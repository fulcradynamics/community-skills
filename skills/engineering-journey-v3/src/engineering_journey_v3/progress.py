"""Strict durable JSONL progress and deterministic relay status rendering."""

from __future__ import annotations

import json
import math
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from engineering_journey_v3.config import ensure_private_directory
from engineering_journey_v3.plan import normalize_utc

PROGRESS_SCHEMA_VERSION = "engineering-journey-v3-progress/v1"


class ProgressError(ValueError):
    """A progress event or stream violates the durable progress contract."""


def _non_negative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProgressError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class WorkCounters:
    repositories_completed: int = 0
    pages_completed: int = 0
    api_calls: int = 0
    writes_attempted: int = 0
    writes_durable: int = 0
    deduplicated: int = 0
    retries: int = 0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _non_negative(getattr(self, name), name)
        if self.writes_durable > self.writes_attempted:
            raise ProgressError("durable writes cannot exceed attempted writes")

    def as_dict(self) -> dict[str, int]:
        return {name: cast(int, getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: object) -> WorkCounters:
        expected = set(cls.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) != expected:
            raise ProgressError("progress counters do not match the schema")
        return cls(**{name: _non_negative(value[name], name) for name in expected})


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    run_id: str
    invocation_id: str
    event: str
    stage: str
    timestamp_utc: str
    elapsed_seconds: float
    current_operation: str
    counters: WorkCounters
    repository_current: str | None = None
    repository_index: int = 0
    repository_total: int = 0
    page_current: int = 0
    quota_state: Mapping[str, Any] = field(default_factory=dict)
    heartbeat: bool = False
    terminal_reconciliation: Mapping[str, int] | None = None
    schema_version: str = PROGRESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROGRESS_SCHEMA_VERSION:
            raise ProgressError("unsupported progress schema version")
        for name in (
            "run_id",
            "invocation_id",
            "event",
            "stage",
            "timestamp_utc",
            "current_operation",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ProgressError(f"progress {name} must be a canonical non-empty string")
        try:
            uuid.UUID(self.run_id)
            uuid.UUID(self.invocation_id)
        except ValueError as error:
            raise ProgressError("progress run/invocation ID is invalid") from error
        if normalize_utc(self.timestamp_utc) != self.timestamp_utc:
            raise ProgressError("progress timestamp must be canonical UTC")
        if (
            isinstance(self.elapsed_seconds, bool)
            or not isinstance(self.elapsed_seconds, int | float)
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ProgressError("progress elapsed time must be non-negative")
        if not isinstance(self.heartbeat, bool):
            raise ProgressError("progress heartbeat must be boolean")
        for name in ("repository_index", "repository_total", "page_current"):
            _non_negative(getattr(self, name), name)
        if self.repository_index > self.repository_total:
            raise ProgressError("repository index cannot exceed repository total")
        if self.repository_current is not None and (
            not self.repository_current
            or self.repository_current != self.repository_current.strip()
            or self.repository_index == 0
        ):
            raise ProgressError("current repository must be canonical when present")
        if self.page_current and self.repository_current is None:
            raise ProgressError("a current page requires a current repository")
        if not isinstance(self.quota_state, Mapping):
            raise ProgressError("quota state must be an object")
        if self.event == "terminal":
            if self.terminal_reconciliation is None:
                raise ProgressError("terminal progress requires reconciliation counts")
            required = {"received", "durable", "deduplicated", "failed"}
            if set(self.terminal_reconciliation) != required:
                raise ProgressError("terminal reconciliation fields do not match the schema")
            for name, value in self.terminal_reconciliation.items():
                _non_negative(value, f"terminal {name}")
            values = self.terminal_reconciliation
            if values["received"] != values["durable"] + values["deduplicated"] + values["failed"]:
                raise ProgressError("terminal reconciliation counts do not balance")
            if (
                values["received"] != self.counters.writes_attempted
                or values["durable"] != self.counters.writes_durable
                or values["deduplicated"] != self.counters.deduplicated
            ):
                raise ProgressError("terminal reconciliation disagrees with progress counters")
        elif self.terminal_reconciliation is not None:
            raise ProgressError("only terminal progress may contain reconciliation")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "invocation_id": self.invocation_id,
            "event": self.event,
            "stage": self.stage,
            "timestamp_utc": self.timestamp_utc,
            "elapsed_seconds": self.elapsed_seconds,
            "repository": {
                "current": self.repository_current,
                "index": self.repository_index,
                "total": self.repository_total,
            },
            "page": self.page_current,
            "counters": self.counters.as_dict(),
            "current_operation": self.current_operation,
            "quota_state": dict(self.quota_state),
            "heartbeat": self.heartbeat,
            "terminal_reconciliation": (
                dict(self.terminal_reconciliation)
                if self.terminal_reconciliation is not None
                else None
            ),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, document: str) -> ProgressEvent:
        try:
            value = json.loads(document)
        except json.JSONDecodeError as error:
            raise ProgressError("progress line is not valid JSON") from error
        expected = {
            "schema_version",
            "run_id",
            "invocation_id",
            "event",
            "stage",
            "timestamp_utc",
            "elapsed_seconds",
            "repository",
            "page",
            "counters",
            "current_operation",
            "quota_state",
            "heartbeat",
            "terminal_reconciliation",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ProgressError("progress fields do not match the schema")
        repository = value["repository"]
        if not isinstance(repository, dict) or set(repository) != {"current", "index", "total"}:
            raise ProgressError("progress repository fields do not match the schema")
        scalar_strings = (
            "schema_version",
            "run_id",
            "invocation_id",
            "event",
            "stage",
            "timestamp_utc",
            "current_operation",
        )
        if not all(isinstance(value[name], str) for name in scalar_strings):
            raise ProgressError("progress string fields are invalid")
        if not isinstance(value["elapsed_seconds"], int | float) or not isinstance(
            value["heartbeat"], bool
        ):
            raise ProgressError("progress elapsed/heartbeat fields are invalid")
        if repository["current"] is not None and not isinstance(repository["current"], str):
            raise ProgressError("progress current repository is invalid")
        terminal = value["terminal_reconciliation"]
        if terminal is not None and not isinstance(terminal, dict):
            raise ProgressError("terminal reconciliation must be an object or null")
        if not isinstance(value["quota_state"], dict):
            raise ProgressError("quota state must be an object")
        return cls(
            schema_version=value["schema_version"],
            run_id=value["run_id"],
            invocation_id=value["invocation_id"],
            event=value["event"],
            stage=value["stage"],
            timestamp_utc=value["timestamp_utc"],
            elapsed_seconds=float(value["elapsed_seconds"]),
            repository_current=repository["current"],
            repository_index=_non_negative(repository["index"], "repository index"),
            repository_total=_non_negative(repository["total"], "repository total"),
            page_current=_non_negative(value["page"], "page"),
            counters=WorkCounters.from_dict(value["counters"]),
            current_operation=value["current_operation"],
            quota_state=value["quota_state"],
            heartbeat=value["heartbeat"],
            terminal_reconciliation=cast(dict[str, int] | None, terminal),
        )


class ProgressStream:
    """Owner-only append/fsync JSONL whose latest complete line survives hard kill."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        ensure_private_directory(self.path.parent)

    def append(self, event: ProgressEvent) -> None:
        payload = (event.to_json() + "\n").encode("utf-8")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            written = os.write(descriptor, payload)
            if written != len(payload):
                raise OSError("short progress stream write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def latest(self) -> ProgressEvent:
        try:
            document = self.path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ProgressError("progress stream does not exist") from error
        lines = document.splitlines()
        if document and not document.endswith("\n"):
            lines = lines[:-1]
        if not lines:
            raise ProgressError("progress stream is empty")
        # A hard kill can leave only the final line partial; previous complete lines remain usable.
        for line in reversed(lines):
            try:
                return ProgressEvent.from_json(line)
            except ProgressError:
                continue
        raise ProgressError("progress stream has no complete valid event")


def render_status(event: ProgressEvent) -> str:
    """Render one concise, deterministic natural-language relay line."""
    repository = (
        f"repository {event.repository_index}/{event.repository_total} {event.repository_current}"
        if event.repository_current is not None
        else f"repositories {event.counters.repositories_completed}/{event.repository_total}"
    )
    unchanged = "; heartbeat, no change" if event.heartbeat else ""
    terminal = "; reconciled" if event.terminal_reconciliation is not None else ""
    return (
        f"Engineering Journey {event.stage}: {repository}, page {event.page_current}; "
        f"API {event.counters.api_calls}, durable {event.counters.writes_durable}, "
        f"dedup {event.counters.deduplicated}, retries {event.counters.retries}; "
        f"{event.current_operation}{unchanged}{terminal}"
    )


def latest_status(path: Path) -> str:
    return render_status(ProgressStream(path).latest())
