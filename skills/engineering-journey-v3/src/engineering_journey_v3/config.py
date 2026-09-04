"""Typed, local-only runtime configuration and secure path helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


class UnsafePathError(ValueError):
    """Raised when a sensitive path is unsafe to create or use."""


def default_state_directory() -> Path:
    """Return the per-user state directory without creating it."""
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return root / "engineering-journey-v3"


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Configuration available before identity and plan construction."""

    state_directory: Path
    schema_version: str = "1"

    @classmethod
    def from_environment(cls) -> RuntimeConfig:
        """Load non-secret local configuration from the process environment."""
        configured = os.environ.get("ENGINEERING_JOURNEY_STATE_DIR")
        state_directory = Path(configured).expanduser() if configured else default_state_directory()
        return cls(state_directory=state_directory)


def ensure_private_directory(path: Path) -> Path:
    """Create or tighten a private directory, rejecting symlink endpoints."""
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise UnsafePathError(f"sensitive directory must not be a symlink: {expanded}")
    expanded.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    if expanded.is_symlink() or not expanded.is_dir():
        raise UnsafePathError(f"sensitive path is not a directory: {expanded}")
    expanded.chmod(_PRIVATE_DIRECTORY_MODE)
    return expanded


def create_private_file(path: Path) -> int:
    """Atomically create a new private file and return its descriptor.

    The caller owns the descriptor and must close it. Existing paths and symlink
    endpoints fail closed through ``O_EXCL`` and ``O_NOFOLLOW`` where available.
    """
    parent = ensure_private_directory(path.expanduser().parent)
    target = parent / path.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(target, flags, _PRIVATE_FILE_MODE)
