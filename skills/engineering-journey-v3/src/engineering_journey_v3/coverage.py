"""Completed whole-window coverage and extension interval algebra."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from engineering_journey_v3.discovery import RepositorySnapshot
from engineering_journey_v3.fulcra_gateway import (
    ApprovedPlan,
    FulcraGateway,
    FulcraSchemaError,
    RecordWriteOutcome,
    coverage_record,
    extract_fingerprint,
    v3_tags,
)
from engineering_journey_v3.fulcra_registry import RECORD_SCHEMA_VERSION, RegisteredType
from engineering_journey_v3.plan import Plan, PlanValidationError, normalize_utc
from engineering_journey_v3.run_state import Checkpoint, RunStatus


class CoverageError(ValueError):
    """A coverage record or interval violates supported semantics."""


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _service_utc(value: Any) -> str:
    """Canonicalize an actual service UTC timestamp without accepting another zone."""
    if not isinstance(value, str):
        raise CoverageError("coverage stored window bounds are not timestamps")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CoverageError("coverage stored window bounds are malformed") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise CoverageError("coverage stored window bounds are not UTC")
    timespec = "microseconds" if parsed.microsecond else "seconds"
    return parsed.astimezone(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")


@dataclass(frozen=True, slots=True, order=True)
class Interval:
    """A canonical half-open UTC interval ``[start, end)``."""

    start_utc: str
    end_utc: str

    def __post_init__(self) -> None:
        try:
            start = normalize_utc(self.start_utc)
            end = normalize_utc(self.end_utc)
        except PlanValidationError as error:
            raise CoverageError("coverage interval has invalid UTC bounds") from error
        if (start, end) != (self.start_utc, self.end_utc) or _instant(start) >= _instant(end):
            raise CoverageError("coverage interval must have canonical increasing UTC bounds")


@dataclass(frozen=True, slots=True)
class CompletedCoverage:
    """Validated durable proof for one completed immutable run and snapshot."""

    record_id: str
    run_id: str
    identity: str
    interval: Interval
    snapshot_digest: str
    source_semantics_version: str
    repository_count: int


@dataclass(frozen=True, slots=True)
class ExtensionPlan:
    """Minimal source work for a request under one supported semantics version."""

    requested: Interval
    fetch_intervals: tuple[Interval, ...]

    @property
    def raw_complete(self) -> bool:
        return not self.fetch_intervals

    @property
    def requires_github(self) -> bool:
        return bool(self.fetch_intervals)


def _merge(intervals: Iterable[Interval]) -> tuple[Interval, ...]:
    ordered = sorted(intervals, key=lambda item: _instant(item.start_utc))
    merged: list[Interval] = []
    for current in ordered:
        if not merged or _instant(current.start_utc) > _instant(merged[-1].end_utc):
            merged.append(current)
            continue
        if _instant(current.end_utc) > _instant(merged[-1].end_utc):
            merged[-1] = Interval(merged[-1].start_utc, current.end_utc)
    return tuple(merged)


def uncovered_intervals(
    requested: Interval,
    completed: Iterable[CompletedCoverage],
    *,
    identity: str,
    source_semantics_version: str,
) -> tuple[Interval, ...]:
    """Subtract actual matching stored bounds, never query bounds, from a request."""
    relevant: list[Interval] = []
    request_start = _instant(requested.start_utc)
    request_end = _instant(requested.end_utc)
    for coverage in completed:
        if (
            coverage.identity != identity
            or coverage.source_semantics_version != source_semantics_version
        ):
            continue
        start = max(request_start, _instant(coverage.interval.start_utc))
        end = min(request_end, _instant(coverage.interval.end_utc))
        if start < end:
            relevant.append(
                Interval(
                    start.isoformat().replace("+00:00", "Z"),
                    end.isoformat().replace("+00:00", "Z"),
                )
            )
    cursor = requested.start_utc
    result: list[Interval] = []
    for covered in _merge(relevant):
        if _instant(cursor) < _instant(covered.start_utc):
            result.append(Interval(cursor, covered.start_utc))
        if _instant(covered.end_utc) > _instant(cursor):
            cursor = covered.end_utc
    if _instant(cursor) < request_end:
        result.append(Interval(cursor, requested.end_utc))
    return tuple(result)


def plan_extension(plan: Plan, completed: Iterable[CompletedCoverage]) -> ExtensionPlan:
    requested = Interval(plan.start_utc, plan.end_utc)
    return ExtensionPlan(
        requested=requested,
        fetch_intervals=uncovered_intervals(
            requested,
            completed,
            identity=plan.identity,
            source_semantics_version=plan.source_semantics_version,
        ),
    )


def decode_coverage_record(record: Mapping[str, Any]) -> CompletedCoverage:
    """Decode actual durable bounds and fail closed on malformed coverage."""
    record_id = record.get("id")
    note = record.get("note")
    bounds = record.get("recorded_at")
    if not isinstance(record_id, str) or not record_id or not isinstance(note, str):
        raise CoverageError("coverage record is missing its ID or note")
    try:
        payload = json.loads(note)
    except json.JSONDecodeError as error:
        raise CoverageError("coverage record note is malformed JSON") from error
    expected = {
        "schema_version",
        "fingerprint",
        "run_id",
        "identity",
        "window_start",
        "window_end",
        "snapshot_digest",
        "source_semantics_version",
        "repository_count",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise CoverageError("coverage note fields do not match the whole-window schema")
    string_fields = expected - {"repository_count"}
    if not all(isinstance(payload[field], str) for field in string_fields):
        raise CoverageError("coverage note string fields are invalid")
    count = payload["repository_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise CoverageError("coverage repository count is invalid")
    if payload["schema_version"] != RECORD_SCHEMA_VERSION or not payload[
        "snapshot_digest"
    ].startswith("sha256:"):
        raise CoverageError("coverage schema or snapshot digest is unsupported")
    try:
        fingerprint = extract_fingerprint(record)
    except FulcraSchemaError as error:
        raise CoverageError(str(error)) from error
    if payload["fingerprint"] != fingerprint:
        raise CoverageError("coverage fingerprint does not match its record")
    if not isinstance(bounds, Mapping) or set(bounds) != {"start_time", "end_time"}:
        raise CoverageError("coverage duration disagrees with its stored window bounds")
    actual = {
        "start_time": _service_utc(bounds["start_time"]),
        "end_time": _service_utc(bounds["end_time"]),
    }
    expected_bounds = {
        "start_time": payload["window_start"],
        "end_time": payload["window_end"],
    }
    if actual != expected_bounds:
        raise CoverageError("coverage duration disagrees with its stored window bounds")
    interval = Interval(payload["window_start"], payload["window_end"])
    return CompletedCoverage(
        record_id=record_id,
        run_id=payload["run_id"],
        identity=payload["identity"],
        interval=interval,
        snapshot_digest=payload["snapshot_digest"],
        source_semantics_version=payload["source_semantics_version"],
        repository_count=count,
    )


class CoverageManager:
    """Read completion proofs and write exactly one proof after terminal reconciliation."""

    def __init__(
        self,
        gateway: FulcraGateway,
        registered_type: RegisteredType,
        approval: ApprovedPlan,
    ) -> None:
        if registered_type.key != "coverage":
            raise FulcraSchemaError("coverage manager requires the isolated v3 coverage type")
        self.gateway = gateway
        self.registered_type = registered_type
        self.approval = approval

    def extension_plan(self) -> ExtensionPlan:
        records = self.gateway.query_records(
            self.registered_type,
            {
                "start_time": self.approval.plan.start_utc,
                "end_time": self.approval.plan.end_utc,
            },
        )
        return plan_extension(
            self.approval.plan, (decode_coverage_record(record) for record in records)
        )

    def write_completed(
        self, checkpoint: Checkpoint, snapshot: RepositorySnapshot
    ) -> RecordWriteOutcome:
        """Write no coverage unless the exact run and every snapshot repository completed."""
        plan = self.approval.plan
        snapshot_ids = tuple(repository.database_id for repository in snapshot.repositories)
        if checkpoint.status != RunStatus.COMPLETED:
            raise CoverageError("completed coverage requires a completed run checkpoint")
        if (
            checkpoint.run_id != plan.run_id
            or checkpoint.plan_digest != plan.digest
            or checkpoint.snapshot_digest != plan.repository_snapshot_digest
            or snapshot.digest != plan.repository_snapshot_digest
            or (snapshot.identity, snapshot.start_utc, snapshot.end_utc)
            != (plan.identity, plan.start_utc, plan.end_utc)
            or checkpoint.repository_total != len(snapshot.repositories)
            or checkpoint.completed_repository_ids != snapshot_ids
        ):
            raise CoverageError(
                "completed checkpoint does not reconcile the immutable run snapshot"
            )
        names = v3_tags(
            f"github-user:{plan.identity}",
            "state:completed",
            f"semantics:{plan.source_semantics_version}",
        )
        tag_ids = self.gateway.resolve_tags(names, self.approval)
        record = coverage_record(
            plan=plan,
            repository_count=len(snapshot.repositories),
            tag_ids=tag_ids,
            sources=[
                "github.com",
                f"repository-snapshot:{snapshot.digest}",
                plan.source_semantics_version,
            ],
        )
        return self.gateway.record_once_classified(self.registered_type, record, self.approval)
