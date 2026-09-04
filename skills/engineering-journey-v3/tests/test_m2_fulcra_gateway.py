from __future__ import annotations

import errno
import io
import json
import socket
from email.message import Message
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError

import pytest

from engineering_journey_v3.cli import main
from engineering_journey_v3.fulcra_gateway import (
    FulcraApprovalError,
    FulcraAuthError,
    FulcraGateway,
    FulcraSchemaError,
    FulcraTransientError,
    PrivateFileGateway,
    RetryPolicy,
    approve_mutation,
    approve_plan,
    canonical_fingerprint,
    classify_error,
    coverage_record,
    deterministic_record_id,
    duration_record,
    moment_record,
    mutation_digest,
    ordered_sources,
    v3_tags,
)
from engineering_journey_v3.fulcra_registry import (
    API_VERSION,
    RECORD_SCHEMA_VERSION,
    TYPE_DEFINITIONS,
    RegisteredType,
    RegistryError,
    TypeRegistry,
)
from engineering_journey_v3.plan import Plan, build_plan

START = "2025-01-02T03:04:05Z"
END = "2026-01-02T03:04:05Z"
UUIDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
)


class StatusError(Exception):
    def __init__(self, status: int) -> None:
        self.status = status


class Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self) -> bytes:
        return self.content


class FakeSDK:
    fulcra_credentials = object()

    def __init__(self) -> None:
        self.catalog_calls: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.tag_calls: list[list[str]] = []
        self.write_calls = 0
        self.last_validate_data_type: str | None = None
        self.last_write_data_type: str | None = None
        self.records: dict[str, dict[str, Any]] = {}
        self.uploads: list[tuple[str, bytes, str]] = []
        self.query_payload: Any = []
        self.agg_payload: Any = {"buckets": []}
        self.query_calls: list[tuple[str, dict[str, str] | None]] = []

    def get_fulcra_userid(self) -> str:
        return "fulcra-user-1"

    def v1_catalog(
        self,
        data_type: str | None = None,
        category: str | None = None,
        fulcra_userid: str | None = None,
    ) -> list[dict[str, Any]]:
        self.catalog_calls.append(
            {"data_type": data_type, "category": category, "fulcra_userid": fulcra_userid}
        )
        return list(self.created)

    def create_annotation(self, **kwargs: Any) -> dict[str, Any]:
        index = len(self.created)
        base = (
            "DurationAnnotation" if kwargs["annotation_type"] == "duration" else "MomentAnnotation"
        )
        item = {
            "id": f"{base}/{UUIDS[index]}",
            "name": kwargs["name"],
            "api_version": API_VERSION,
            "fulcra_userid": self.get_fulcra_userid(),
        }
        self.created.append(item)
        return item

    def create_tags(self, tag_names: list[str]) -> list[dict[str, str]]:
        self.tag_calls.append(tag_names)
        return [{"id": f"tag-{index}", "name": name} for index, name in enumerate(tag_names)]

    def validate_records(self, **kwargs: Any) -> list[tuple[int, str, Any]]:
        self.last_validate_data_type = kwargs["data_type"]
        return []

    def record_data_type(self, **kwargs: Any) -> dict[str, Any]:
        self.write_calls += 1
        self.last_write_data_type = kwargs["data_type"]
        record = kwargs["records"][0]
        self.records[record["id"]] = record
        self.query_payload = list(self.records.values())
        return {"upload_id": "upload-1"}

    def fulcra_v1_api_path(self, path: str, params: dict[str, str] | None = None) -> bytes:
        self.query_calls.append((path, params))
        return json.dumps(self.query_payload).encode()

    def fulcra_api(self, url_path: str, **kwargs: Any) -> bytes:
        assert url_path.endswith("/agg/day")
        return json.dumps(self.agg_payload).encode()

    def upload_file(
        self, data: io.BufferedReader, file_type: str, file_size: int, filepath: str
    ) -> dict[str, Any]:
        content = data.read()
        assert file_size == len(content)
        self.uploads.append((filepath, content, file_type))
        return {
            "file": {
                "id": "file-1",
                "path": str(Path(filepath).parent),
                "name": Path(filepath).name,
            }
        }

    def resolve_filepath(self, filepath: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "file-1", "path": str(Path(filepath).parent), "name": Path(filepath).name}]

    def download_file(self, file_id: str, **kwargs: Any) -> Response:
        return Response(b"private-content")


def plan() -> Plan:
    return build_plan(
        identity="account-a",
        start_utc=START,
        end_utc=END,
        repository_snapshot_digest="sha256:synthetic-snapshot",
    )


def raw_type() -> RegisteredType:
    definition = TYPE_DEFINITIONS[0]
    return RegisteredType(
        key=definition.key,
        name=definition.name,
        base_type=definition.base_type,
        type_id=f"MomentAnnotation/{UUIDS[0]}",
        api_version=API_VERSION,
        fulcra_user_id="fulcra-user-1",
    )


def test_registry_is_strictly_new_custom_ids_and_exact_v3_names() -> None:
    approved = plan()
    client = FakeSDK()
    gateway = FulcraGateway(client)
    output = "/private/registry.json"
    approval_digest = mutation_digest(approved, action="create-isolated-v3-types", outputs=[output])
    registry = gateway.create_registry(
        approve_mutation(
            approved,
            action="create-isolated-v3-types",
            outputs=[output],
            supplied_digest=approval_digest,
        )
    )
    reloaded = TypeRegistry.from_json(registry.to_json())
    assert reloaded == registry
    gateway.verify_registry(reloaded)
    assert {entry.type_id for entry in registry.types} == {
        f"MomentAnnotation/{UUIDS[0]}",
        f"MomentAnnotation/{UUIDS[1]}",
        f"DurationAnnotation/{UUIDS[2]}",
    }
    assert all("v3" in entry.name for entry in registry.types)

    payload = registry.as_dict()
    payload["types"][0]["name"] = "Engineering Journey legacy GitHub Activity"
    with pytest.raises(RegistryError, match="exact v3"):
        TypeRegistry.from_json(json.dumps(payload))

    payload = registry.as_dict()
    payload["types"][0]["type_id"] = "MomentAnnotation"
    with pytest.raises(RegistryError, match="custom-type ID"):
        TypeRegistry.from_json(json.dumps(payload))


def test_discovery_is_read_only_and_queries_only_exact_v3_names() -> None:
    client = FakeSDK()
    gateway = FulcraGateway(client)
    output = io.StringIO()
    assert main(["fulcra-types", "discover"], fulcra_gateway=gateway, output=output) == 0
    assert "DRY-RUN" in output.getvalue()
    assert client.created == []
    assert client.write_calls == 0
    assert client.catalog_calls == [
        {"data_type": None, "category": None, "fulcra_userid": "fulcra-user-1"}
    ]


def test_discovery_filters_unfiltered_v1_owner_catalog_by_exact_contract() -> None:
    client = FakeSDK()
    client.created = [
        {
            "id": f"MomentAnnotation/{UUIDS[0]}",
            "name": TYPE_DEFINITIONS[0].name,
            "api_version": API_VERSION,
            "fulcra_userid": "fulcra-user-1",
        },
        {
            "id": f"MomentAnnotation/{UUIDS[1]}",
            "name": TYPE_DEFINITIONS[1].name,
            "api_version": API_VERSION,
            "fulcra_userid": "another-owner",
        },
        {
            "id": f"MomentAnnotation/{UUIDS[2]}",
            "name": "Engineering Journey legacy GitHub Activity",
            "api_version": API_VERSION,
            "fulcra_userid": "fulcra-user-1",
        },
        {
            "id": f"DurationAnnotation/{UUIDS[2]}",
            "name": TYPE_DEFINITIONS[2].name,
            "api_version": "v1",
            "fulcra_userid": "fulcra-user-1",
        },
    ]
    assert FulcraGateway(client).catalog() == [client.created[0]]
    assert client.catalog_calls == [
        {"data_type": None, "category": None, "fulcra_userid": "fulcra-user-1"}
    ]


def test_cli_creation_requires_bound_approval_and_writes_private_registry(tmp_path: Path) -> None:
    immutable_plan = plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(immutable_plan.as_dict()), encoding="utf-8")
    registry_path = tmp_path / "private" / "registry.json"
    creation_digest = mutation_digest(
        immutable_plan,
        action="create-isolated-v3-types",
        outputs=[str(registry_path.absolute())],
    )
    client = FakeSDK()
    gateway = FulcraGateway(client)

    stopped = io.StringIO()
    assert (
        main(
            [
                "fulcra-types",
                "create",
                "--plan",
                str(plan_path),
                "--approve-plan",
                "0" * 64,
                "--registry",
                str(registry_path),
            ],
            fulcra_gateway=gateway,
            output=stopped,
        )
        == 2
    )
    assert client.created == []
    assert not registry_path.exists()

    output = io.StringIO()
    assert (
        main(
            [
                "fulcra-types",
                "create",
                "--plan",
                str(plan_path),
                "--approve-plan",
                creation_digest,
                "--registry",
                str(registry_path),
            ],
            fulcra_gateway=gateway,
            output=output,
        )
        == 0
    )
    assert len(client.created) == 3
    assert registry_path.stat().st_mode & 0o777 == 0o600
    assert TypeRegistry.load(registry_path).plan_digest == immutable_plan.digest


def test_candidate_schemas_preserve_timestamps_json_tags_and_ordered_sources() -> None:
    fingerprint = canonical_fingerprint("commit", "account-a", {"oid": "abc123"})
    moment = moment_record(
        fingerprint=fingerprint,
        recorded_at=START,
        note_payload={"repository": "synthetic/example", "activity_subtype": "commit"},
        tag_ids=["tag-v3", "tag-user", "tag-repository"],
        sources=ordered_sources("github.com", "commit:abc123", "engineering-journey-v3"),
    )
    duration = coverage_record(
        plan=plan(),
        repository_count=0,
        tag_ids=["tag-v3", "tag-user"],
        sources=["github.com", "snapshot:sha256:x", "engineering-journey-v3"],
    )
    assert moment["recorded_at"] == START
    assert duration["recorded_at"] == {"start_time": START, "end_time": END}
    assert json.loads(moment["note"])["schema_version"] == RECORD_SCHEMA_VERSION
    assert moment["sources"] == ["github.com", "commit:abc123", "engineering-journey-v3"]
    assert deterministic_record_id(fingerprint) == moment["id"]
    assert deterministic_record_id(fingerprint) == deterministic_record_id(fingerprint)
    names = v3_tags("github-user:account-a", "repository:synthetic/example", "visibility:private")
    assert names[0] == "ej3"
    assert names[-1] == "ej3-s-v1"
    assert all(len(name) <= 30 and name.replace("-", "").isalnum() for name in names)
    assert names == v3_tags(
        "github-user:account-a", "repository:synthetic/example", "visibility:private"
    )


def test_ambiguous_committed_write_response_loss_reconciles_without_duplicate() -> None:
    class AmbiguousSDK(FakeSDK):
        def record_data_type(self, **kwargs: Any) -> dict[str, Any]:
            super().record_data_type(**kwargs)
            raise URLError("response lost after commit")

    immutable_plan = plan()
    approval = approve_plan(immutable_plan, immutable_plan.digest)
    client = AmbiguousSDK()
    gateway = FulcraGateway(client)
    fingerprint = canonical_fingerprint("review", "account-a", {"node_id": "review-1"})
    record = moment_record(
        fingerprint=fingerprint,
        recorded_at=START,
        note_payload={"activity_subtype": "review"},
        tag_ids=["tag-v3"],
        sources=["github.com", "review:review-1"],
    )
    result = gateway.record_once(raw_type(), record, approval)
    assert result == {"reconciled": True, "record_id": record["id"]}
    assert client.write_calls == 1
    assert len(client.records) == 1


def test_transient_record_failure_before_commit_retries_without_duplicate() -> None:
    class PreCommitFailureSDK(FakeSDK):
        def record_data_type(self, **kwargs: Any) -> dict[str, Any]:
            self.write_calls += 1
            if self.write_calls == 1:
                raise URLError("connection lost before commit")
            self.write_calls -= 1
            return super().record_data_type(**kwargs)

    immutable_plan = plan()
    client = PreCommitFailureSDK()
    delays: list[float] = []
    gateway = FulcraGateway(
        client,
        retry_policy=RetryPolicy(attempts=2, base_delay=1, max_delay=1, jitter=0),
        sleep=delays.append,
    )
    fingerprint = canonical_fingerprint("commit", "account-a", {"oid": "retry-once"})
    record = moment_record(
        fingerprint=fingerprint,
        recorded_at=START,
        note_payload={"activity_subtype": "commit"},
        tag_ids=["tag-v3"],
        sources=["github.com", "commit:retry-once"],
    )

    result = gateway.record_once(
        raw_type(), record, approve_plan(immutable_plan, immutable_plan.digest)
    )

    assert result == {"upload_id": "upload-1"}
    assert client.write_calls == 2
    assert len(client.records) == 1
    assert delays == [1]


def test_transient_record_failure_before_commit_stops_at_write_attempt_limit() -> None:
    class AlwaysPreCommitFailureSDK(FakeSDK):
        def record_data_type(self, **kwargs: Any) -> dict[str, Any]:
            self.write_calls += 1
            raise URLError("connection lost before commit")

    immutable_plan = plan()
    client = AlwaysPreCommitFailureSDK()
    gateway = FulcraGateway(
        client,
        retry_policy=RetryPolicy(attempts=3, base_delay=0, max_delay=0, jitter=0),
        sleep=lambda _delay: None,
    )
    fingerprint = canonical_fingerprint("commit", "account-a", {"oid": "always-fails"})
    record = moment_record(
        fingerprint=fingerprint,
        recorded_at=START,
        note_payload={"activity_subtype": "commit"},
        tag_ids=["tag-v3"],
        sources=["github.com", "commit:always-fails"],
    )

    with pytest.raises(FulcraTransientError):
        gateway.record_once(raw_type(), record, approve_plan(immutable_plan, immutable_plan.digest))

    assert client.write_calls == 3
    assert client.records == {}


def test_ambiguous_type_creation_response_loss_reconciles_without_duplicate() -> None:
    class AmbiguousTypeSDK(FakeSDK):
        def create_annotation(self, **kwargs: Any) -> dict[str, Any]:
            result = super().create_annotation(**kwargs)
            if len(self.created) == 1:
                raise URLError("response lost after type commit")
            return result

    immutable_plan = plan()
    output = "/private/registry.json"
    client = AmbiguousTypeSDK()
    registry = FulcraGateway(client).create_registry(
        approve_mutation(
            immutable_plan,
            action="create-isolated-v3-types",
            outputs=[output],
            supplied_digest=mutation_digest(
                immutable_plan,
                action="create-isolated-v3-types",
                outputs=[output],
            ),
        )
    )
    assert len(client.created) == 3
    assert registry.get("raw_activity").type_id == client.created[0]["id"]


def test_type_creation_replay_finds_exact_catalog_entries_without_duplicate() -> None:
    immutable_plan = plan()
    output = "/private/registry.json"
    approval = approve_mutation(
        immutable_plan,
        action="create-isolated-v3-types",
        outputs=[output],
        supplied_digest=mutation_digest(
            immutable_plan,
            action="create-isolated-v3-types",
            outputs=[output],
        ),
    )
    client = FakeSDK()
    gateway = FulcraGateway(client)
    first = gateway.create_registry(approval)
    second = gateway.create_registry(approval)
    assert second == first
    assert len(client.created) == 3


def test_record_schema_fails_closed_before_sdk_validation_or_write() -> None:
    immutable_plan = plan()
    approval = approve_plan(immutable_plan, immutable_plan.digest)
    client = FakeSDK()
    gateway = FulcraGateway(client)
    fingerprint = canonical_fingerprint("commit", "account-a", {"oid": "abc123"})
    valid = moment_record(
        fingerprint=fingerprint,
        recorded_at=START,
        note_payload={"activity_subtype": "commit"},
        tag_ids=["tag-v3"],
        sources=["github.com", "commit:abc123"],
    )

    malformed = dict(valid)
    malformed["id"] = "not-the-deterministic-id"
    with pytest.raises(FulcraSchemaError, match="not derived"):
        gateway.record_once(raw_type(), malformed, approval)

    malformed = dict(valid)
    malformed["note"] = json.dumps(
        {"schema_version": "legacy", "fingerprint": fingerprint}, sort_keys=True
    )
    with pytest.raises(FulcraSchemaError, match="schema and fingerprint"):
        gateway.record_once(raw_type(), malformed, approval)

    malformed = dict(valid)
    malformed["recorded_at"] = {"start_time": START, "end_time": END}
    with pytest.raises(FulcraSchemaError, match="source timestamp"):
        gateway.record_once(raw_type(), malformed, approval)
    assert client.write_calls == 0

    with pytest.raises(FulcraSchemaError, match="reserved fingerprint"):
        moment_record(
            fingerprint=fingerprint,
            recorded_at=START,
            note_payload={"fingerprint": "override"},
            tag_ids=["tag-v3"],
            sources=["github.com"],
        )


def test_writes_and_private_file_uploads_reject_missing_capability() -> None:
    client = FakeSDK()
    gateway = FulcraGateway(client)
    with pytest.raises(FulcraApprovalError):
        gateway.create_registry(None)  # type: ignore[arg-type]
    with pytest.raises(FulcraApprovalError):
        PrivateFileGateway(gateway).upload_bytes(
            "/engineering-journey-runs/v3/account/run/plan.json",
            b"{}",
            "application/json",
            None,  # type: ignore[arg-type]
        )
    assert client.created == []
    assert client.uploads == []


def test_forged_approval_is_rejected_and_base_type_is_ingest_target() -> None:
    immutable_plan = plan()
    client = FakeSDK()
    gateway = FulcraGateway(client)
    fingerprint = canonical_fingerprint("commit", "account-a", {"oid": "abc123"})
    record = moment_record(
        fingerprint=fingerprint,
        recorded_at=START,
        note_payload={"activity_subtype": "commit"},
        tag_ids=["tag-v3"],
        sources=["github.com", "commit:abc123"],
    )
    with pytest.raises(TypeError):
        from engineering_journey_v3.fulcra_gateway import ApprovedPlan

        ApprovedPlan(immutable_plan, "plan", (), immutable_plan.digest)  # type: ignore[call-arg]

    gateway.record_once(raw_type(), record, approve_plan(immutable_plan, immutable_plan.digest))
    assert client.last_validate_data_type == raw_type().type_id
    assert client.last_write_data_type == raw_type().base_type
    written = next(iter(client.records.values()))
    assert written["sources"][-1] == (
        "com.fulcradynamics.annotation.11111111-1111-4111-8111-111111111111"
    )


def test_coverage_is_one_plan_bound_whole_window_including_zero_repository_snapshot() -> None:
    immutable_plan = plan()
    coverage_type = RegisteredType(
        key="coverage",
        name=TYPE_DEFINITIONS[2].name,
        base_type="DurationAnnotation",
        type_id=f"DurationAnnotation/{UUIDS[2]}",
        api_version=API_VERSION,
        fulcra_user_id="fulcra-user-1",
    )
    record = coverage_record(
        plan=immutable_plan,
        repository_count=0,
        tag_ids=["tag-v3"],
        sources=["github.com", "snapshot:sha256:synthetic-snapshot"],
    )
    client = FakeSDK()
    gateway = FulcraGateway(client)
    approval = approve_plan(immutable_plan, immutable_plan.digest)
    gateway.record_once(coverage_type, record, approval)
    assert client.write_calls == 1
    assert gateway.record_once(coverage_type, record, approval)["reconciled"] is True
    assert client.write_calls == 1

    malformed = dict(record)
    malformed["note"] = duration_record(
        fingerprint=record["fingerprint"],
        start_time=START,
        end_time=END,
        note_payload={"repository": "synthetic/example"},
        tag_ids=["tag-v3"],
        sources=["github.com"],
    )["note"]
    with pytest.raises(FulcraSchemaError, match="whole immutable window"):
        gateway.record_once(coverage_type, malformed, approval)


def test_private_file_gateway_round_trips_and_blocks_traversal() -> None:
    immutable_plan = plan()
    approval = approve_plan(immutable_plan, immutable_plan.digest)
    client = FakeSDK()
    files = PrivateFileGateway(FulcraGateway(client))
    remote = "/engineering-journey-runs/v3/account/run/plan.json"
    files.upload_bytes(remote, b"{}", "application/json", approval)
    assert client.uploads == [(remote, b"{}", "application/json")]
    assert files.download_bytes(remote) == b"private-content"
    with pytest.raises(FulcraSchemaError, match="traversal"):
        files.download_bytes("/engineering-journey-runs/../credentials.json")


def test_private_file_transient_retry_replays_the_complete_content() -> None:
    class RetryUploadSDK(FakeSDK):
        def __init__(self) -> None:
            super().__init__()
            self.attempt_contents: list[bytes] = []

        def upload_file(
            self, data: io.BufferedReader, file_type: str, file_size: int, filepath: str
        ) -> dict[str, Any]:
            content = data.read()
            self.attempt_contents.append(content)
            if len(self.attempt_contents) == 1:
                raise URLError("transient upload failure before commit")
            return super().upload_file(
                cast(io.BufferedReader, io.BytesIO(content)), file_type, file_size, filepath
            )

    immutable_plan = plan()
    client = RetryUploadSDK()
    files = PrivateFileGateway(
        FulcraGateway(
            client,
            retry_policy=RetryPolicy(attempts=2, base_delay=0, max_delay=0, jitter=0),
            sleep=lambda _delay: None,
        )
    )
    content = b'{"schema_version":"synthetic/v1"}'
    files.upload_bytes(
        "/engineering-journey-runs/v3/account/run/progress.jsonl",
        content,
        "application/x-ndjson",
        approve_plan(immutable_plan, immutable_plan.digest),
    )
    assert client.attempt_contents == [content, content]


def test_tag_resolution_requires_exact_ordered_name_to_id_mapping() -> None:
    immutable_plan = plan()
    approval = approve_plan(immutable_plan, immutable_plan.digest)
    client = FakeSDK()
    gateway = FulcraGateway(client)
    names = v3_tags("github-user:account-a", "repository:synthetic/example")
    assert gateway.resolve_tags(names, approval) == [f"tag-{index}" for index in range(len(names))]
    assert client.tag_calls == [names]

    class ReorderedTagSDK(FakeSDK):
        def create_tags(self, tag_names: list[str]) -> list[dict[str, str]]:
            return list(reversed(super().create_tags(tag_names)))

    with pytest.raises(FulcraSchemaError, match="requested dimensions"):
        FulcraGateway(ReorderedTagSDK()).resolve_tags(names, approval)


def test_query_and_agg_day_use_registered_type_routes() -> None:
    client = FakeSDK()
    client.query_payload = [{"id": "record-1"}]
    client.agg_payload = {"buckets": [{"day": "2025-01-02", "count": 1}]}
    gateway = FulcraGateway(client)
    assert gateway.query_records(raw_type(), {"start_time": START}) == [{"id": "record-1"}]
    assert gateway.aggregate_day(raw_type(), {"start_time": START, "end_time": END}) == {
        "buckets": [{"day": "2025-01-02", "count": 1}]
    }
    assert client.query_calls == [(f"event/{raw_type().type_id}", {"start_time": START})]


def test_reconciliation_queries_custom_event_range_and_filters_deterministic_id() -> None:
    immutable_plan = plan()
    fingerprint = canonical_fingerprint("commit", "account-a", {"oid": "abc123"})
    record = moment_record(
        fingerprint=fingerprint,
        recorded_at=START,
        note_payload={"activity_subtype": "commit"},
        tag_ids=["tag-v3"],
        sources=["github.com"],
    )
    client = FakeSDK()
    client.query_payload = [{"id": "other"}, record]
    gateway = FulcraGateway(client)
    found = gateway.get_record(
        raw_type(),
        record["id"],
        start_time=immutable_plan.start_utc,
        end_time=immutable_plan.end_utc,
    )
    assert found == record
    assert client.query_calls == [
        (
            f"event/{raw_type().type_id}",
            {"start_time": immutable_plan.start_utc, "end_time": immutable_plan.end_utc},
        )
    ]


def test_auth_schema_and_transient_failures_are_classified_and_retry_is_bounded() -> None:
    assert isinstance(classify_error(StatusError(401), operation="test"), FulcraAuthError)
    assert isinstance(classify_error(StatusError(422), operation="test"), FulcraSchemaError)
    assert isinstance(classify_error(StatusError(503), operation="test"), FulcraTransientError)
    http_validation = HTTPError("https://example.invalid", 422, "invalid", Message(), None)
    assert isinstance(classify_error(http_validation, operation="test"), FulcraSchemaError)
    assert isinstance(
        classify_error(socket.gaierror("DNS lookup failed"), operation="test"), FulcraTransientError
    )
    assert isinstance(
        classify_error(OSError(errno.ENETUNREACH, "network unreachable"), operation="test"),
        FulcraTransientError,
    )
    assert not isinstance(
        classify_error(PermissionError("local file denied"), operation="test"),
        FulcraTransientError,
    )
    assert not isinstance(
        classify_error(OSError("local deterministic failure"), operation="test"),
        FulcraTransientError,
    )

    class RetrySDK(FakeSDK):
        def __init__(self) -> None:
            super().__init__()
            self.failures = 2

        def v1_catalog(
            self,
            data_type: str | None = None,
            category: str | None = None,
            fulcra_userid: str | None = None,
        ) -> list[dict[str, Any]]:
            if self.failures:
                self.failures -= 1
                raise StatusError(503)
            return super().v1_catalog(data_type, category, fulcra_userid)

    delays: list[float] = []
    client = RetrySDK()
    gateway = FulcraGateway(
        client,
        retry_policy=RetryPolicy(attempts=3, base_delay=1, max_delay=2, jitter=0),
        sleep=delays.append,
    )
    gateway.catalog()
    assert delays == [1, 2]

    class AlwaysFailSDK(FakeSDK):
        def v1_catalog(
            self,
            data_type: str | None = None,
            category: str | None = None,
            fulcra_userid: str | None = None,
        ) -> list[dict[str, Any]]:
            raise StatusError(503)

    with pytest.raises(FulcraTransientError):
        FulcraGateway(
            AlwaysFailSDK(),
            retry_policy=RetryPolicy(attempts=2, base_delay=0, max_delay=0, jitter=0),
            sleep=lambda _delay: None,
        ).catalog()
