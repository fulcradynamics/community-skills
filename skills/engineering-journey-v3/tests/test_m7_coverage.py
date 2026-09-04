from __future__ import annotations

import json
import uuid
from dataclasses import replace
from typing import Any

import pytest

from engineering_journey_v3.coverage import (
    CompletedCoverage,
    CoverageError,
    CoverageManager,
    Interval,
    decode_coverage_record,
    plan_extension,
)
from engineering_journey_v3.discovery import Provenance, Repository, RepositorySnapshot
from engineering_journey_v3.fulcra_gateway import (
    RecordWriteOutcome,
    WriteDisposition,
    approve_plan,
    coverage_record,
)
from engineering_journey_v3.fulcra_registry import API_VERSION, TYPE_DEFINITIONS, RegisteredType
from engineering_journey_v3.plan import SOURCE_SEMANTICS_VERSION, Mode, Plan, build_plan
from engineering_journey_v3.run_state import Checkpoint, RunStatus

DAY = "2026-01-{:02d}T00:00:00Z"


def interval(start: int, end: int) -> Interval:
    return Interval(DAY.format(start), DAY.format(end))


def completed(
    start: int,
    end: int,
    *,
    identity: str = "synthetic-user",
    semantics: str = SOURCE_SEMANTICS_VERSION,
) -> CompletedCoverage:
    return CompletedCoverage(
        record_id=f"coverage-{start}-{end}",
        run_id=str(uuid.uuid4()),
        identity=identity,
        interval=interval(start, end),
        snapshot_digest="sha256:synthetic",
        source_semantics_version=semantics,
        repository_count=1,
    )


def make_plan(start: int, end: int, *, mode: Mode = "write") -> Plan:
    return build_plan(
        identity="synthetic-user",
        start_utc=DAY.format(start),
        end_utc=DAY.format(end),
        mode=mode,
        repository_snapshot_digest="sha256:synthetic",
    )


def bounds(value: tuple[Interval, ...]) -> list[tuple[int, int]]:
    return [(int(item.start_utc[8:10]), int(item.end_utc[8:10])) for item in value]


@pytest.mark.parametrize(
    ("requested_bounds", "stored", "expected"),
    [
        ((10, 20), [(1, 25)], []),  # contained
        ((10, 20), [(5, 15)], [(15, 20)]),  # overlap on left
        ((10, 20), [(15, 25)], [(10, 15)]),  # overlap on right
        ((10, 20), [(12, 18)], [(10, 12), (18, 20)]),  # stored is contained
        ((10, 20), [(1, 5)], [(10, 20)]),  # disjoint
        ((1, 20), [(10, 20)], [(1, 10)]),  # backward extension
        ((1, 20), [(1, 10)], [(10, 20)]),  # forward extension
        ((1, 20), [(1, 5), (5, 8), (7, 15), (18, 25)], [(15, 18)]),
    ],
)
def test_extension_fetches_exactly_uncovered_half_open_intervals(
    requested_bounds: tuple[int, int],
    stored: list[tuple[int, int]],
    expected: list[tuple[int, int]],
) -> None:
    plan = make_plan(*requested_bounds)
    result = plan_extension(plan, [completed(start, end) for start, end in stored])
    assert bounds(result.fetch_intervals) == expected
    assert result.requires_github is bool(expected)
    assert result.raw_complete is not bool(expected)


def test_query_overlap_is_not_mistaken_for_containment() -> None:
    """Regression: an API overlap query returning a short record proves only its bounds."""
    requested = make_plan(10, 20)
    returned_by_overlap_query = completed(12, 14)
    result = plan_extension(requested, [returned_by_overlap_query])
    assert bounds(result.fetch_intervals) == [(10, 12), (14, 20)]


def test_wrong_identity_or_semantics_never_proves_coverage() -> None:
    plan = make_plan(10, 20)
    result = plan_extension(
        plan,
        [
            completed(1, 25, identity="someone-else"),
            completed(1, 25, semantics="older-source-semantics/v0"),
        ],
    )
    assert bounds(result.fetch_intervals) == [(10, 20)]


def test_covered_and_fetch_segments_partition_request_without_gaps_or_duplicates() -> None:
    plan = make_plan(1, 10)
    coverages = [completed(1, 3), completed(2, 5), completed(7, 8), completed(8, 10)]
    result = plan_extension(plan, coverages)
    assert bounds(result.fetch_intervals) == [(5, 7)]

    occurrences: dict[int, int] = {day: 0 for day in range(1, 10)}
    for coverage in coverages:
        start_day = max(1, int(coverage.interval.start_utc[8:10]))
        end_day = min(10, int(coverage.interval.end_utc[8:10]))
        for day in range(start_day, end_day):
            occurrences[day] = 1
    for fetch_interval in result.fetch_intervals:
        for day in range(int(fetch_interval.start_utc[8:10]), int(fetch_interval.end_utc[8:10])):
            occurrences[day] += 1
    assert occurrences == {day: 1 for day in range(1, 10)}


def test_raw_complete_rewrite_requires_no_github_work() -> None:
    plan = make_plan(10, 20, mode="rewrite")
    result = plan_extension(plan, [completed(1, 25)])
    github_calls = 0
    if result.requires_github:
        github_calls += 1
    assert result.raw_complete
    assert github_calls == 0


def coverage_type() -> RegisteredType:
    definition = TYPE_DEFINITIONS[2]
    return RegisteredType(
        key="coverage",
        name=definition.name,
        base_type="DurationAnnotation",
        type_id="DurationAnnotation/33333333-3333-4333-8333-333333333333",
        api_version=API_VERSION,
        fulcra_user_id="synthetic-owner",
    )


def snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        identity="synthetic-user",
        start_utc=DAY.format(1),
        end_utc=DAY.format(10),
        repositories=(
            Repository(
                database_id=7,
                node_id="R_synthetic",
                name_with_owner="synthetic/zero-activity",
                private=True,
                archived=False,
                url="https://github.com/synthetic/zero-activity",
                provenance=(Provenance("direct-access", 1, "synthetic-page"),),
            ),
        ),
    )


def bound_plan(value: RepositorySnapshot) -> Plan:
    return build_plan(
        identity=value.identity,
        start_utc=value.start_utc,
        end_utc=value.end_utc,
        repository_snapshot_digest=value.digest,
    )


def checkpoint(plan: Plan, value: RepositorySnapshot, status: RunStatus) -> Checkpoint:
    return Checkpoint(
        run_id=plan.run_id,
        plan_digest=plan.digest,
        snapshot_digest=value.digest,
        invocation_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        stage="coverage",
        status=status,
        repository_total=1,
        completed_repository_ids=(7,),
    )


class FakeGateway:
    def __init__(self) -> None:
        self.tag_calls: list[list[str]] = []
        self.records: list[dict[str, Any]] = []
        self.query_payload: list[dict[str, Any]] = []
        self.query_parameters: dict[str, str] | None = None

    def resolve_tags(self, names: list[str], approval: object) -> list[str]:
        self.tag_calls.append(names)
        return [f"tag-{index}" for index in range(len(names))]

    def record_once_classified(
        self, registered_type: RegisteredType, record: dict[str, Any], approval: object
    ) -> RecordWriteOutcome:
        self.records.append(record)
        return RecordWriteOutcome(WriteDisposition.WRITTEN, record["id"], {"ok": True})

    def query_records(
        self, registered_type: RegisteredType, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        self.query_parameters = params
        return self.query_payload


def manager(plan: Plan, gateway: FakeGateway) -> CoverageManager:
    approval = approve_plan(plan, plan.digest)
    return CoverageManager(gateway, coverage_type(), approval)  # type: ignore[arg-type]


def test_only_completed_reconciled_run_writes_one_full_snapshot_duration() -> None:
    value = snapshot()
    plan = bound_plan(value)
    gateway = FakeGateway()
    outcome = manager(plan, gateway).write_completed(
        checkpoint(plan, value, RunStatus.COMPLETED), value
    )

    assert outcome.disposition == WriteDisposition.WRITTEN
    assert len(gateway.records) == 1
    decoded = decode_coverage_record(gateway.records[0])
    assert decoded.interval == Interval(plan.start_utc, plan.end_utc)
    assert decoded.snapshot_digest == value.digest
    assert decoded.repository_count == 1  # repository is retained despite zero activity
    assert decoded.source_semantics_version == SOURCE_SEMANTICS_VERSION


@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.INTERRUPTED, RunStatus.FAILED])
def test_incomplete_or_failed_run_never_writes_completed_coverage(status: RunStatus) -> None:
    value = snapshot()
    plan = bound_plan(value)
    gateway = FakeGateway()
    with pytest.raises(CoverageError, match="completed run checkpoint"):
        manager(plan, gateway).write_completed(checkpoint(plan, value, status), value)
    assert gateway.tag_calls == []
    assert gateway.records == []


def test_completed_checkpoint_must_match_every_snapshot_repository() -> None:
    value = snapshot()
    plan = bound_plan(value)
    gateway = FakeGateway()
    wrong = replace(checkpoint(plan, value, RunStatus.COMPLETED), completed_repository_ids=(8,))
    with pytest.raises(CoverageError, match="does not reconcile"):
        manager(plan, gateway).write_completed(wrong, value)
    assert gateway.records == []


def test_manager_uses_actual_returned_duration_not_overlap_query_bounds() -> None:
    requested = make_plan(10, 20)
    stored_plan = make_plan(12, 14)
    gateway = FakeGateway()
    gateway.query_payload = [
        coverage_record(
            plan=stored_plan,
            repository_count=0,
            tag_ids=["tag-v3"],
            sources=["github.com", "snapshot:synthetic"],
        )
    ]
    result = manager(requested, gateway).extension_plan()
    assert gateway.query_parameters == {
        "start_time": DAY.format(10),
        "end_time": DAY.format(20),
    }
    assert bounds(result.fetch_intervals) == [(10, 12), (14, 20)]


def test_decode_rejects_query_record_whose_duration_disagrees_with_note() -> None:
    plan = make_plan(10, 20)
    record = coverage_record(
        plan=plan,
        repository_count=0,
        tag_ids=["tag-v3"],
        sources=["github.com"],
    )
    record["recorded_at"] = {"start_time": DAY.format(1), "end_time": DAY.format(25)}
    with pytest.raises(CoverageError, match="disagrees"):
        decode_coverage_record(record)
    assert json.loads(record["note"])["window_start"] == DAY.format(10)


def test_decode_accepts_service_normalized_utc_duration_bounds() -> None:
    plan = make_plan(10, 20)
    record = coverage_record(
        plan=plan,
        repository_count=1,
        tag_ids=["tag-v3"],
        sources=["github.com"],
    )
    bounds = record["recorded_at"]
    assert isinstance(bounds, dict)
    record["recorded_at"] = {key: value.replace("Z", "+00:00") for key, value in bounds.items()}

    decoded = decode_coverage_record(record)

    assert decoded.interval == Interval(plan.start_utc, plan.end_utc)
