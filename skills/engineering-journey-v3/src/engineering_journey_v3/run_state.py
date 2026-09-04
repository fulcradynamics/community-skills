"""Bounded, crash-safe run checkpoint transitions and private run-file layout."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast

from engineering_journey_v3.config import ensure_private_directory
from engineering_journey_v3.discovery import RepositorySnapshot
from engineering_journey_v3.fulcra_gateway import (
    ApprovedPlan,
    canonical_fingerprint,
    moment_record,
)
from engineering_journey_v3.fulcra_registry import RegisteredType
from engineering_journey_v3.plan import Plan
from engineering_journey_v3.progress import ProgressStream
from engineering_journey_v3.workflow import ApprovalError, require_approval

CHECKPOINT_SCHEMA_VERSION = "engineering-journey-v3-checkpoint/v1"
RUN_EVENT_SCHEMA_VERSION = "engineering-journey-v3-run-event/v1"
VALIDATION_REPORT_SCHEMA_VERSION = "engineering-journey-v3-validation-report/v1"
RUN_FILE_ROOT = "/engineering-journey-runs"


class RunStateError(ValueError):
    """A checkpoint transition, resume binding, or run-file invariant failed."""


class RunStatus(StrEnum):
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Bounded state: repository milestones plus pages for only the current repository."""

    run_id: str
    plan_digest: str
    snapshot_digest: str
    invocation_id: str
    stage: str
    status: RunStatus
    repository_total: int
    completed_repository_ids: tuple[int, ...] = ()
    current_repository_id: int | None = None
    page_milestones: Mapping[str, int] = field(default_factory=dict)
    transition_count: int = 0
    schema_version: str = CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise RunStateError("unsupported checkpoint schema version")
        for name in ("run_id", "plan_digest", "snapshot_digest", "invocation_id", "stage"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise RunStateError(f"checkpoint {name} is invalid")
        try:
            uuid.UUID(self.run_id)
            uuid.UUID(self.invocation_id)
        except ValueError as error:
            raise RunStateError("checkpoint run/invocation ID is invalid") from error
        if len(self.plan_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.plan_digest
        ):
            raise RunStateError("checkpoint plan digest is invalid")
        if not self.snapshot_digest.startswith("sha256:"):
            raise RunStateError("checkpoint snapshot digest is invalid")
        for name, value in (
            ("repository_total", self.repository_total),
            ("transition_count", self.transition_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RunStateError(f"checkpoint {name} must be non-negative")
        completed = self.completed_repository_ids
        if tuple(sorted(completed)) != completed or len(completed) != len(set(completed)):
            raise RunStateError("completed repository IDs must be unique and sorted")
        if len(completed) > self.repository_total:
            raise RunStateError("completed repository count exceeds the snapshot")
        if self.current_repository_id is not None and (
            self.current_repository_id < 1 or self.current_repository_id in completed
        ):
            raise RunStateError("current repository ID is invalid")
        if self.current_repository_id is None and self.page_milestones:
            raise RunStateError("page milestones require one current repository")
        if not isinstance(self.page_milestones, Mapping):
            raise RunStateError("page milestones must be an object")
        for source, page in self.page_milestones.items():
            if (
                not isinstance(source, str)
                or not source
                or source != source.strip()
                or isinstance(page, bool)
                or not isinstance(page, int)
                or page < 1
            ):
                raise RunStateError("page milestones are invalid")
        if self.status == RunStatus.COMPLETED and (
            len(completed) != self.repository_total or self.current_repository_id is not None
        ):
            raise RunStateError("completed checkpoint does not reconcile all repositories")

    @property
    def repository_index(self) -> int:
        return len(self.completed_repository_ids) + (1 if self.current_repository_id else 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "plan_digest": self.plan_digest,
            "snapshot_digest": self.snapshot_digest,
            "invocation_id": self.invocation_id,
            "stage": self.stage,
            "status": self.status.value,
            "repository_total": self.repository_total,
            "completed_repository_ids": list(self.completed_repository_ids),
            "current_repository_id": self.current_repository_id,
            "page_milestones": dict(sorted(self.page_milestones.items())),
            "transition_count": self.transition_count,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_json(cls, document: str) -> Checkpoint:
        try:
            value = json.loads(document)
        except json.JSONDecodeError as error:
            raise RunStateError("checkpoint is not valid JSON") from error
        expected = {
            "schema_version",
            "run_id",
            "plan_digest",
            "snapshot_digest",
            "invocation_id",
            "stage",
            "status",
            "repository_total",
            "completed_repository_ids",
            "current_repository_id",
            "page_milestones",
            "transition_count",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise RunStateError("checkpoint fields do not match the schema")
        string_fields = {
            "schema_version",
            "run_id",
            "plan_digest",
            "snapshot_digest",
            "invocation_id",
            "stage",
            "status",
        }
        if not all(isinstance(value[name], str) for name in string_fields):
            raise RunStateError("checkpoint string fields are invalid")
        completed = value["completed_repository_ids"]
        pages = value["page_milestones"]
        if (
            not isinstance(completed, list)
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in completed)
            or not isinstance(pages, dict)
        ):
            raise RunStateError("checkpoint milestone fields are invalid")
        current = value["current_repository_id"]
        if current is not None and (isinstance(current, bool) or not isinstance(current, int)):
            raise RunStateError("checkpoint current repository is invalid")
        try:
            status = RunStatus(value["status"])
        except ValueError as error:
            raise RunStateError("checkpoint status is invalid") from error
        return cls(
            schema_version=value["schema_version"],
            run_id=value["run_id"],
            plan_digest=value["plan_digest"],
            snapshot_digest=value["snapshot_digest"],
            invocation_id=value["invocation_id"],
            stage=value["stage"],
            status=status,
            repository_total=value["repository_total"],
            completed_repository_ids=tuple(completed),
            current_repository_id=current,
            page_milestones=cast(dict[str, int], pages),
            transition_count=value["transition_count"],
        )


class FileUploader(Protocol):
    def upload_path(
        self, local_path: Path, remote_path: str, approval: ApprovedPlan
    ) -> dict[str, Any]: ...


class RunFiles:
    """Owner-only local run files with versioned remote private-file destinations."""

    PLAN = "plan.json"
    SNAPSHOT = "repository-snapshot.json"
    CHECKPOINT = "checkpoint.json"
    PROGRESS = "progress.jsonl"
    HANDOFF = "handoff.json"
    VALIDATION = "validation-report.json"
    _UPLOADABLE = {PLAN, SNAPSHOT, CHECKPOINT, PROGRESS, HANDOFF, VALIDATION}

    def __init__(self, directory: Path) -> None:
        self.directory = ensure_private_directory(directory.expanduser())

    def path(self, name: str) -> Path:
        if name not in self._UPLOADABLE:
            raise RunStateError("run file name is not in the private artifact contract")
        return self.directory / name

    @property
    def progress(self) -> ProgressStream:
        return ProgressStream(self.path(self.PROGRESS))

    @staticmethod
    def _atomic_write(path: Path, content: bytes, *, immutable: bool = False) -> None:
        if path.is_symlink():
            raise RunStateError("run files must not be symlinks")
        if immutable and path.exists():
            existing = path.read_bytes()
            if hmac.compare_digest(existing, content):
                return
            raise RunStateError(f"immutable run file changed: {path.name}")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            written = os.write(descriptor, content)
            if written != len(content):
                raise OSError("short run-file write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

    def initialize(
        self, plan: Plan, snapshot: RepositorySnapshot, invocation_id: str
    ) -> Checkpoint:
        if self.path(self.CHECKPOINT).exists():
            raise RunStateError("run checkpoint already exists; review and resume it instead")
        if plan.repository_snapshot_digest != snapshot.digest:
            raise RunStateError("plan is not bound to the supplied repository snapshot")
        if (plan.identity, plan.start_utc, plan.end_utc) != (
            snapshot.identity,
            snapshot.start_utc,
            snapshot.end_utc,
        ):
            raise RunStateError("plan and repository snapshot scope differ")
        self._atomic_write(
            self.path(self.PLAN),
            (json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode(),
            immutable=True,
        )
        self._atomic_write(self.path(self.SNAPSHOT), snapshot.to_json().encode(), immutable=True)
        checkpoint = Checkpoint(
            run_id=plan.run_id,
            plan_digest=plan.digest,
            snapshot_digest=snapshot.digest,
            invocation_id=invocation_id,
            stage=plan.stages[0],
            status=RunStatus.RUNNING,
            repository_total=len(snapshot.repositories),
        )
        self.save_checkpoint(checkpoint)
        return checkpoint

    def load_plan(self) -> Plan:
        try:
            value = json.loads(self.path(self.PLAN).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise RunStateError("saved immutable plan is missing or malformed") from error
        if not isinstance(value, dict):
            raise RunStateError("saved immutable plan is not an object")
        return Plan.from_dict(value)

    def load_snapshot(self) -> RepositorySnapshot:
        try:
            return RepositorySnapshot.from_json(
                self.path(self.SNAPSHOT).read_text(encoding="utf-8")
            )
        except FileNotFoundError as error:
            raise RunStateError("saved repository snapshot is missing") from error

    def load_checkpoint(self) -> Checkpoint:
        try:
            return Checkpoint.from_json(self.path(self.CHECKPOINT).read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise RunStateError("saved checkpoint is missing") from error

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        plan = self.load_plan()
        snapshot = self.load_snapshot()
        self._validate_bindings(plan, snapshot, checkpoint)
        self._atomic_write(self.path(self.CHECKPOINT), checkpoint.to_json().encode())

    def save_validation_report(self, report: Mapping[str, Any]) -> None:
        """Persist a strict report bound to this run after publication verification."""
        plan = self.load_plan()
        expected_fields = {
            "schema_version",
            "plan_digest",
            "run_id",
            "context_id",
            "evidence_count",
            "citation_count",
            "narrative_sha256",
            "sources_sha256",
            "remote_outputs",
            "remote_verified",
            "status",
        }
        if set(report) != expected_fields:
            raise RunStateError("validation report fields do not match the v3 schema")
        if (
            report["schema_version"] != VALIDATION_REPORT_SCHEMA_VERSION
            or report["plan_digest"] != plan.digest
            or report["run_id"] != plan.run_id
            or report["remote_outputs"] != list(plan.outputs)
            or report["remote_verified"] is not True
            or report["status"] != "completed"
        ):
            raise RunStateError("validation report is not bound to the completed publication")
        self._atomic_write(
            self.path(self.VALIDATION),
            (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )

    @staticmethod
    def _validate_bindings(
        plan: Plan, snapshot: RepositorySnapshot, checkpoint: Checkpoint
    ) -> None:
        repository_ids = {repository.database_id for repository in snapshot.repositories}
        checkpoint_ids = set(checkpoint.completed_repository_ids)
        if checkpoint.current_repository_id is not None:
            checkpoint_ids.add(checkpoint.current_repository_id)
        if (
            checkpoint.run_id != plan.run_id
            or checkpoint.plan_digest != plan.digest
            or checkpoint.snapshot_digest != snapshot.digest
            or plan.repository_snapshot_digest != snapshot.digest
            or checkpoint.repository_total != len(snapshot.repositories)
            or checkpoint.stage not in plan.stages
            or not checkpoint_ids.issubset(repository_ids)
        ):
            raise RunStateError("checkpoint, plan, and repository snapshot bindings differ")

    def review_resume(self) -> tuple[Plan, RepositorySnapshot, Checkpoint]:
        """Load and cross-check durable resume state before presenting it for approval."""
        plan = self.load_plan()
        snapshot = self.load_snapshot()
        checkpoint = self.load_checkpoint()
        self._validate_bindings(plan, snapshot, checkpoint)
        return plan, snapshot, checkpoint

    def resume(self, supplied_digest: str | None, invocation_id: str) -> Checkpoint:
        """Verify all immutable bindings, require renewed approval, and start an invocation."""
        plan, _snapshot, checkpoint = self.review_resume()
        try:
            require_approval(plan, supplied_digest)
        except ApprovalError as error:
            raise RunStateError(str(error)) from error
        if checkpoint.status == RunStatus.COMPLETED:
            raise RunStateError("completed run cannot be resumed")
        resumed = replace(
            checkpoint,
            invocation_id=invocation_id,
            status=RunStatus.RUNNING,
            transition_count=checkpoint.transition_count + 1,
        )
        self.save_checkpoint(resumed)
        return resumed

    def remote_path(self, identity: str, run_id: str, name: str) -> str:
        self.path(name)
        if not identity or "/" in identity:
            raise RunStateError("identity is invalid for a private run-file path")
        return str(PurePosixPath(RUN_FILE_ROOT) / identity / run_id / name)

    def upload(self, name: str, uploader: FileUploader, approval: ApprovedPlan) -> dict[str, Any]:
        plan = self.load_plan()
        if approval.plan.digest != plan.digest:
            raise RunStateError("private run-file upload approval does not match its plan")
        local = self.path(name)
        if not local.is_file() or local.is_symlink():
            raise RunStateError("private run file is missing or unsafe")
        return uploader.upload_path(
            local,
            self.remote_path(plan.identity, plan.run_id, name),
            approval,
        )


class CheckpointJournal:
    """Persist every bounded transition before allowing the caller to continue."""

    def __init__(self, files: RunFiles, checkpoint: Checkpoint) -> None:
        self.files = files
        self.current = checkpoint

    def _commit(self, checkpoint: Checkpoint) -> Checkpoint:
        self.files.save_checkpoint(checkpoint)
        self.current = checkpoint
        return checkpoint

    def begin_repository(self, repository_id: int) -> Checkpoint:
        return self._commit(begin_repository(self.current, repository_id))

    def complete_page(self, source: str, page: int) -> Checkpoint:
        return self._commit(complete_page(self.current, source, page))

    def complete_repository(self, repository_id: int) -> Checkpoint:
        return self._commit(complete_repository(self.current, repository_id))

    def transition_stage(self, stage: str) -> Checkpoint:
        return self._commit(transition_stage(self.current, stage))

    def interrupt(self) -> Checkpoint:
        return self._commit(stop_checkpoint(self.current, RunStatus.INTERRUPTED))

    def fail(self) -> Checkpoint:
        return self._commit(stop_checkpoint(self.current, RunStatus.FAILED))

    def complete(self) -> Checkpoint:
        return self._commit(stop_checkpoint(self.current, RunStatus.COMPLETED))


def begin_repository(checkpoint: Checkpoint, repository_id: int) -> Checkpoint:
    if checkpoint.status != RunStatus.RUNNING or checkpoint.current_repository_id is not None:
        raise RunStateError("cannot begin a repository from the current checkpoint")
    if (
        repository_id in checkpoint.completed_repository_ids
        or len(checkpoint.completed_repository_ids) >= checkpoint.repository_total
    ):
        raise RunStateError("repository is already complete or outside the snapshot")
    return replace(
        checkpoint,
        current_repository_id=repository_id,
        page_milestones={},
        transition_count=checkpoint.transition_count + 1,
    )


def complete_page(checkpoint: Checkpoint, source: str, page: int) -> Checkpoint:
    if checkpoint.status != RunStatus.RUNNING or checkpoint.current_repository_id is None:
        raise RunStateError("page milestone requires a running current repository")
    previous = checkpoint.page_milestones.get(source, 0)
    if not source or source != source.strip() or page != previous + 1:
        raise RunStateError("page milestones must advance exactly once per source")
    return replace(
        checkpoint,
        page_milestones={**checkpoint.page_milestones, source: page},
        transition_count=checkpoint.transition_count + 1,
    )


def complete_repository(checkpoint: Checkpoint, repository_id: int) -> Checkpoint:
    if checkpoint.status != RunStatus.RUNNING or checkpoint.current_repository_id != repository_id:
        raise RunStateError("repository completion does not match the current repository")
    completed = tuple(sorted((*checkpoint.completed_repository_ids, repository_id)))
    return replace(
        checkpoint,
        completed_repository_ids=completed,
        current_repository_id=None,
        page_milestones={},
        transition_count=checkpoint.transition_count + 1,
    )


def transition_stage(checkpoint: Checkpoint, stage: str) -> Checkpoint:
    if checkpoint.status != RunStatus.RUNNING or checkpoint.current_repository_id is not None:
        raise RunStateError("stage transition requires a repository boundary")
    if not stage or stage == checkpoint.stage:
        raise RunStateError("stage transition must advance to a new non-empty stage")
    return replace(checkpoint, stage=stage, transition_count=checkpoint.transition_count + 1)


def stop_checkpoint(checkpoint: Checkpoint, status: RunStatus) -> Checkpoint:
    if status not in {RunStatus.INTERRUPTED, RunStatus.FAILED, RunStatus.COMPLETED}:
        raise RunStateError("stop status must be interrupted, failed, or completed")
    return replace(checkpoint, status=status, transition_count=checkpoint.transition_count + 1)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_event_record(
    *,
    plan: Plan,
    checkpoint: Checkpoint,
    event: str,
    recorded_at: str,
    tag_ids: list[str],
    sources: list[str],
    registered_type: RegisteredType,
) -> dict[str, Any]:
    """Build one deterministic bounded run event for a transition, never a raw fact."""
    if registered_type.key != "run_event":
        raise RunStateError("run event requires the isolated v3 run-event type")
    immutable = {
        "run_id": plan.run_id,
        "invocation_id": checkpoint.invocation_id,
        "transition_count": checkpoint.transition_count,
        "event": event,
        "stage": checkpoint.stage,
        "repository_id": checkpoint.current_repository_id,
        "page_milestones": dict(sorted(checkpoint.page_milestones.items())),
    }
    fingerprint = canonical_fingerprint("run_event", plan.identity, immutable)
    return moment_record(
        fingerprint=fingerprint,
        recorded_at=recorded_at,
        note_payload={
            "run_event_schema_version": RUN_EVENT_SCHEMA_VERSION,
            **immutable,
            "state": checkpoint.status.value,
            "snapshot_digest": checkpoint.snapshot_digest,
        },
        tag_ids=tag_ids,
        sources=sources,
    )


def file_digest(path: Path) -> str:
    """Return a content digest useful for upload/version verification without file content."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
