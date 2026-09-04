"""SDK-backed Fulcra record, type, tag, query, and private-file gateway."""

from __future__ import annotations

import errno
import hashlib
import hmac
import io
import json
import mimetypes
import os
import random
import re
import socket
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, TypeVar, cast
from urllib.error import HTTPError, URLError

from fulcra_api.core import FulcraAPI  # type: ignore[import-untyped]
from fulcra_api.credentials import FulcraCredentials  # type: ignore[import-untyped]

from engineering_journey_v3.fulcra_registry import (
    API_VERSION,
    RECORD_SCHEMA_VERSION,
    TYPE_DEFINITIONS,
    V3_MARKER_TAG,
    RegisteredType,
    TypeRegistry,
)
from engineering_journey_v3.plan import Plan, normalize_utc
from engineering_journey_v3.workflow import require_approval

_RECORD_NAMESPACE = uuid.UUID("45afd657-0896-5465-a40d-4b19b2bf06dc")
_APPROVAL_SEAL = object()
_TAG_MAX_LENGTH = 30
_TAG_KEY_ALIASES = {
    "github-user": "u",
    "repository": "r",
    "activity-subtype": "a",
    "visibility": "v",
    "stage": "g",
    "state": "t",
}
T = TypeVar("T")


class FulcraError(RuntimeError):
    """Base class for classified gateway failures."""


class FulcraAuthError(FulcraError):
    """Credentials are absent, expired beyond refresh, or rejected."""


class FulcraSchemaError(FulcraError):
    """A registry, schema, validation, or reconciliation invariant failed."""


class FulcraTransientError(FulcraError):
    """A bounded retryable network, throttling, or service failure occurred."""


class FulcraApprovalError(FulcraError):
    """A remote mutation was attempted without exact plan approval."""


class WriteDisposition(StrEnum):
    """Durable outcome used for exact ingestion count accounting."""

    WRITTEN = "written"
    ALREADY_PRESENT = "already_present"
    RECONCILED = "reconciled"


@dataclass(frozen=True, slots=True)
class RecordWriteOutcome:
    disposition: WriteDisposition
    record_id: str
    response: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ApprovedPlan:
    """Sealed capability produced only by an exact approval helper."""

    plan: Plan
    action: str
    outputs: tuple[str, ...]
    authorization_digest: str
    _seal: object = field(repr=False, compare=False)


def approve_plan(plan: Plan, supplied_digest: str | None) -> ApprovedPlan:
    try:
        require_approval(plan, supplied_digest)
    except RuntimeError as error:
        raise FulcraApprovalError(str(error)) from error
    return ApprovedPlan(plan, "plan", (), plan.digest, _APPROVAL_SEAL)


def mutation_digest(plan: Plan, *, action: str, outputs: list[str]) -> str:
    """Bind a separately displayed mutation to immutable scope and exact outputs."""
    payload = {
        "schema_version": "engineering-journey-v3-mutation-approval/v1",
        "plan_digest": plan.digest,
        "action": action,
        "outputs": outputs,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def approve_mutation(
    plan: Plan,
    *,
    action: str,
    outputs: list[str],
    supplied_digest: str | None,
) -> ApprovedPlan:
    expected = mutation_digest(plan, action=action, outputs=outputs)
    if supplied_digest is None or not hmac.compare_digest(expected, supplied_digest):
        raise FulcraApprovalError("approval digest does not match the displayed Fulcra mutation")
    return ApprovedPlan(plan, action, tuple(outputs), expected, _APPROVAL_SEAL)


def _require_capability(approval: ApprovedPlan) -> None:
    if not isinstance(approval, ApprovedPlan) or approval._seal is not _APPROVAL_SEAL:
        raise FulcraApprovalError("remote mutation requires an explicitly approved plan")
    expected = (
        approval.plan.digest
        if approval.action == "plan"
        else mutation_digest(
            approval.plan,
            action=approval.action,
            outputs=list(approval.outputs),
        )
    )
    if not hmac.compare_digest(expected, approval.authorization_digest):
        raise FulcraApprovalError("approved mutation capability does not match its plan")


class SDKClient(Protocol):
    fulcra_credentials: Any

    def get_fulcra_userid(self) -> str: ...
    def v1_catalog(
        self,
        data_type: str | None = None,
        category: str | None = None,
        fulcra_userid: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def create_annotation(self, **kwargs: Any) -> dict[str, Any]: ...
    def create_tags(self, tag_names: list[str]) -> list[dict[str, str]]: ...
    def validate_records(self, **kwargs: Any) -> list[tuple[int, str, Any]]: ...
    def record_data_type(self, **kwargs: Any) -> dict[str, Any]: ...
    def fulcra_v1_api_path(self, path: str, params: dict[str, str] | None = None) -> bytes: ...
    def fulcra_api(self, url_path: str, **kwargs: Any) -> bytes: ...
    def upload_file(
        self, data: io.BufferedReader, file_type: str, file_size: int, filepath: str
    ) -> dict[str, Any]: ...
    def resolve_filepath(self, filepath: str, **kwargs: Any) -> list[dict[str, Any]]: ...
    def download_file(self, file_id: str, **kwargs: Any) -> Any: ...


def _status(error: BaseException) -> int | None:
    value = getattr(error, "code", getattr(error, "status", None))
    return value if isinstance(value, int) else None


_NETWORK_ERRNOS = {
    errno.ECONNABORTED,
    errno.ECONNREFUSED,
    errno.ECONNRESET,
    errno.EHOSTUNREACH,
    errno.ENETDOWN,
    errno.ENETRESET,
    errno.ENETUNREACH,
    errno.ETIMEDOUT,
}


def _is_network_error(error: BaseException) -> bool:
    """Recognize transport failures without treating every local OS error as retryable."""
    if isinstance(error, PermissionError):
        return False
    if isinstance(error, socket.gaierror | TimeoutError | ConnectionError):
        return True
    if isinstance(error, URLError):
        return not isinstance(error.reason, PermissionError)
    return isinstance(error, OSError) and error.errno in _NETWORK_ERRNOS


def classify_error(error: BaseException, *, operation: str) -> FulcraError:
    """Classify failures without retrying deterministic errors."""
    if isinstance(error, FulcraError):
        return error
    status = _status(error)
    if status in {401, 403}:
        return FulcraAuthError(f"Fulcra authentication failed during {operation}")
    if status == 429 or status in {500, 502, 503, 504}:
        return FulcraTransientError(f"transient Fulcra failure during {operation}: HTTP {status}")
    if isinstance(error, ValueError | KeyError | TypeError) or status in {400, 404, 409, 422}:
        return FulcraSchemaError(f"Fulcra schema/validation failure during {operation}: {error}")
    if isinstance(error, HTTPError):
        return FulcraError(f"non-retryable Fulcra HTTP failure during {operation}: {status}")
    if _is_network_error(error):
        return FulcraTransientError(f"transient network failure during {operation}: {error}")
    return FulcraError(f"Fulcra failure during {operation}: {error}")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 4
    base_delay: float = 0.25
    max_delay: float = 2.0
    jitter: float = 0.1

    def __post_init__(self) -> None:
        if self.attempts < 1 or min(self.base_delay, self.max_delay, self.jitter) < 0:
            raise ValueError("retry policy values must be non-negative and attempts positive")


class FulcraGateway:
    """Narrow adapter around the supported Fulcra Python SDK."""

    def __init__(
        self,
        client: SDKClient,
        *,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.client = client
        self.retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep
        self._random = random_value
        if getattr(client, "fulcra_credentials", None) is None:
            raise FulcraAuthError(
                "no Fulcra SDK credentials; authenticate before using the gateway"
            )

    @classmethod
    def from_default_credentials(cls) -> FulcraGateway:
        configured = os.environ.get("FULCRA_CREDENTIALS_FILE")
        path = (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".config/fulcra/credentials.json"
        )
        try:
            credentials = FulcraCredentials.from_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise FulcraAuthError(
                "no Fulcra credentials; run `engineering-journey fulcra-auth`"
            ) from error
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise FulcraAuthError("Fulcra credentials could not be loaded") from error
        return cls(cast(SDKClient, FulcraAPI(credentials=credentials)))

    def _call(self, operation: str, function: Callable[[], T]) -> T:
        for attempt in range(self.retry_policy.attempts):
            try:
                return function()
            except Exception as raw_error:
                error = classify_error(raw_error, operation=operation)
                if (
                    not isinstance(error, FulcraTransientError)
                    or attempt + 1 == self.retry_policy.attempts
                ):
                    raise error from raw_error
                self._wait_before_retry(attempt)
        raise AssertionError("retry loop exhausted")

    def _wait_before_retry(self, attempt: int) -> None:
        delay = min(self.retry_policy.max_delay, self.retry_policy.base_delay * (2**attempt))
        self._sleep(delay + self.retry_policy.jitter * self._random())

    @property
    def user_id(self) -> str:
        return self._call("identify user", self.client.get_fulcra_userid)

    def catalog(self) -> list[dict[str, Any]]:
        """Fetch the owner catalog once and retain only exact isolated v3 entries."""
        owner = self.user_id
        response = self._call(
            "discover v3 types",
            partial(self.client.v1_catalog, fulcra_userid=owner),
        )
        if not isinstance(response, list) or not all(isinstance(item, dict) for item in response):
            raise FulcraSchemaError("v1 catalog did not return an array of objects")
        definitions = {definition.name: definition for definition in TYPE_DEFINITIONS}
        isolated: list[dict[str, Any]] = []
        for item in response:
            item_name = item.get("name")
            definition = definitions.get(item_name) if isinstance(item_name, str) else None
            type_id = item.get("id")
            if (
                definition is not None
                and item.get("fulcra_userid") == owner
                and item.get("api_version") == API_VERSION
                and isinstance(type_id, str)
                and type_id.startswith(f"{definition.base_type}/")
            ):
                isolated.append(item)
        return isolated

    def create_registry(self, approval: ApprovedPlan) -> TypeRegistry:
        """Find or explicitly create exactly the three isolated v3 types."""
        _require_capability(approval)
        if approval.action != "create-isolated-v3-types":
            raise FulcraApprovalError("type creation requires its separately displayed mutation")
        owner = self.user_id
        candidates = self.catalog()
        entries: list[RegisteredType] = []
        for definition in TYPE_DEFINITIONS:
            matches = [item for item in candidates if item.get("name") == definition.name]
            if len(matches) > 1:
                raise FulcraSchemaError(
                    f"ambiguous existing v3 type for {definition.key}: found {len(matches)}"
                )
            if matches:
                entries.append(
                    RegisteredType(
                        key=definition.key,
                        name=definition.name,
                        base_type=definition.base_type,
                        type_id=matches[0]["id"],
                        api_version=API_VERSION,
                        fulcra_user_id=owner,
                    )
                )
                continue
            annotation_type = "moment" if definition.base_type == "MomentAnnotation" else "duration"
            create = partial(
                self.client.create_annotation,
                annotation_type=annotation_type,
                name=definition.name,
                description=definition.description,
                tags=[V3_MARKER_TAG],
            )
            # Type creation has no caller-selected deterministic ID. Never blindly retry it:
            # a lost success response would create a second custom type. Reconcile the exact
            # owner-scoped v3 name instead and fail closed if the result is ambiguous.
            try:
                response = create()
            except Exception as raw_error:
                error = classify_error(raw_error, operation=f"create {definition.key} type")
                if not isinstance(error, FulcraTransientError):
                    raise error from raw_error
                candidates = self.catalog()
                matches = [
                    item
                    for item in candidates
                    if item.get("name") == definition.name
                    and item.get("fulcra_userid") == owner
                    and item.get("api_version") == API_VERSION
                    and isinstance(item.get("id"), str)
                    and item["id"].startswith(f"{definition.base_type}/")
                ]
                if len(matches) != 1:
                    raise FulcraSchemaError(
                        f"ambiguous type-creation reconciliation for {definition.key}: "
                        f"expected one exact v3 type, found {len(matches)}"
                    ) from raw_error
                response = matches[0]
            type_id = response.get("id")
            if not isinstance(type_id, str):
                raise FulcraSchemaError("created type response omitted its custom type ID")
            if "/" not in type_id:
                type_id = f"{definition.base_type}/{type_id}"
            entries.append(
                RegisteredType(
                    key=definition.key,
                    name=definition.name,
                    base_type=definition.base_type,
                    type_id=type_id,
                    api_version=API_VERSION,
                    fulcra_user_id=owner,
                )
            )
        registry = TypeRegistry(tuple(entries), plan_digest=approval.plan.digest)
        # Before these IDs are saved, apply the same fresh owner-catalog check used
        # for every later registry verification.
        self.verify_registry(registry)
        return registry

    def verify_registry(self, registry: TypeRegistry) -> None:
        """Verify IDs and exact v3 names against the owner-scoped SDK catalog."""
        owner = self.user_id
        if registry.types[0].fulcra_user_id != owner:
            raise FulcraSchemaError("registry owner is not the authenticated Fulcra user")
        catalog = self.catalog()
        for entry in registry.types:
            matches = [
                item
                for item in catalog
                if item.get("id") == entry.type_id
                and item.get("name") == entry.name
                and item.get("fulcra_userid") == owner
                and item.get("api_version") == entry.api_version
            ]
            if len(matches) != 1:
                raise FulcraSchemaError(f"registered v3 type is absent: {entry.type_id}")

    def resolve_tags(self, names: list[str], approval: ApprovedPlan) -> list[str]:
        _require_capability(approval)
        if not names or any(not name or name != name.strip() for name in names):
            raise FulcraSchemaError("tag names must be non-empty canonical strings")
        unique_names = list(dict.fromkeys(names))
        response = self._call("resolve tags", lambda: self.client.create_tags(unique_names))
        if len(response) != len(unique_names):
            raise FulcraSchemaError("Fulcra tag response did not match the requested dimensions")
        ids: list[str] = []
        for expected_name, tag in zip(unique_names, response, strict=True):
            tag_id = tag.get("id")
            if tag.get("name") != expected_name or not isinstance(tag_id, str) or not tag_id:
                raise FulcraSchemaError(
                    "Fulcra tag response did not match the requested dimensions"
                )
            ids.append(tag_id)
        return ids

    def query_records(
        self, registered_type: RegisteredType, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        payload = self._call(
            "query records",
            lambda: self.client.fulcra_v1_api_path(f"event/{registered_type.type_id}", params),
        )
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise FulcraSchemaError("record query returned malformed JSON") from error
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise FulcraSchemaError("record query did not return an array of objects")
        return cast(list[dict[str, Any]], value)

    def aggregate_day(self, registered_type: RegisteredType, params: dict[str, str]) -> Any:
        payload = self._call(
            "aggregate day",
            lambda: self.client.fulcra_api(
                f"/data/v1alpha1/event/{registered_type.type_id}/agg/day", query=params
            ),
        )
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise FulcraSchemaError("day aggregation returned malformed JSON") from error

    def get_record(
        self,
        registered_type: RegisteredType,
        record_id: str,
        *,
        start_time: str,
        end_time: str,
    ) -> dict[str, Any] | None:
        """Find a deterministic ID in the supported custom-event range query."""
        records = self.query_records(
            registered_type,
            {"start_time": normalize_utc(start_time), "end_time": normalize_utc(end_time)},
        )
        matches = [record for record in records if record.get("id") == record_id]
        if len(matches) > 1:
            raise FulcraSchemaError("record reconciliation found a duplicate deterministic ID")
        return matches[0] if matches else None

    def record_once(
        self,
        registered_type: RegisteredType,
        record: dict[str, Any],
        approval: ApprovedPlan,
    ) -> dict[str, Any]:
        """Write once; reconcile deterministic ID after ambiguous response loss."""
        outcome = self.record_once_classified(registered_type, record, approval)
        if outcome.disposition == WriteDisposition.WRITTEN:
            return dict(outcome.response)
        return {"reconciled": True, "record_id": outcome.record_id}

    def record_once_classified(
        self,
        registered_type: RegisteredType,
        record: dict[str, Any],
        approval: ApprovedPlan,
    ) -> RecordWriteOutcome:
        """Idempotently write one record and expose how durability was established."""
        return self.record_batch_once_classified(registered_type, [record], approval)[0]

    def record_batch_once_classified(
        self,
        registered_type: RegisteredType,
        records: list[dict[str, Any]],
        approval: ApprovedPlan,
    ) -> list[RecordWriteOutcome]:
        """Write one actual SDK batch, reconciling every ID before any retry."""
        _require_capability(approval)
        if not records:
            return []
        candidates = [_record_for_custom_type(registered_type, record) for record in records]
        by_id: dict[str, dict[str, Any]] = {}
        for record in candidates:
            _validate_record_for_type(registered_type, record, approval.plan)
            record_id = record.get("id")
            fingerprint = record.get("fingerprint")
            if not isinstance(record_id, str) or not isinstance(fingerprint, str):
                raise FulcraSchemaError("records require deterministic id and fingerprint")
            if record_id in by_id:
                raise FulcraSchemaError("record batch contains a duplicate deterministic ID")
            by_id[record_id] = record

        def reconcile(disposition: WriteDisposition) -> dict[str, RecordWriteOutcome]:
            observed = self.query_records(
                registered_type,
                {
                    "start_time": approval.plan.start_utc,
                    "end_time": approval.plan.end_utc,
                },
            )
            matches: dict[str, list[dict[str, Any]]] = {record_id: [] for record_id in by_id}
            for existing in observed:
                record_id = existing.get("id")
                if isinstance(record_id, str) and record_id in matches:
                    matches[record_id].append(existing)
            outcomes: dict[str, RecordWriteOutcome] = {}
            for record_id, found in matches.items():
                if len(found) > 1:
                    raise FulcraSchemaError(
                        "record reconciliation found a duplicate deterministic ID"
                    )
                if not found:
                    continue
                expected = cast(str, by_id[record_id]["fingerprint"])
                if not hmac.compare_digest(extract_fingerprint(found[0]), expected):
                    raise FulcraSchemaError(
                        "deterministic record ID collided with different evidence"
                    )
                outcomes[record_id] = RecordWriteOutcome(
                    disposition, record_id, {"reconciled": True}
                )
            return outcomes

        outcomes = reconcile(WriteDisposition.ALREADY_PRESENT)
        pending = [record for record in candidates if record["id"] not in outcomes]
        if not pending:
            return [outcomes[cast(str, record["id"])] for record in candidates]
        errors = self._call(
            "validate record batch",
            lambda: self.client.validate_records(
                data_type=registered_type.type_id,
                records=pending,
                api_version=registered_type.api_version,
            ),
        )
        if errors:
            raise FulcraSchemaError(f"record validation failed: {errors[0][1]}")
        for attempt in range(self.retry_policy.attempts):
            try:
                response = self.client.record_data_type(
                    data_type=registered_type.base_type,
                    records=pending,
                    api_version=registered_type.api_version,
                )
                for record in pending:
                    record_id = cast(str, record["id"])
                    outcomes[record_id] = RecordWriteOutcome(
                        WriteDisposition.WRITTEN, record_id, response
                    )
                return [outcomes[cast(str, record["id"])] for record in candidates]
            except Exception as raw_error:
                error = classify_error(raw_error, operation="record batch write")
                if not isinstance(error, FulcraTransientError):
                    raise error from raw_error
                observed = reconcile(WriteDisposition.RECONCILED)
                for record in pending:
                    record_id = cast(str, record["id"])
                    if record_id in observed:
                        outcomes[record_id] = observed[record_id]
                pending = [record for record in pending if record["id"] not in outcomes]
                if not pending:
                    return [outcomes[cast(str, record["id"])] for record in candidates]
                if attempt + 1 == self.retry_policy.attempts:
                    raise error from raw_error
                self._wait_before_retry(attempt)
        raise AssertionError("record batch retry loop exhausted")


class PrivateFileGateway:
    """Versioned private Fulcra files; every upload requires approved scope."""

    def __init__(self, gateway: FulcraGateway) -> None:
        self.gateway = gateway

    @staticmethod
    def _path(remote_path: str) -> str:
        path = PurePosixPath(remote_path)
        if not path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
            raise FulcraSchemaError("Fulcra file path must be absolute and traversal-free")
        return str(path)

    def upload_bytes(
        self,
        remote_path: str,
        content: bytes,
        content_type: str,
        approval: ApprovedPlan,
    ) -> dict[str, Any]:
        _require_capability(approval)
        path = self._path(remote_path)

        def upload() -> dict[str, Any]:
            # upload_file consumes its stream. A retry must receive the complete content,
            # not the exhausted stream left by the failed attempt.
            stream = io.BytesIO(content)
            return self.gateway.client.upload_file(
                cast(io.BufferedReader, stream), content_type, len(content), path
            )

        return self.gateway._call(
            "private file upload",
            upload,
        )

    def upload_path(
        self, local_path: Path, remote_path: str, approval: ApprovedPlan
    ) -> dict[str, Any]:
        content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        return self.upload_bytes(remote_path, local_path.read_bytes(), content_type, approval)

    def download_bytes(self, remote_path: str) -> bytes:
        path = self._path(remote_path)
        versions = self.gateway._call(
            "private file resolve", lambda: self.gateway.client.resolve_filepath(path)
        )
        if not versions or not isinstance(versions[0].get("id"), str):
            raise FulcraSchemaError("Fulcra file resolve returned no valid version")
        response = self.gateway._call(
            "private file download",
            lambda: self.gateway.client.download_file(versions[0]["id"]),
        )
        return cast(bytes, response.read())

    def download_uploaded_bytes(self, upload_result: Mapping[str, Any]) -> bytes:
        """Download the exact version returned by an upload, avoiding path-resolution lag."""
        file_value = upload_result.get("file")
        file_id = file_value.get("id") if isinstance(file_value, Mapping) else None
        if not isinstance(file_id, str) or not file_id:
            raise FulcraSchemaError("Fulcra file upload returned no valid file version ID")
        response = self.gateway._call(
            "private uploaded file download",
            lambda: self.gateway.client.download_file(file_id),
        )
        return cast(bytes, response.read())


def canonical_fingerprint(kind: str, identity: str, immutable_fields: Mapping[str, Any]) -> str:
    """Return a stable source-kind fingerprint over immutable canonical JSON."""
    payload = {
        "kind": kind,
        "identity": identity,
        "immutable_fields": immutable_fields,
        "schema_version": RECORD_SCHEMA_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def deterministic_record_id(fingerprint: str) -> str:
    if not re_full_sha256(fingerprint):
        raise FulcraSchemaError("fingerprint must be a lowercase SHA-256 digest")
    return str(uuid.uuid5(_RECORD_NAMESPACE, fingerprint))


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def canonical_note(payload: Mapping[str, Any]) -> str:
    """Encode structured record content as versioned compact JSON."""
    if "schema_version" in payload:
        raise FulcraSchemaError("note payload cannot override reserved schema_version")
    value = {"schema_version": RECORD_SCHEMA_VERSION, **payload}
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def moment_record(
    *,
    fingerprint: str,
    recorded_at: str,
    note_payload: Mapping[str, Any],
    tag_ids: list[str],
    sources: list[str],
) -> dict[str, Any]:
    """Build a candidate MomentAnnotation using its semantic source timestamp."""
    if "fingerprint" in note_payload:
        raise FulcraSchemaError("note payload cannot override reserved fingerprint")
    timestamp = normalize_utc(recorded_at)
    note = canonical_note({"fingerprint": fingerprint, **note_payload})
    return {
        "id": deterministic_record_id(fingerprint),
        "fingerprint": fingerprint,
        "recorded_at": timestamp,
        "note": note,
        "tags": list(tag_ids),
        "sources": ordered_sources(*sources),
    }


def duration_record(
    *,
    fingerprint: str,
    start_time: str,
    end_time: str,
    note_payload: Mapping[str, Any],
    tag_ids: list[str],
    sources: list[str],
) -> dict[str, Any]:
    """Build one candidate whole-window DurationAnnotation."""
    if "fingerprint" in note_payload:
        raise FulcraSchemaError("note payload cannot override reserved fingerprint")
    start = normalize_utc(start_time)
    end = normalize_utc(end_time)
    if start >= end:
        raise FulcraSchemaError("coverage start must be before coverage end")
    note = canonical_note({"fingerprint": fingerprint, **note_payload})
    return {
        "id": deterministic_record_id(fingerprint),
        "fingerprint": fingerprint,
        "recorded_at": {"start_time": start, "end_time": end},
        "note": note,
        "tags": list(tag_ids),
        "sources": ordered_sources(*sources),
    }


def coverage_record(
    *,
    plan: Plan,
    repository_count: int,
    tag_ids: list[str],
    sources: list[str],
) -> dict[str, Any]:
    """Build the sole whole-window coverage fact for one immutable run and snapshot."""
    if plan.repository_snapshot_digest == "pending-discovery":
        raise FulcraSchemaError("coverage requires a frozen repository snapshot digest")
    if (
        isinstance(repository_count, bool)
        or not isinstance(repository_count, int)
        or repository_count < 0
    ):
        raise FulcraSchemaError("coverage repository count must be a non-negative integer")
    immutable_fields = {
        "run_id": plan.run_id,
        "window_start": plan.start_utc,
        "window_end": plan.end_utc,
        "snapshot_digest": plan.repository_snapshot_digest,
        "source_semantics_version": plan.source_semantics_version,
    }
    fingerprint = canonical_fingerprint("coverage", plan.identity, immutable_fields)
    return duration_record(
        fingerprint=fingerprint,
        start_time=plan.start_utc,
        end_time=plan.end_utc,
        note_payload={
            **immutable_fields,
            "identity": plan.identity,
            "repository_count": repository_count,
        },
        tag_ids=tag_ids,
        sources=sources,
    )


def ordered_sources(*sources: str) -> list[str]:
    if not sources or any(not source or source != source.strip() for source in sources):
        raise FulcraSchemaError("sources must be ordered non-empty canonical strings")
    return list(dict.fromkeys(sources))


def annotation_source(registered_type: RegisteredType) -> str:
    """Return the SDK-required provenance source for one custom annotation."""
    _, annotation_uuid = registered_type.type_id.split("/", maxsplit=1)
    return f"com.fulcradynamics.annotation.{annotation_uuid.lower()}"


def _record_for_custom_type(
    registered_type: RegisteredType, record: Mapping[str, Any]
) -> dict[str, Any]:
    value = dict(record)
    sources = value.get("sources")
    if not isinstance(sources, list):
        raise FulcraSchemaError("record sources must be an ordered list")
    value["sources"] = ordered_sources(*sources, annotation_source(registered_type))
    return value


def _tag_name(dimension: str) -> str:
    if ":" not in dimension:
        raise FulcraSchemaError("tag dimensions must use key:value form")
    key, value = dimension.split(":", maxsplit=1)
    key = _TAG_KEY_ALIASES.get(key, key)
    safe_key = re.sub(r"[^A-Za-z0-9-]", "-", key).strip("-")
    safe_value = re.sub(r"[^A-Za-z0-9-]", "-", value).strip("-")
    if not safe_key or not safe_value:
        raise FulcraSchemaError("tag dimensions must contain reusable key and value")
    candidate = f"ej3-{safe_key}-{safe_value}"
    if candidate != f"ej3-{key}-{value}" or len(candidate) > _TAG_MAX_LENGTH:
        digest = hashlib.sha256(dimension.encode()).hexdigest()[:8]
        available = _TAG_MAX_LENGTH - len(f"ej3-{safe_key}--{digest}")
        candidate = f"ej3-{safe_key}-{safe_value[:available]}-{digest}"
    if len(candidate) > _TAG_MAX_LENGTH:
        raise FulcraSchemaError("tag dimension key is too long")
    return candidate


def v3_tags(*dimensions: str) -> list[str]:
    if any(not value or value != value.strip() for value in dimensions):
        raise FulcraSchemaError("tag dimensions must be non-empty canonical strings")
    names = ("ej3", *(_tag_name(dimension) for dimension in dimensions), "ej3-s-v1")
    return list(dict.fromkeys(names))


def extract_fingerprint(record: Mapping[str, Any]) -> str:
    direct = record.get("fingerprint")
    if isinstance(direct, str):
        return direct
    note = record.get("note")
    if isinstance(note, str):
        try:
            value = json.loads(note)
        except json.JSONDecodeError as error:
            raise FulcraSchemaError("existing record note is malformed JSON") from error
        fingerprint = value.get("fingerprint") if isinstance(value, dict) else None
        if isinstance(fingerprint, str):
            return fingerprint
    raise FulcraSchemaError("existing record has no reconcilable fingerprint")


def _validate_record_for_type(
    registered_type: RegisteredType,
    record: Mapping[str, Any],
    plan: Plan,
) -> None:
    """Enforce application invariants before SDK schema validation or mutation."""
    expected_fields = {"id", "fingerprint", "recorded_at", "note", "tags", "sources"}
    if set(record) != expected_fields:
        raise FulcraSchemaError("record fields do not match the v3 candidate schema")
    fingerprint = record.get("fingerprint")
    if not isinstance(fingerprint, str) or not re_full_sha256(fingerprint):
        raise FulcraSchemaError("record fingerprint must be a lowercase SHA-256 digest")
    if record.get("id") != deterministic_record_id(fingerprint):
        raise FulcraSchemaError("record ID is not derived from its canonical fingerprint")
    note = record.get("note")
    try:
        payload = json.loads(note) if isinstance(note, str) else None
    except json.JSONDecodeError as error:
        raise FulcraSchemaError("record note is malformed JSON") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != RECORD_SCHEMA_VERSION
        or payload.get("fingerprint") != fingerprint
    ):
        raise FulcraSchemaError("record note is not bound to its schema and fingerprint")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if note != canonical:
        raise FulcraSchemaError("record note must use canonical versioned JSON")
    for field_name in ("tags", "sources"):
        values = record.get(field_name)
        if (
            not isinstance(values, list)
            or not values
            or not all(
                isinstance(value, str) and value and value == value.strip() for value in values
            )
            or len(values) != len(set(values))
        ):
            raise FulcraSchemaError(f"record {field_name} must be ordered unique non-empty strings")
    recorded_at = record.get("recorded_at")
    if registered_type.base_type == "MomentAnnotation":
        if not isinstance(recorded_at, str) or normalize_utc(recorded_at) != recorded_at:
            raise FulcraSchemaError("moment record requires one canonical UTC source timestamp")
    elif not (
        isinstance(recorded_at, dict)
        and set(recorded_at) == {"start_time", "end_time"}
        and all(isinstance(value, str) for value in recorded_at.values())
        and normalize_utc(recorded_at["start_time"]) == recorded_at["start_time"]
        and normalize_utc(recorded_at["end_time"]) == recorded_at["end_time"]
        and recorded_at["start_time"] < recorded_at["end_time"]
    ):
        raise FulcraSchemaError("duration record requires canonical ordered UTC bounds")
    if registered_type.key != "coverage":
        return
    required = {
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
    if set(payload) != required:
        raise FulcraSchemaError("coverage note fields must describe one whole immutable window")
    immutable_fields = {
        "run_id": plan.run_id,
        "window_start": plan.start_utc,
        "window_end": plan.end_utc,
        "snapshot_digest": plan.repository_snapshot_digest,
        "source_semantics_version": plan.source_semantics_version,
    }
    expected_fingerprint = canonical_fingerprint("coverage", plan.identity, immutable_fields)
    expected = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "fingerprint": expected_fingerprint,
        **immutable_fields,
        "identity": plan.identity,
        "repository_count": payload["repository_count"],
    }
    if payload != expected or record.get("fingerprint") != expected_fingerprint:
        raise FulcraSchemaError("coverage is not bound to the approved run/window/snapshot")
    if recorded_at != {"start_time": plan.start_utc, "end_time": plan.end_utc}:
        raise FulcraSchemaError("coverage duration does not match the approved UTC window")
    count = payload["repository_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise FulcraSchemaError("coverage repository count must be a non-negative integer")
