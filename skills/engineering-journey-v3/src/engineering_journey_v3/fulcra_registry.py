"""Strict, v3-only Fulcra custom-type registry and candidate schemas."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from engineering_journey_v3.plan import PlanValidationError, approval_matches

REGISTRY_SCHEMA_VERSION = "engineering-journey-v3-type-registry/v1"
RECORD_SCHEMA_VERSION = "engineering-journey-v3-record/v1"
V3_MARKER_TAG = "engineering-journey:v3"
API_VERSION = "v1alpha1"
TypeKey = Literal["raw_activity", "run_event", "coverage"]


class RegistryError(ValueError):
    """Raised when a type registry is malformed, ambiguous, or not isolated v3."""


@dataclass(frozen=True, slots=True)
class TypeDefinition:
    key: TypeKey
    name: str
    base_type: Literal["MomentAnnotation", "DurationAnnotation"]
    description: str


TYPE_DEFINITIONS = (
    TypeDefinition(
        "raw_activity",
        "Engineering Journey v3 GitHub Activity",
        "MomentAnnotation",
        "Canonical normalized GitHub source facts for Engineering Journey v3.",
    ),
    TypeDefinition(
        "run_event",
        "Engineering Journey v3 Run Event",
        "MomentAnnotation",
        "Bounded operational milestones for an Engineering Journey v3 run.",
    ),
    TypeDefinition(
        "coverage",
        "Engineering Journey v3 GitHub History Coverage",
        "DurationAnnotation",
        "Completed whole-window GitHub history coverage for Engineering Journey v3.",
    ),
)
_DEFINITIONS = {definition.key: definition for definition in TYPE_DEFINITIONS}
_CUSTOM_ID = re.compile(r"(MomentAnnotation|DurationAnnotation)/([0-9a-fA-F-]{36})\Z")


@dataclass(frozen=True, slots=True)
class RegisteredType:
    key: TypeKey
    name: str
    base_type: Literal["MomentAnnotation", "DurationAnnotation"]
    type_id: str
    api_version: str
    fulcra_user_id: str

    def __post_init__(self) -> None:
        expected = _DEFINITIONS.get(self.key)
        if expected is None or self.name != expected.name or self.base_type != expected.base_type:
            raise RegistryError(f"registry entry {self.key!r} is not the exact v3 type definition")
        match = _CUSTOM_ID.fullmatch(self.type_id)
        if match is None or match.group(1) != self.base_type:
            raise RegistryError(f"registry entry {self.key!r} must contain a new custom-type ID")
        try:
            UUID(match.group(2))
        except ValueError as error:
            raise RegistryError(f"registry entry {self.key!r} has an invalid UUID") from error
        if self.api_version != API_VERSION or not self.fulcra_user_id:
            raise RegistryError("registry entries require v1alpha1 and one Fulcra owner")

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "name": self.name,
            "base_type": self.base_type,
            "type_id": self.type_id,
            "api_version": self.api_version,
            "fulcra_user_id": self.fulcra_user_id,
        }


@dataclass(frozen=True, slots=True)
class TypeRegistry:
    types: tuple[RegisteredType, ...]
    plan_digest: str
    schema_version: str = REGISTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REGISTRY_SCHEMA_VERSION:
            raise RegistryError("unsupported registry schema version")
        if len(self.types) != len(TYPE_DEFINITIONS):
            raise RegistryError("registry must contain exactly the three v3 types")
        by_key = {entry.key: entry for entry in self.types}
        if set(by_key) != set(_DEFINITIONS) or len(by_key) != len(self.types):
            raise RegistryError("registry keys must be unique and exactly match v3 definitions")
        owners = {entry.fulcra_user_id for entry in self.types}
        if len(owners) != 1 or not self.plan_digest:
            raise RegistryError("registry requires one owner and its creating plan digest")

    def get(self, key: TypeKey) -> RegisteredType:
        return next(entry for entry in self.types if entry.key == key)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_digest": self.plan_digest,
            "types": [entry.as_dict() for entry in self.types],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_json(cls, document: str) -> TypeRegistry:
        try:
            value = json.loads(document)
        except json.JSONDecodeError as error:
            raise RegistryError("registry is not valid JSON") from error
        if not isinstance(value, dict) or set(value) != {"schema_version", "plan_digest", "types"}:
            raise RegistryError("registry fields do not match the v3 registry schema")
        if not isinstance(value["types"], list):
            raise RegistryError("registry types must be an array")
        entries: list[RegisteredType] = []
        expected_fields = {"key", "name", "base_type", "type_id", "api_version", "fulcra_user_id"}
        for item in value["types"]:
            if not isinstance(item, dict) or set(item) != expected_fields:
                raise RegistryError("registry type fields do not match the v3 schema")
            if not all(isinstance(item[field], str) for field in expected_fields):
                raise RegistryError("registry type fields must be strings")
            entries.append(
                RegisteredType(
                    key=cast(TypeKey, item["key"]),
                    name=item["name"],
                    base_type=cast(
                        Literal["MomentAnnotation", "DurationAnnotation"], item["base_type"]
                    ),
                    type_id=item["type_id"],
                    api_version=item["api_version"],
                    fulcra_user_id=item["fulcra_user_id"],
                )
            )
        if not isinstance(value["schema_version"], str) or not isinstance(
            value["plan_digest"], str
        ):
            raise RegistryError("registry metadata fields must be strings")
        return cls(
            types=tuple(entries),
            plan_digest=value["plan_digest"],
            schema_version=value["schema_version"],
        )

    @classmethod
    def load(cls, path: Path) -> TypeRegistry:
        return cls.from_json(path.read_text(encoding="utf-8"))


def require_registry_plan(registry: TypeRegistry, plan_digest: str) -> None:
    """Ensure the registry was created under the currently approved plan."""
    if not approval_matches_digest(registry.plan_digest, plan_digest):
        raise PlanValidationError("type registry was created for a different plan digest")


def approval_matches_digest(expected: str, supplied: str) -> bool:
    """Compare plan digests using the existing canonical approval rule."""

    class _DigestOnly:
        digest = expected

    return approval_matches(cast(Any, _DigestOnly()), supplied)
