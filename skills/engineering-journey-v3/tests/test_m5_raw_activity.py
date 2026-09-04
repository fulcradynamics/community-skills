from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast
from urllib.error import URLError

import pytest

from engineering_journey_v3.fulcra_gateway import (
    FulcraGateway,
    RetryPolicy,
    SDKClient,
    approve_plan,
)
from engineering_journey_v3.fulcra_registry import API_VERSION, TYPE_DEFINITIONS, RegisteredType
from engineering_journey_v3.github_sources import (
    SourceFact,
    SourceKind,
    SourceSighting,
    ValidationSourceError,
)
from engineering_journey_v3.plan import Plan, build_plan
from engineering_journey_v3.raw_activity import (
    SOURCE_KIND_POLICIES,
    RawActivityWriter,
    RepositoryVisibility,
    decode_raw_activity_note,
    normalize_source_facts,
)

START = "2025-01-02T03:04:05Z"
END = "2025-02-02T03:04:05Z"
REPOSITORY = "private-owner/private-project"


class FakeSDK:
    fulcra_credentials = object()

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.write_calls = 0
        self.tag_names: list[str] = []

    def get_fulcra_userid(self) -> str:
        return "fulcra-user"

    def create_tags(self, tag_names: list[str]) -> list[dict[str, str]]:
        self.tag_names = list(tag_names)
        return [{"id": f"tag-{index}", "name": name} for index, name in enumerate(tag_names)]

    def validate_records(self, **kwargs: Any) -> list[tuple[int, str, Any]]:
        return []

    def record_data_type(self, **kwargs: Any) -> dict[str, Any]:
        self.write_calls += 1
        for record in kwargs["records"]:
            self.records[record["id"]] = record
        return {"upload_id": f"upload-{self.write_calls}"}

    def fulcra_v1_api_path(self, path: str, params: dict[str, str] | None = None) -> bytes:
        return json.dumps(list(self.records.values())).encode()


def raw_type() -> RegisteredType:
    definition = TYPE_DEFINITIONS[0]
    return RegisteredType(
        key=definition.key,
        name=definition.name,
        base_type=definition.base_type,
        type_id="MomentAnnotation/11111111-1111-4111-8111-111111111111",
        api_version=API_VERSION,
        fulcra_user_id="fulcra-user",
    )


def plan() -> Plan:
    return build_plan(
        identity="private-user",
        start_utc=START,
        end_utc=END,
        repository_snapshot_digest="sha256:synthetic-private-snapshot",
    )


EVIDENCE: dict[SourceKind, dict[str, Any]] = {
    SourceKind.COMMIT: {"sha": "abc", "message": "private commit message"},
    SourceKind.PULL_REQUEST: {
        "number": 1,
        "title": "private PR title",
        "body": "private PR body",
    },
    SourceKind.MERGE: {
        "number": 1,
        "merge_commit_sha": "def",
        "title": "private merged title",
    },
    SourceKind.REVIEW: {"pull_number": 1, "state": "APPROVED", "body": "private review"},
    SourceKind.ISSUE_COMMENT: {"issue_or_pull_number": 2, "body": "private issue comment"},
    SourceKind.PR_DISCUSSION_COMMENT: {
        "issue_or_pull_number": 3,
        "body": "private discussion",
    },
    SourceKind.PR_LINE_COMMENT: {
        "pull_request_url": f"https://github.com/{REPOSITORY}/pull/3",
        "path": "secret/module.py",
        "line": 12,
        "body": "private line comment",
    },
}


def fact(
    kind: SourceKind,
    *,
    stable_id: str | None = None,
    timestamp: str = START,
    url: str | None = None,
    sighting: SourceSighting | None = None,
) -> SourceFact:
    identifier = stable_id or kind.value
    return SourceFact(
        source_identity=f"github:{kind.value}:{identifier}",
        subtype=kind,
        identity="private-user",
        repository=REPOSITORY,
        recorded_at=timestamp,
        url=url or f"https://github.com/{REPOSITORY}/events/{identifier}",
        evidence=EVIDENCE[kind],
        attribution={"matched_identity": "private-user"},
        sightings=(sighting or SourceSighting("rest", f"repos/{REPOSITORY}/{kind.value}"),),
    )


def test_every_source_policy_preserves_actual_timestamp_and_private_evidence() -> None:
    facts = [
        fact(kind, timestamp=f"2025-01-{index + 2:02d}T03:04:05Z")
        for index, kind in enumerate(SourceKind)
    ]
    result = normalize_source_facts(facts, {REPOSITORY: RepositoryVisibility.PRIVATE})
    assert set(SOURCE_KIND_POLICIES) == set(SourceKind)
    assert [activity.recorded_at for activity in result.activities] == [
        item.recorded_at for item in facts
    ]
    for activity, source in zip(result.activities, facts, strict=True):
        assert activity.note_payload["evidence"] == source.evidence
        assert activity.note_payload["source_url"] == source.url
        assert activity.note_payload["repository"] == REPOSITORY
        assert activity.note_payload["visibility"] == "private"
        assert activity.sources[0] == source.url
        assert activity.recorded_at not in activity.fingerprint

    immutable_plan = plan()
    client = FakeSDK()
    counts = RawActivityWriter(
        FulcraGateway(cast(SDKClient, client)),
        raw_type(),
        approve_plan(immutable_plan, immutable_plan.digest),
        batch_size=2,
    ).write(result)
    assert (counts.batches, counts.written, counts.durable) == (4, 7, 7)
    assert [record["recorded_at"] for record in client.records.values()] == [
        source.recorded_at for source in facts
    ]
    assert all(
        decode_raw_activity_note(record["note"])["evidence"] == source.evidence
        for record, source in zip(client.records.values(), facts, strict=True)
    )


def test_cross_surface_duplicate_merges_once_and_conflicts_fail_closed() -> None:
    rest = fact(SourceKind.REVIEW, stable_id="global-review")
    graphql = fact(
        SourceKind.REVIEW,
        stable_id="global-review",
        url=None,
        sighting=SourceSighting("graphql", "node:global-review"),
    )
    result = normalize_source_facts([rest, graphql], {REPOSITORY: RepositoryVisibility.PRIVATE})
    assert result.duplicates == 1
    assert len(result.activities) == 1
    assert result.source_sightings == 2
    assert result.activities[0].note_payload["source_sightings"] == [
        {"api": "graphql", "locator": "node:global-review"},
        {"api": "rest", "locator": f"repos/{REPOSITORY}/pull_request_review"},
    ]

    changed = replace(
        rest,
        evidence={**EVIDENCE[SourceKind.REVIEW], "body": "conflicting body"},
    )
    with pytest.raises(ValidationSourceError, match="evidence fields disagree"):
        normalize_source_facts([rest, changed], {REPOSITORY: RepositoryVisibility.PRIVATE})


def test_same_commit_object_in_upstream_and_fork_is_two_repository_bound_facts() -> None:
    source_identity = "github:commit:shared-object-id"
    upstream = replace(
        fact(SourceKind.COMMIT),
        source_identity=source_identity,
        repository="synthetic-owner/upstream",
        url="https://github.com/synthetic-owner/upstream/commit/shared-object-id",
        sightings=(
            SourceSighting("rest", "repos/synthetic-owner/upstream/commits/shared-object-id"),
        ),
    )
    fork = replace(
        upstream,
        repository="synthetic-user/fork",
        url="https://github.com/synthetic-user/fork/commit/shared-object-id",
        sightings=(SourceSighting("graphql", "synthetic-user/fork:shared-object-id"),),
    )
    result = normalize_source_facts(
        [upstream, fork],
        {
            upstream.repository: RepositoryVisibility.PUBLIC,
            fork.repository: RepositoryVisibility.PRIVATE,
        },
    )

    assert result.duplicates == 0
    assert result.source_facts == result.source_sightings == 2
    assert len(result.activities) == 2
    assert {activity.repository for activity in result.activities} == {
        upstream.repository,
        fork.repository,
    }
    assert len({activity.fingerprint for activity in result.activities}) == 2


def test_private_evidence_tags_lineage_batches_replay_and_count_accounting() -> None:
    immutable_plan = plan()
    client = FakeSDK()
    writer = RawActivityWriter(
        FulcraGateway(cast(SDKClient, client)),
        raw_type(),
        approve_plan(immutable_plan, immutable_plan.digest),
        batch_size=2,
    )
    normalized = normalize_source_facts(
        [fact(SourceKind.COMMIT), fact(SourceKind.PULL_REQUEST)],
        {REPOSITORY: RepositoryVisibility.PRIVATE},
    )
    first = writer.write(normalized)
    assert (first.batches, first.attempted, first.written, first.durable) == (1, 2, 2, 2)
    assert first.already_present == first.reconciled == 0
    assert client.write_calls == 1
    assert "ej3" in client.tag_names
    assert "ej3-s-v1" in client.tag_names
    assert any(name.startswith("ej3-u-") for name in client.tag_names)
    assert any(name.startswith("ej3-r-") for name in client.tag_names)
    assert any(name.startswith("ej3-a-") for name in client.tag_names)
    assert "ej3-v-private" in client.tag_names

    notes = [decode_raw_activity_note(record["note"]) for record in client.records.values()]
    assert {note["repository"] for note in notes} == {REPOSITORY}
    assert {note["evidence"]["title"] for note in notes if "title" in note["evidence"]} == {
        "private PR title"
    }
    assert all(
        record["sources"][-1].startswith("com.fulcradynamics.annotation.")
        for record in client.records.values()
    )

    replay = writer.write(normalized)
    assert (replay.written, replay.already_present, replay.reconciled) == (0, 2, 0)
    assert replay.durable == 2
    assert client.write_calls == 1
    assert len(client.records) == 2


def test_committed_write_response_loss_reconciles_without_duplicate() -> None:
    class ResponseLossSDK(FakeSDK):
        def record_data_type(self, **kwargs: Any) -> dict[str, Any]:
            super().record_data_type(**kwargs)
            raise URLError("response lost after committed write")

    immutable_plan = plan()
    client = ResponseLossSDK()
    gateway = FulcraGateway(
        cast(SDKClient, client),
        retry_policy=RetryPolicy(attempts=3, base_delay=0, max_delay=0, jitter=0),
        sleep=lambda _delay: None,
    )
    normalized = normalize_source_facts(
        [fact(SourceKind.PR_LINE_COMMENT), fact(SourceKind.ISSUE_COMMENT)],
        {REPOSITORY: RepositoryVisibility.PRIVATE},
    )
    counts = RawActivityWriter(
        gateway, raw_type(), approve_plan(immutable_plan, immutable_plan.digest)
    ).write(normalized)
    assert (counts.written, counts.already_present, counts.reconciled) == (0, 0, 2)
    assert counts.durable == 2
    assert client.write_calls == 1
    assert len(client.records) == 2
