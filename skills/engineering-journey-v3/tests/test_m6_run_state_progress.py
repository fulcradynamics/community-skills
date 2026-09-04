from __future__ import annotations

import io
import json
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from engineering_journey_v3.cli import main
from engineering_journey_v3.discovery import (
    Provenance,
    Repository,
    RepositorySnapshot,
    bind_snapshot,
)
from engineering_journey_v3.fulcra_gateway import approve_plan
from engineering_journey_v3.fulcra_registry import API_VERSION, TYPE_DEFINITIONS, RegisteredType
from engineering_journey_v3.managed import ManagedProcessError, run_managed
from engineering_journey_v3.plan import Plan, build_plan
from engineering_journey_v3.progress import (
    ProgressError,
    ProgressEvent,
    ProgressStream,
    WorkCounters,
    latest_status,
)
from engineering_journey_v3.run_state import (
    Checkpoint,
    RunFiles,
    RunStateError,
    RunStatus,
    begin_repository,
    complete_page,
    complete_repository,
    run_event_record,
    stop_checkpoint,
)

START = "2025-01-01T00:00:00Z"
END = "2026-01-01T00:00:00Z"
NOW = "2026-01-01T01:02:03Z"


def snapshot() -> RepositorySnapshot:
    repositories = tuple(
        Repository(
            database_id=index,
            node_id=f"R_{index}",
            name_with_owner=f"synthetic/repository-{index}",
            private=index == 2,
            archived=False,
            url=f"https://github.com/synthetic/repository-{index}",
            provenance=(Provenance("direct-access", 1, "synthetic:page:1"),),
        )
        for index in range(1, 4)
    )
    return RepositorySnapshot(
        identity="synthetic-user", start_utc=START, end_utc=END, repositories=repositories
    )


def frozen_plan() -> Plan:
    return bind_snapshot(
        build_plan(identity="synthetic-user", start_utc=START, end_utc=END), snapshot()
    )


def invocation() -> str:
    return str(uuid.uuid4())


def test_hard_killed_multi_repository_run_resumes_fresh_with_renewed_approval(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run"
    plan = frozen_plan()
    files = RunFiles(run_directory)
    files.initialize(plan, snapshot(), invocation())

    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import os,sys,time;"
                "from pathlib import Path;"
                "from engineering_journey_v3.run_state import "
                "RunFiles,begin_repository,complete_page,complete_repository;"
                "f=RunFiles(Path(sys.argv[1]));c=f.load_checkpoint();"
                "c=begin_repository(c,1);c=complete_page(c,'commits',1);"
                "c=complete_repository(c,1);c=begin_repository(c,2);"
                "c=complete_page(c,'reviews',1);f.save_checkpoint(c);"
                "print('checkpoint-durable',flush=True);time.sleep(60)"
            ),
            str(run_directory),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "checkpoint-durable"
    child.send_signal(signal.SIGKILL)
    assert child.wait(timeout=5) == -signal.SIGKILL

    fresh = RunFiles(run_directory)
    recovered = fresh.load_checkpoint()
    assert recovered.completed_repository_ids == (1,)
    assert recovered.current_repository_id == 2
    assert recovered.page_milestones == {"reviews": 1}
    with pytest.raises(RunStateError, match="stopped by default"):
        fresh.resume(None, invocation())
    resumed = fresh.resume(plan.digest, invocation())
    assert resumed.status == RunStatus.RUNNING
    assert resumed.completed_repository_ids == (1,)
    assert resumed.current_repository_id == 2
    assert resumed.page_milestones == {"reviews": 1}
    assert resumed.invocation_id != recovered.invocation_id


def test_resume_rejects_changed_plan_snapshot_or_checkpoint_binding(tmp_path: Path) -> None:
    plan = frozen_plan()
    files = RunFiles(tmp_path / "run")
    files.initialize(plan, snapshot(), invocation())
    changed = json.loads(files.path(RunFiles.PLAN).read_text())
    changed["end_utc"] = "2026-01-02T00:00:00Z"
    files.path(RunFiles.PLAN).write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(RunStateError, match="bindings differ"):
        files.resume(Plan.from_dict(changed).digest, invocation())


def test_resume_review_rejects_repository_outside_frozen_snapshot(tmp_path: Path) -> None:
    files = RunFiles(tmp_path / "run")
    checkpoint = files.initialize(frozen_plan(), snapshot(), invocation())
    payload = checkpoint.as_dict()
    payload["current_repository_id"] = 999
    files.path(RunFiles.CHECKPOINT).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RunStateError, match="bindings differ"):
        files.review_resume()


def test_initialize_never_clobbers_an_existing_checkpoint(tmp_path: Path) -> None:
    files = RunFiles(tmp_path / "run")
    original = files.initialize(frozen_plan(), snapshot(), invocation())
    with pytest.raises(RunStateError, match="already exists"):
        files.initialize(frozen_plan(), snapshot(), invocation())
    assert files.load_checkpoint() == original


def test_cli_redisplays_bounded_checkpoint_and_renews_resume_approval(tmp_path: Path) -> None:
    plan = frozen_plan()
    files = RunFiles(tmp_path / "run")
    checkpoint = files.initialize(plan, snapshot(), invocation())
    checkpoint = complete_page(begin_repository(checkpoint, 1), "commits", 1)
    files.save_checkpoint(checkpoint)

    stopped = io.StringIO()
    assert main(["resume", "--run-directory", str(files.directory)], output=stopped) == 0
    rendered = stopped.getvalue()
    assert "identity: synthetic-user" in rendered
    assert f"repository snapshot digest: {snapshot().digest}" in rendered
    assert "saved stage: repository-discovery" in rendered
    assert "current repository position 1; page sources 1; highest page 1" in rendered
    assert "STOPPED" in rendered

    approved = io.StringIO()
    assert (
        main(
            [
                "resume",
                "--run-directory",
                str(files.directory),
                "--approve-plan",
                plan.digest,
            ],
            output=approved,
        )
        == 0
    )
    assert "APPROVED: resumed invocation" in approved.getvalue()
    assert files.load_checkpoint().invocation_id != checkpoint.invocation_id


def test_checkpoint_transitions_are_page_repository_bounded_not_raw_event_sized(
    tmp_path: Path,
) -> None:
    files = RunFiles(tmp_path / "run")
    checkpoint = files.initialize(frozen_plan(), snapshot(), invocation())
    checkpoint = begin_repository(checkpoint, 1)
    checkpoint = complete_page(checkpoint, "commits", 1)
    checkpoint = complete_page(checkpoint, "commits", 2)
    checkpoint = complete_page(checkpoint, "reviews", 1)
    files.save_checkpoint(checkpoint)
    payload = json.loads(files.path(RunFiles.CHECKPOINT).read_text())
    assert payload["page_milestones"] == {"commits": 2, "reviews": 1}
    assert "records" not in payload and "raw_events" not in payload

    checkpoint = complete_repository(checkpoint, 1)
    assert checkpoint.page_milestones == {}
    assert checkpoint.completed_repository_ids == (1,)
    with pytest.raises(RunStateError, match="advance exactly"):
        complete_page(begin_repository(checkpoint, 2), "commits", 2)


def progress_event(
    *,
    event: str = "heartbeat",
    heartbeat: bool = True,
    terminal: dict[str, int] | None = None,
) -> ProgressEvent:
    return ProgressEvent(
        run_id=frozen_plan().run_id,
        invocation_id=invocation(),
        event=event,
        stage="github-ingestion",
        timestamp_utc=NOW,
        elapsed_seconds=12.5,
        repository_current="synthetic/repository-2",
        repository_index=2,
        repository_total=3,
        page_current=4,
        counters=WorkCounters(
            repositories_completed=1,
            pages_completed=7,
            api_calls=11,
            writes_attempted=5,
            writes_durable=4,
            deduplicated=1,
            retries=2,
        ),
        current_operation="retrying pull-request reviews",
        quota_state={
            "core": {"remaining": 4990},
            "graphql": {"remaining": 4999},
            "search": {"remaining": 29},
            "secondary": {"active": False},
        },
        heartbeat=heartbeat,
        terminal_reconciliation=terminal,
    )


def test_progress_schema_status_heartbeat_and_terminal_reconciliation(tmp_path: Path) -> None:
    stream = ProgressStream(tmp_path / "private" / "progress.jsonl")
    heartbeat = progress_event()
    stream.append(heartbeat)
    assert stream.latest() == heartbeat
    status = latest_status(stream.path)
    assert status == (
        "Engineering Journey github-ingestion: repository 2/3 synthetic/repository-2, page 4; "
        "API 11, durable 4, dedup 1, retries 2; retrying pull-request reviews; "
        "heartbeat, no change"
    )
    assert oct(stream.path.stat().st_mode & 0o777) == "0o600"

    terminal = progress_event(
        event="terminal",
        heartbeat=False,
        terminal={"received": 5, "durable": 4, "deduplicated": 1, "failed": 0},
    )
    stream.append(terminal)
    assert stream.latest() == terminal
    with pytest.raises(ProgressError, match="do not balance"):
        progress_event(
            event="terminal",
            heartbeat=False,
            terminal={"received": 6, "durable": 4, "deduplicated": 1, "failed": 0},
        )


def test_progress_recovers_previous_complete_line_after_partial_hard_kill(tmp_path: Path) -> None:
    stream = ProgressStream(tmp_path / "progress.jsonl")
    expected = progress_event()
    stream.append(expected)
    with stream.path.open("ab") as destination:
        destination.write(b'{"schema_version":"partial')
    assert stream.latest() == expected


def test_progress_does_not_accept_unterminated_json_as_a_complete_line(tmp_path: Path) -> None:
    stream = ProgressStream(tmp_path / "progress.jsonl")
    stream.path.write_text(progress_event().to_json(), encoding="utf-8")
    with pytest.raises(ProgressError, match="empty"):
        stream.latest()


def test_terminal_reconciliation_must_match_cumulative_write_counters() -> None:
    with pytest.raises(ProgressError, match="disagrees"):
        progress_event(
            event="terminal",
            heartbeat=False,
            terminal={"received": 4, "durable": 3, "deduplicated": 1, "failed": 0},
        )


def test_managed_orchestration_relays_unchanged_status_no_more_than_15_seconds_apart(
    tmp_path: Path,
) -> None:
    stream = ProgressStream(tmp_path / "progress.jsonl")
    stream.append(progress_event())

    class Clock:
        def __init__(self) -> None:
            self.now = 0.0
            self.sleeps: list[float] = []

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.sleeps.append(seconds)
            self.now += seconds

    class Process:
        pid = 1234

        def __init__(self) -> None:
            self.polls = 0

        def poll(self) -> int | None:
            self.polls += 1
            return None if self.polls <= 3 else 0

        def wait(self) -> int:
            return 0

    clock = Clock()
    process = Process()
    output = io.StringIO()
    result = run_managed(
        ["synthetic-ingestion"],
        progress_path=stream.path,
        output=output,
        popen=lambda command: cast(Any, process),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result == 0
    assert clock.sleeps == [15.0, 15.0, 15.0]
    relays = [line for line in output.getvalue().splitlines() if "heartbeat, no change" in line]
    assert len(relays) == 4  # three interval relays plus terminal process-exit relay
    with pytest.raises(ManagedProcessError, match="<=15s"):
        run_managed(["x"], progress_path=stream.path, output=io.StringIO(), relay_interval=15.1)


def test_run_events_are_deterministic_bounded_transition_records() -> None:
    definition = TYPE_DEFINITIONS[1]
    registered = RegisteredType(
        key=definition.key,
        name=definition.name,
        base_type=definition.base_type,
        type_id="MomentAnnotation/22222222-2222-4222-8222-222222222222",
        api_version=API_VERSION,
        fulcra_user_id="synthetic-fulcra-user",
    )
    plan = frozen_plan()
    checkpoint = Checkpoint(
        run_id=plan.run_id,
        plan_digest=plan.digest,
        snapshot_digest=plan.repository_snapshot_digest,
        invocation_id=invocation(),
        stage="github-ingestion",
        status=RunStatus.RUNNING,
        repository_total=3,
        current_repository_id=2,
        page_milestones={"reviews": 1},
        transition_count=7,
    )
    first = run_event_record(
        plan=plan,
        checkpoint=checkpoint,
        event="page-complete",
        recorded_at=NOW,
        tag_ids=["tag-v3", "tag-stage", "tag-state"],
        sources=["engineering-journey-v3:run"],
        registered_type=registered,
    )
    replay = run_event_record(
        plan=plan,
        checkpoint=checkpoint,
        event="page-complete",
        recorded_at=NOW,
        tag_ids=["tag-v3", "tag-stage", "tag-state"],
        sources=["engineering-journey-v3:run"],
        registered_type=registered,
    )
    assert first == replay
    note = json.loads(first["note"])
    assert note["transition_count"] == 7
    assert "raw" not in note


def test_private_run_files_upload_only_whitelisted_versioned_artifacts(tmp_path: Path) -> None:
    plan = frozen_plan()
    files = RunFiles(tmp_path / "run")
    files.initialize(plan, snapshot(), invocation())

    class Uploader:
        def __init__(self) -> None:
            self.calls: list[tuple[Path, str]] = []

        def upload_path(self, local: Path, remote: str, approval: Any) -> dict[str, Any]:
            assert approval.plan == plan
            self.calls.append((local, remote))
            return {"version": "synthetic-v1"}

    uploader = Uploader()
    result = files.upload(RunFiles.CHECKPOINT, uploader, approve_plan(plan, plan.digest))
    assert result == {"version": "synthetic-v1"}
    assert uploader.calls[0][1] == (
        f"/engineering-journey-runs/{plan.identity}/{plan.run_id}/checkpoint.json"
    )
    with pytest.raises(RunStateError, match="artifact contract"):
        files.path("credentials.json")


def test_interrupt_checkpoint_preserves_current_page_for_resume() -> None:
    checkpoint = Checkpoint(
        run_id=frozen_plan().run_id,
        plan_digest=frozen_plan().digest,
        snapshot_digest=frozen_plan().repository_snapshot_digest,
        invocation_id=invocation(),
        stage="github-ingestion",
        status=RunStatus.RUNNING,
        repository_total=3,
        current_repository_id=2,
        completed_repository_ids=(1,),
        page_milestones={"reviews": 4},
    )
    interrupted = stop_checkpoint(checkpoint, RunStatus.INTERRUPTED)
    assert interrupted.current_repository_id == 2
    assert interrupted.page_milestones == {"reviews": 4}
    assert interrupted.status == RunStatus.INTERRUPTED
