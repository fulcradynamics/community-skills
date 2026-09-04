"""Canonical v3 raw GitHub activity normalization and idempotent writing."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from engineering_journey_v3.fulcra_gateway import (
    ApprovedPlan,
    FulcraGateway,
    FulcraSchemaError,
    WriteDisposition,
    canonical_fingerprint,
    moment_record,
    v3_tags,
)
from engineering_journey_v3.fulcra_registry import RECORD_SCHEMA_VERSION, RegisteredType
from engineering_journey_v3.github_sources import (
    SOURCE_SEMANTICS_VERSION,
    FactAccumulator,
    SourceFact,
    SourceKind,
    ValidationSourceError,
)

RAW_ACTIVITY_SCHEMA_VERSION = "engineering-journey-v3-raw-github-activity/v1"


class RepositoryVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class SourceKindPolicy:
    """Fields and timestamp semantics required from one source subtype."""

    timestamp_semantic: str
    required_evidence: tuple[str, ...]


SOURCE_KIND_POLICIES: Mapping[SourceKind, SourceKindPolicy] = {
    SourceKind.COMMIT: SourceKindPolicy("commit.author.date", ("sha", "message")),
    SourceKind.PULL_REQUEST: SourceKindPolicy(
        "pull_request.created_at", ("number", "title", "body")
    ),
    SourceKind.MERGE: SourceKindPolicy(
        "pull_request.merged_at", ("number", "merge_commit_sha", "title")
    ),
    SourceKind.REVIEW: SourceKindPolicy(
        "pull_request_review.submitted_at", ("pull_number", "state", "body")
    ),
    SourceKind.ISSUE_COMMENT: SourceKindPolicy(
        "issue_comment.created_at", ("issue_or_pull_number", "body")
    ),
    SourceKind.PR_DISCUSSION_COMMENT: SourceKindPolicy(
        "pull_request_discussion_comment.created_at", ("issue_or_pull_number", "body")
    ),
    SourceKind.PR_LINE_COMMENT: SourceKindPolicy(
        "pull_request_line_comment.created_at",
        ("pull_request_url", "path", "line", "body"),
    ),
}


@dataclass(frozen=True, slots=True)
class NormalizedActivity:
    fingerprint: str
    recorded_at: str
    identity: str
    repository: str
    subtype: SourceKind
    visibility: RepositoryVisibility
    note_payload: Mapping[str, Any]
    tag_names: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    activities: tuple[NormalizedActivity, ...]
    source_facts: int
    source_sightings: int
    duplicates: int


@dataclass(frozen=True, slots=True)
class WriteCounts:
    source_facts: int
    source_sightings: int
    normalized: int
    duplicates: int
    batches: int
    attempted: int
    written: int
    already_present: int
    reconciled: int

    @property
    def durable(self) -> int:
        return self.written + self.already_present + self.reconciled


def _json_copy(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    """Reject non-JSON evidence while preserving private text losslessly."""
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise ValidationSourceError(f"{label} must contain JSON-compatible evidence") from error
    if not isinstance(decoded, dict):
        raise ValidationSourceError(f"{label} must be an object")
    return decoded


def normalize_source_fact(fact: SourceFact, visibility: RepositoryVisibility) -> NormalizedActivity:
    """Map a source fact to a lossless, deterministic private record candidate."""
    policy = SOURCE_KIND_POLICIES[fact.subtype]
    missing = [field for field in policy.required_evidence if field not in fact.evidence]
    if missing:
        raise ValidationSourceError(
            f"{fact.subtype.value} evidence is missing required fields: {', '.join(missing)}"
        )
    evidence = _json_copy(fact.evidence, label="source evidence")
    attribution = _json_copy(fact.attribution, label="source attribution")
    immutable = {
        "repository": fact.repository,
        "source_identity": fact.source_identity,
        "source_semantics_version": fact.semantics_version,
        "subtype": fact.subtype.value,
    }
    fingerprint = canonical_fingerprint(fact.subtype.value, fact.identity, immutable)
    sightings = [{"api": sighting.api, "locator": sighting.locator} for sighting in fact.sightings]
    note = {
        "activity_schema_version": RAW_ACTIVITY_SCHEMA_VERSION,
        "activity_subtype": fact.subtype.value,
        "actual_timestamp_semantic": policy.timestamp_semantic,
        "attribution": attribution,
        "evidence": evidence,
        "identity": fact.identity,
        "repository": fact.repository,
        "source_identity": fact.source_identity,
        "source_semantics_version": fact.semantics_version,
        "source_url": fact.url,
        "source_sightings": sightings,
        "visibility": visibility.value,
    }
    tag_names = tuple(
        v3_tags(
            f"github-user:{fact.identity}",
            f"repository:{fact.repository}",
            f"activity-subtype:{fact.subtype.value}",
            f"visibility:{visibility.value}",
        )
    )
    repository_url = f"https://github.com/{fact.repository}"
    lineage = [fact.url or repository_url]
    lineage.extend(f"github-api:{item.api}:{item.locator}" for item in fact.sightings)
    lineage.extend((fact.source_identity, fact.semantics_version))
    return NormalizedActivity(
        fingerprint=fingerprint,
        recorded_at=fact.recorded_at,
        identity=fact.identity,
        repository=fact.repository,
        subtype=fact.subtype,
        visibility=visibility,
        note_payload=note,
        tag_names=tag_names,
        sources=tuple(dict.fromkeys(lineage)),
    )


def normalize_source_facts(
    facts: Sequence[SourceFact],
    visibility_by_repository: Mapping[str, RepositoryVisibility],
) -> NormalizationResult:
    """Merge cross-surface sightings and normalize a deterministic chronological set."""
    accumulator = FactAccumulator()
    for fact in facts:
        if fact.semantics_version != SOURCE_SEMANTICS_VERSION:
            raise ValidationSourceError("source fact uses an unsupported semantics version")
        accumulator.add(fact)
    merged = accumulator.facts()
    activities: list[NormalizedActivity] = []
    fingerprints: set[str] = set()
    for fact in merged:
        visibility = visibility_by_repository.get(fact.repository)
        if visibility is None:
            raise ValidationSourceError(f"repository visibility is missing for {fact.repository}")
        activity = normalize_source_fact(fact, visibility)
        if activity.fingerprint in fingerprints:
            raise ValidationSourceError("distinct GitHub identities produced one fingerprint")
        fingerprints.add(activity.fingerprint)
        activities.append(activity)
    return NormalizationResult(
        activities=tuple(activities),
        source_facts=len(facts),
        source_sightings=sum(len(fact.sightings) for fact in facts),
        duplicates=len(facts) - len(merged),
    )


class RawActivityWriter:
    """Resolve reusable dimensions and idempotently write bounded activity batches."""

    def __init__(
        self,
        gateway: FulcraGateway,
        registered_type: RegisteredType,
        approval: ApprovedPlan,
        *,
        batch_size: int = 100,
    ) -> None:
        if registered_type.key != "raw_activity":
            raise FulcraSchemaError("raw activity writer requires the isolated v3 raw type")
        if batch_size < 1:
            raise ValueError("batch size must be positive")
        self.gateway = gateway
        self.registered_type = registered_type
        self.approval = approval
        self.batch_size = batch_size

    def write(self, normalized: NormalizationResult) -> WriteCounts:
        for activity in normalized.activities:
            if activity.identity != self.approval.plan.identity:
                raise FulcraSchemaError("raw activity identity does not match the approved plan")
            if not (
                self.approval.plan.start_utc <= activity.recorded_at < self.approval.plan.end_utc
            ):
                raise FulcraSchemaError("raw activity timestamp is outside the approved UTC window")
        all_names = list(
            dict.fromkeys(name for activity in normalized.activities for name in activity.tag_names)
        )
        tag_ids = self.gateway.resolve_tags(all_names, self.approval) if all_names else []
        tags = dict(zip(all_names, tag_ids, strict=True))
        written = already_present = reconciled = batches = 0
        for offset in range(0, len(normalized.activities), self.batch_size):
            batches += 1
            batch = normalized.activities[offset : offset + self.batch_size]
            records = [
                moment_record(
                    fingerprint=activity.fingerprint,
                    recorded_at=activity.recorded_at,
                    note_payload=activity.note_payload,
                    tag_ids=[tags[name] for name in activity.tag_names],
                    sources=list(activity.sources),
                )
                for activity in batch
            ]
            outcomes = self.gateway.record_batch_once_classified(
                self.registered_type, records, self.approval
            )
            for outcome in outcomes:
                if outcome.disposition == WriteDisposition.WRITTEN:
                    written += 1
                elif outcome.disposition == WriteDisposition.ALREADY_PRESENT:
                    already_present += 1
                else:
                    reconciled += 1
        counts = WriteCounts(
            source_facts=normalized.source_facts,
            source_sightings=normalized.source_sightings,
            normalized=len(normalized.activities),
            duplicates=normalized.duplicates,
            batches=batches,
            attempted=len(normalized.activities),
            written=written,
            already_present=already_present,
            reconciled=reconciled,
        )
        if counts.durable != counts.normalized:
            raise FulcraSchemaError("raw activity write accounting did not reconcile")
        return counts


def decode_raw_activity_note(note: str) -> Mapping[str, Any]:
    """Strict private-evidence reader used by later handoff/publication milestones."""
    try:
        payload = json.loads(note)
    except json.JSONDecodeError as error:
        raise FulcraSchemaError("raw activity note is malformed JSON") from error
    if not isinstance(payload, dict):
        raise FulcraSchemaError("raw activity note is not an object")
    if payload.get("schema_version") != RECORD_SCHEMA_VERSION:
        raise FulcraSchemaError("raw activity note has an unsupported record schema")
    if payload.get("activity_schema_version") != RAW_ACTIVITY_SCHEMA_VERSION:
        raise FulcraSchemaError("raw activity note has an unsupported activity schema")
    return payload
