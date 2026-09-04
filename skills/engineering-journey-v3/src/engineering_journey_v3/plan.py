"""Immutable, canonical plan construction and approval binding."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

Mode = Literal["write", "resume", "rewrite"]

PLAN_SCHEMA_VERSION = "engineering-journey-plan/v1"
SOURCE_SEMANTICS_VERSION = "engineering-journey-v3-github-sources/v1"
DEFAULT_REPOSITORY_POLICY = "all-directly-accessible-and-required-contribution-repositories"
DEFAULT_STAGES = (
    "repository-discovery",
    "pre-check",
    "github-ingestion",
    "fulcra-write",
    "coverage",
    "narrative-handoff",
    "publication",
)
DEFAULT_PRIVATE_DATA_BEHAVIOR = (
    "include accessible public and private repositories; keep evidence and outputs private"
)
_PENDING_SNAPSHOT = "pending-discovery"
_UTC_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_PLAN_NAMESPACE = uuid.UUID("cc782473-4a28-5e77-bb23-d52f6ed802ea")


class PlanValidationError(ValueError):
    """Raised when plan input is malformed, ambiguous, or non-UTC."""


def normalize_utc(value: str) -> str:
    """Validate an explicit UTC timestamp and return one canonical representation."""
    if not _UTC_PATTERN.fullmatch(value):
        raise PlanValidationError("timestamp must be an explicit ISO-8601 UTC value ending in Z")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise PlanValidationError(f"invalid UTC timestamp: {value}") from error
    timespec = "microseconds" if parsed.microsecond else "seconds"
    return parsed.astimezone(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class Plan:
    """All user-visible scope that an approval digest authorizes."""

    identity: str
    start_utc: str
    end_utc: str
    repository_policy: str
    mode: Mode
    stages: tuple[str, ...]
    private_data_behavior: str
    outputs: tuple[str, ...]
    repository_snapshot_digest: str = _PENDING_SNAPSHOT
    source_semantics_version: str = SOURCE_SEMANTICS_VERSION
    schema_version: str = PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        identity = self.identity.strip()
        if not identity or identity != self.identity or any(char.isspace() for char in identity):
            raise PlanValidationError("identity must be one non-empty GitHub login")
        start = normalize_utc(self.start_utc)
        end = normalize_utc(self.end_utc)
        if start != self.start_utc or end != self.end_utc:
            raise PlanValidationError("UTC bounds must use their canonical representation")
        if datetime.fromisoformat(start.replace("Z", "+00:00")) >= datetime.fromisoformat(
            end.replace("Z", "+00:00")
        ):
            raise PlanValidationError("start UTC bound must be earlier than end UTC bound")
        if self.mode not in ("write", "resume", "rewrite"):
            raise PlanValidationError(f"unsupported mode: {self.mode}")
        scalar_values = (
            self.repository_policy,
            self.private_data_behavior,
            self.repository_snapshot_digest,
            self.source_semantics_version,
            self.schema_version,
        )
        if any(not value.strip() for value in scalar_values):
            raise PlanValidationError("plan fields must not be empty")
        if not self.stages or not self.outputs or any(not value.strip() for value in self.stages):
            raise PlanValidationError("plan stages and outputs must not be empty")
        if any(not value.strip() for value in self.outputs):
            raise PlanValidationError("plan outputs must not be empty")

    def as_dict(self) -> dict[str, Any]:
        """Return the stable plan payload used for display, persistence, and hashing."""
        return {
            "schema_version": self.schema_version,
            "identity": self.identity,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "repository_policy": self.repository_policy,
            "repository_snapshot_digest": self.repository_snapshot_digest,
            "source_semantics_version": self.source_semantics_version,
            "mode": self.mode,
            "stages": list(self.stages),
            "private_data_behavior": self.private_data_behavior,
            "outputs": list(self.outputs),
        }

    @property
    def canonical_json(self) -> str:
        """Return byte-stable JSON for approval and run identity derivation."""
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def digest(self) -> str:
        """Return the approval digest for the complete immutable plan."""
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    @property
    def run_id(self) -> str:
        """Return a deterministic run identity bound to all plan scope dimensions."""
        return str(uuid.uuid5(_PLAN_NAMESPACE, self.canonical_json))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Plan:
        """Strictly decode a persisted plan, rejecting missing or extra scope fields."""
        expected = {
            "schema_version",
            "identity",
            "start_utc",
            "end_utc",
            "repository_policy",
            "repository_snapshot_digest",
            "source_semantics_version",
            "mode",
            "stages",
            "private_data_behavior",
            "outputs",
        }
        if set(value) != expected:
            raise PlanValidationError("persisted plan fields do not match the plan schema")
        scalar_fields = expected - {"stages", "outputs"}
        if any(not isinstance(value[field], str) for field in scalar_fields):
            raise PlanValidationError("persisted plan scalar fields must be strings")
        stage_value = value["stages"]
        output_value = value["outputs"]
        if (
            not isinstance(stage_value, list)
            or not all(isinstance(item, str) for item in stage_value)
            or not isinstance(output_value, list)
            or not all(isinstance(item, str) for item in output_value)
        ):
            raise PlanValidationError("persisted plan stages and outputs must be string arrays")
        try:
            return cls(
                schema_version=cast(str, value["schema_version"]),
                identity=cast(str, value["identity"]),
                start_utc=cast(str, value["start_utc"]),
                end_utc=cast(str, value["end_utc"]),
                repository_policy=cast(str, value["repository_policy"]),
                repository_snapshot_digest=cast(str, value["repository_snapshot_digest"]),
                source_semantics_version=cast(str, value["source_semantics_version"]),
                mode=cast(Mode, value["mode"]),
                stages=tuple(stage_value),
                private_data_behavior=cast(str, value["private_data_behavior"]),
                outputs=tuple(output_value),
            )
        except (KeyError, TypeError, AttributeError) as error:
            raise PlanValidationError("persisted plan has invalid field types") from error


def build_plan(
    *,
    identity: str,
    start_utc: str,
    end_utc: str,
    mode: Mode = "write",
    repository_policy: str = DEFAULT_REPOSITORY_POLICY,
    output_directory: str | None = None,
    repository_snapshot_digest: str = _PENDING_SNAPSHOT,
) -> Plan:
    """Build a plan only after the caller has explicitly confirmed ``identity``."""
    start = normalize_utc(start_utc)
    end = normalize_utc(end_utc)
    root = output_directory or f"/engineering-journeys/{identity}/{start[:4]}"
    return Plan(
        identity=identity,
        start_utc=start,
        end_utc=end,
        repository_policy=repository_policy,
        repository_snapshot_digest=repository_snapshot_digest,
        mode=mode,
        stages=DEFAULT_STAGES,
        private_data_behavior=DEFAULT_PRIVATE_DATA_BEHAVIOR,
        outputs=(f"{root}/engineering-journey.md", f"{root}/sources.md"),
    )


def approval_matches(plan: Plan, supplied_digest: str | None) -> bool:
    """Accept approval only when it exactly binds to the current plan payload."""
    return supplied_digest is not None and hmac.compare_digest(plan.digest, supplied_digest)
