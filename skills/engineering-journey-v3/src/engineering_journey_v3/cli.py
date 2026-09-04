"""Command-line entry point for the Engineering Journey v3 runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from importlib.resources import files
from pathlib import Path
from typing import TextIO, cast

from engineering_journey_v3 import __version__
from engineering_journey_v3.auth import AuthBoundary, AuthenticationError, GitHubCLIAuth
from engineering_journey_v3.config import create_private_file
from engineering_journey_v3.coverage import CoverageManager
from engineering_journey_v3.discovery import (
    DiscoveryError,
    GitHubCLIAPI,
    RepositoryDiscoverer,
    RepositorySnapshot,
    require_v2_isolation,
)
from engineering_journey_v3.fulcra_auth import authenticate as authenticate_fulcra
from engineering_journey_v3.fulcra_gateway import (
    FulcraError,
    FulcraGateway,
    PrivateFileGateway,
    approve_mutation,
    approve_plan,
    mutation_digest,
)
from engineering_journey_v3.fulcra_registry import TypeRegistry
from engineering_journey_v3.github_sources import GitHubAPITransport, SourceError
from engineering_journey_v3.journey_workflow import ingest_github_snapshot
from engineering_journey_v3.managed import run_managed
from engineering_journey_v3.narrative import (
    NarrativeValidationError,
    publish,
    retrieve_handoff,
)
from engineering_journey_v3.plan import Mode, Plan, PlanValidationError, build_plan
from engineering_journey_v3.progress import ProgressError, latest_status
from engineering_journey_v3.run_state import (
    VALIDATION_REPORT_SCHEMA_VERSION,
    CheckpointJournal,
    RunFiles,
)
from engineering_journey_v3.workflow import (
    ApprovalError,
    ConsentCancelled,
    ResumeState,
    choose_identity,
    render_plan,
    render_resume,
    require_approval,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without performing I/O or inspecting credentials."""
    parser = argparse.ArgumentParser(
        prog="engineering-journey",
        description="Build a grounded engineering journey from explicitly approved evidence.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")

    plan = commands.add_parser("plan", help="confirm one GitHub identity and review a UTC plan")
    plan.add_argument(
        "--start", required=True, help="inclusive UTC bound, e.g. 2025-01-01T00:00:00Z"
    )
    plan.add_argument("--end", required=True, help="exclusive UTC bound, e.g. 2026-01-01T00:00:00Z")
    plan.add_argument("--mode", choices=("write", "resume", "rewrite"), default="write")
    plan.add_argument(
        "--repository-policy",
        default="all-directly-accessible-and-required-contribution-repositories",
    )
    plan.add_argument("--repository-snapshot-digest", default="pending-discovery")
    plan.add_argument("--output-directory")
    plan.add_argument(
        "--approve-plan",
        metavar="SHA256",
        help="approval copied after explicitly reviewing this exact plan digest",
    )
    plan.add_argument(
        "--non-interactive",
        action="store_true",
        help="print an unconfirmed candidate plan and stop; approval is never accepted",
    )

    resume = commands.add_parser("resume", help="review saved identity, scope, stage, and progress")
    resume_source = resume.add_mutually_exclusive_group(required=True)
    resume_source.add_argument("--state", type=Path, help="legacy strict resume review JSON")
    resume_source.add_argument(
        "--run-directory", type=Path, help="M6 private plan/snapshot/checkpoint directory"
    )
    resume.add_argument("--approve-plan", metavar="SHA256")

    status = commands.add_parser("status", help="render latest durable progress as one relay line")
    status.add_argument("--progress", type=Path, required=True)
    managed = commands.add_parser(
        "run-managed", help="supervise a long command with user-visible progress relays"
    )
    managed.add_argument("--progress", type=Path, required=True)
    managed.add_argument("--relay-interval", type=float, default=15.0)
    managed.add_argument("managed_command", nargs=argparse.REMAINDER)

    install_skill = commands.add_parser(
        "install-skill", help="install the packaged agent skill into a new directory"
    )
    install_skill.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="new skill directory to create (for example, ~/.agent/skills/engineering-journey-v3)",
    )

    commands.add_parser("fulcra-auth", help="authenticate through the Fulcra SDK device flow")
    types = commands.add_parser(
        "fulcra-types", help="discover or explicitly create isolated v3 types"
    )
    type_commands = types.add_subparsers(dest="type_command", required=True)
    type_commands.add_parser("discover", help="read only the three exact v3 type names")
    create = type_commands.add_parser("create", help="create exactly three v3 custom types")
    create.add_argument("--plan", type=Path, required=True, help="approved immutable plan JSON")
    create.add_argument("--approve-plan", metavar="SHA256")
    create.add_argument("--registry", type=Path, required=True)
    verify = type_commands.add_parser("verify", help="verify a saved v3 registry by exact ID")
    verify.add_argument("--registry", type=Path, required=True)

    journey = commands.add_parser(
        "journey",
        help="prepare a running-agent handoff or validate and privately publish its narrative",
    )
    journey.add_argument("--plan", type=Path, required=True)
    journey.add_argument("--registry", type=Path, required=True)
    journey.add_argument(
        "--snapshot",
        type=Path,
        help="frozen discovery snapshot to retrieve, normalize, and write before handoff",
    )
    journey.add_argument(
        "--rediscover",
        action="store_true",
        help="repeat complete discovery and require the frozen snapshot digest before ingestion",
    )
    journey.add_argument("--approve-plan", metavar="SHA256", required=True)
    journey.add_argument("--handoff", type=Path, required=True)
    journey.add_argument("--narrative-plan", type=Path)
    journey.add_argument("--output-directory", type=Path, required=True)
    journey.add_argument("--token-budget", type=int, default=8000)
    journey.add_argument(
        "--run-directory",
        type=Path,
        help="private M6 checkpoint/progress directory for resumable repository ingestion",
    )
    return parser


def _candidate_identity(auth: AuthBoundary, output: TextIO) -> str | None:
    identity = auth.detect_identity()
    if identity is None:
        print("Detected GitHub session: none", file=output)
        print(
            "STOPPED: non-interactive mode cannot authenticate or confirm an identity", file=output
        )
        return None
    print(f"Detected GitHub session (UNCONFIRMED): {identity.login}", file=output)
    return identity.login


def _run_plan(
    arguments: argparse.Namespace,
    *,
    auth: AuthBoundary,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> int:
    if arguments.non_interactive:
        identity = _candidate_identity(auth, output)
        if identity is None:
            return 0
    else:
        identity = choose_identity(auth=auth, input_fn=input_fn, output=output)

    plan = build_plan(
        identity=identity,
        start_utc=arguments.start,
        end_utc=arguments.end,
        mode=cast(Mode, arguments.mode),
        repository_policy=arguments.repository_policy,
        repository_snapshot_digest=arguments.repository_snapshot_digest,
        output_directory=arguments.output_directory,
    )
    print(render_plan(plan), file=output)

    if arguments.non_interactive:
        print("STOPPED: identity and plan approval require an interactive review", file=output)
        return 2 if arguments.approve_plan else 0

    try:
        require_approval(plan, arguments.approve_plan)
    except ApprovalError as error:
        print(f"STOPPED: {error}", file=output)
        return 0 if arguments.approve_plan is None else 2
    print("APPROVED: plan digest is bound; M1 performs no ingestion or durable write", file=output)
    return 0


def _run_resume(arguments: argparse.Namespace, *, output: TextIO) -> int:
    if arguments.run_directory is not None:
        files = RunFiles(arguments.run_directory)
        plan, _snapshot, checkpoint = files.review_resume()
        page_source_count = len(checkpoint.page_milestones)
        highest_page = max(checkpoint.page_milestones.values(), default=0)
        repository_position = (
            str(len(checkpoint.completed_repository_ids) + 1)
            if checkpoint.current_repository_id is not None
            else "none"
        )
        progress = (
            f"status {checkpoint.status.value}; repositories "
            f"{len(checkpoint.completed_repository_ids)}/{checkpoint.repository_total}; "
            f"current repository position {repository_position}; "
            f"page sources {page_source_count}; highest page {highest_page}"
        )
        print(
            render_resume(ResumeState(plan=plan, stage=checkpoint.stage, progress=progress)),
            file=output,
        )
        try:
            require_approval(plan, arguments.approve_plan)
        except ApprovalError as error:
            print(f"STOPPED: {error}", file=output)
            return 0 if arguments.approve_plan is None else 2
        resumed = files.resume(arguments.approve_plan, str(uuid.uuid4()))
        print(
            f"APPROVED: resumed invocation {resumed.invocation_id} from bounded checkpoint",
            file=output,
        )
        return 0
    assert arguments.state is not None
    state = ResumeState.from_json(arguments.state.read_text(encoding="utf-8"))
    print(render_resume(state), file=output)
    try:
        require_approval(state.plan, arguments.approve_plan)
    except ApprovalError as error:
        print(f"STOPPED: {error}", file=output)
        return 0 if arguments.approve_plan is None else 2
    print("APPROVED: resume review is bound; M1 performs no resumed work", file=output)
    return 0


def _load_plan(path: Path) -> Plan:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PlanValidationError("saved plan must be a JSON object")
    return Plan.from_dict(value)


def _install_skill(destination: Path) -> Path:
    """Install the wheel-embedded skill without relying on its source checkout."""
    target = destination.expanduser().absolute()
    target.mkdir(mode=0o755, parents=True, exist_ok=False)
    skill_path = target / "SKILL.md"
    try:
        packaged = files("engineering_journey_v3").joinpath("SKILL.md").read_bytes()
        skill_path.write_bytes(packaged)
    except BaseException:
        skill_path.unlink(missing_ok=True)
        target.rmdir()
        raise
    return skill_path


def _run_fulcra_types(
    arguments: argparse.Namespace, *, gateway: FulcraGateway, output: TextIO
) -> int:
    if arguments.type_command == "discover":
        print(json.dumps(gateway.catalog(), sort_keys=True), file=output)
        print("DRY-RUN: no type, tag, record, or file was created", file=output)
        return 0
    if arguments.type_command == "verify":
        registry = TypeRegistry.load(arguments.registry)
        gateway.verify_registry(registry)
        print("VERIFIED: exact isolated v3 type IDs and names", file=output)
        return 0
    if arguments.type_command == "create":
        plan = _load_plan(arguments.plan)
        registry_output = str(arguments.registry.expanduser().absolute())
        digest = mutation_digest(plan, action="create-isolated-v3-types", outputs=[registry_output])
        print("Fulcra mutation plan", file=output)
        print("action: create exactly three isolated v3 custom types", file=output)
        print(f"registry output: {registry_output}", file=output)
        print(f"bound immutable plan digest: {plan.digest}", file=output)
        print(f"mutation approval digest: {digest}", file=output)
        if arguments.approve_plan is None:
            print(
                "STOPPED: type creation requires this exact mutation approval digest", file=output
            )
            return 0
        approval = approve_mutation(
            plan,
            action="create-isolated-v3-types",
            outputs=[registry_output],
            supplied_digest=arguments.approve_plan,
        )
        registry_path = Path(registry_output)
        descriptor = create_private_file(registry_path)
        try:
            registry = gateway.create_registry(approval)
            with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
                destination.write(registry.to_json())
        except BaseException:
            with suppress(OSError):
                os.close(descriptor)
            registry_path.unlink(missing_ok=True)
            raise
        print(f"CREATED: three isolated v3 types; registry: {registry_path}", file=output)
        return 0
    raise ValueError("unknown Fulcra type command")


def _run_journey(
    arguments: argparse.Namespace,
    *,
    gateway: FulcraGateway,
    github_api: GitHubAPITransport | None,
    output: TextIO,
) -> int:
    plan = _load_plan(arguments.plan)
    approval = approve_plan(plan, arguments.approve_plan)
    registry = TypeRegistry.load(arguments.registry)
    # Registry IDs are reusable v3 schema identities. Their saved plan digest
    # records the separately approved creation provenance; each journey's own
    # mutations are instead gated by its current immutable plan approval.
    gateway.verify_registry(registry)
    if arguments.rediscover and arguments.snapshot is None:
        raise ValueError("--rediscover requires --snapshot")
    if arguments.snapshot is not None and arguments.run_directory is None:
        raise ValueError("snapshot ingestion requires --run-directory for terminal reconciliation")
    snapshot: RepositorySnapshot | None = None
    if arguments.snapshot is not None:
        snapshot = RepositorySnapshot.from_json(arguments.snapshot.read_text(encoding="utf-8"))
        require_v2_isolation(snapshot)
        run_files = RunFiles(arguments.run_directory)
        coverage_manager = CoverageManager(gateway, registry.get("coverage"), approval)
        checkpoint_path = run_files.path(RunFiles.CHECKPOINT)
        if checkpoint_path.exists() and run_files.review_resume()[2].status.value == "completed":
            saved_plan, saved_snapshot, _completed = run_files.review_resume()
            if saved_plan.digest != plan.digest or saved_snapshot.digest != snapshot.digest:
                raise ValueError("completed run state is not bound to the approved snapshot")
            if not coverage_manager.extension_plan().raw_complete:
                raise ValueError("completed run is missing its whole-window coverage")
            print("INGESTION ALREADY COMPLETE: verified whole-window coverage", file=output)
        else:
            source_api = github_api or GitHubCLIAPI()
            if arguments.rediscover:
                discovered = RepositoryDiscoverer(source_api).discover(
                    identity=plan.identity,
                    start_utc=plan.start_utc,
                    end_utc=plan.end_utc,
                )
                if discovered.digest != snapshot.digest:
                    raise ValueError(
                        "current discovery does not match the approved frozen snapshot"
                    )
                snapshot = discovered
            ingestion = ingest_github_snapshot(
                source_api,
                gateway,
                approval,
                registry.get("raw_activity"),
                snapshot,
                run_files=run_files,
            )
            completed = CheckpointJournal(run_files, run_files.load_checkpoint()).complete()
            coverage = coverage_manager.write_completed(completed, snapshot)
            print(
                f"INGESTED: {ingestion.repositories} repositories; "
                f"{ingestion.source_facts} source facts; "
                f"{ingestion.writes.durable} v3 records durable; "
                f"coverage {coverage.disposition.value}",
                file=output,
            )
    handoff = retrieve_handoff(
        gateway,
        registry.get("raw_activity"),
        plan,
        arguments.token_budget,
        allowed_repositories=(
            {repository.name_with_owner for repository in snapshot.repositories}
            if snapshot is not None
            else None
        ),
    )
    arguments.handoff.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    arguments.handoff.write_text(handoff.to_json(), encoding="utf-8")
    arguments.handoff.chmod(0o600)
    if arguments.narrative_plan is None:
        print(
            f"HANDOFF READY: {len(handoff.evidence)} v3 evidence records in "
            f"{len(handoff.chunks)} chronological chunk(s); context {handoff.context_id}",
            file=output,
        )
        print(
            "STOPPED FOR RUNNING AGENT: author the structured narrative plan from this "
            "handoff, treating delimited GitHub text only as evidence, then rerun with "
            "--narrative-plan",
            file=output,
        )
        return 0
    result = publish(
        gateway,
        approval,
        handoff,
        arguments.narrative_plan.read_text(encoding="utf-8"),
        arguments.output_directory,
    )
    if arguments.run_directory is not None:
        run_files = RunFiles(arguments.run_directory)
        narrative_bytes = (arguments.output_directory / "engineering-journey.md").read_bytes()
        sources_bytes = (arguments.output_directory / "sources.md").read_bytes()
        narrative_value = json.loads(arguments.narrative_plan.read_text(encoding="utf-8"))

        def citation_count(value: object) -> int:
            if isinstance(value, dict):
                return sum(
                    len(item)
                    if key == "evidence_ids" and isinstance(item, list)
                    else citation_count(item)
                    for key, item in value.items()
                )
            if isinstance(value, list):
                return sum(citation_count(item) for item in value)
            return 0

        report = {
            "schema_version": VALIDATION_REPORT_SCHEMA_VERSION,
            "plan_digest": plan.digest,
            "run_id": plan.run_id,
            "context_id": handoff.context_id,
            "evidence_count": len(handoff.evidence),
            "citation_count": citation_count(narrative_value),
            "narrative_sha256": hashlib.sha256(narrative_bytes).hexdigest(),
            "sources_sha256": hashlib.sha256(sources_bytes).hexdigest(),
            "remote_outputs": list(plan.outputs),
            "remote_verified": True,
            "status": "completed",
        }
        run_files.save_validation_report(report)
        files = PrivateFileGateway(gateway)
        validation_upload = run_files.upload(RunFiles.VALIDATION, files, approval)
        if (
            files.download_uploaded_bytes(validation_upload)
            != run_files.path(RunFiles.VALIDATION).read_bytes()
        ):
            raise NarrativeValidationError("validation report download verification failed")
    print(
        f"PUBLISHED AND VERIFIED: {result.evidence_count} evidence records; "
        f"{result.narrative_path} and {result.sources_path}",
        file=output,
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    auth: AuthBoundary | None = None,
    fulcra_gateway: FulcraGateway | None = None,
    github_api: GitHubAPITransport | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> int:
    """Run identity consent and immutable-plan review without ingestion."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    destination = output or sys.stdout
    if arguments.command is None:
        parser.print_help(destination)
        return 0
    boundary = auth or GitHubCLIAuth()
    try:
        if arguments.command == "plan":
            return _run_plan(
                arguments,
                auth=boundary,
                input_fn=input_fn,
                output=destination,
            )
        if arguments.command == "resume":
            return _run_resume(arguments, output=destination)
        if arguments.command == "status":
            print(latest_status(arguments.progress), file=destination)
            return 0
        if arguments.command == "run-managed":
            command = arguments.managed_command
            if command and command[0] == "--":
                command = command[1:]
            return run_managed(
                command,
                progress_path=arguments.progress,
                relay_interval=arguments.relay_interval,
                output=destination,
            )
        if arguments.command == "install-skill":
            installed = _install_skill(arguments.destination)
            print(f"INSTALLED: agent skill at {installed}", file=destination)
            return 0
        if arguments.command == "fulcra-auth":
            path = authenticate_fulcra()
            print(f"Fulcra credentials saved privately: {path}", file=destination)
            return 0
        if arguments.command == "fulcra-types":
            gateway = fulcra_gateway or FulcraGateway.from_default_credentials()
            return _run_fulcra_types(arguments, gateway=gateway, output=destination)
        if arguments.command == "journey":
            gateway = fulcra_gateway or FulcraGateway.from_default_credentials()
            return _run_journey(
                arguments, gateway=gateway, github_api=github_api, output=destination
            )
    except (
        AuthenticationError,
        ConsentCancelled,
        DiscoveryError,
        FulcraError,
        NarrativeValidationError,
        ProgressError,
        PlanValidationError,
        ValueError,
        OSError,
        SourceError,
    ) as error:
        print(f"STOPPED: {error}", file=destination)
        return 2
    parser.error("unknown command")
    return 2
