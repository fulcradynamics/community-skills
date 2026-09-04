from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from engineering_journey_v3.config import (
    RuntimeConfig,
    UnsafePathError,
    create_private_file,
    ensure_private_directory,
)


def permissions(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_environment_config_is_typed_and_does_not_create_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "configured"
    monkeypatch.setenv("ENGINEERING_JOURNEY_STATE_DIR", str(target))
    config = RuntimeConfig.from_environment()
    assert config.state_directory == target
    assert config.schema_version == "1"
    assert not target.exists()


def test_private_directory_is_created_and_existing_permissions_are_tightened(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state"
    target.mkdir(mode=0o755)
    result = ensure_private_directory(target)
    assert result == target
    assert permissions(target) == 0o700


def test_sensitive_directory_rejects_symlink(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    link = tmp_path / "state"
    link.symlink_to(destination, target_is_directory=True)
    with pytest.raises(UnsafePathError, match="symlink"):
        ensure_private_directory(link)


def test_private_file_is_new_and_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "state" / "checkpoint.json"
    descriptor = create_private_file(target)
    try:
        os.write(descriptor, b"{}\n")
    finally:
        os.close(descriptor)
    assert permissions(target.parent) == 0o700
    assert permissions(target) == 0o600
    with pytest.raises(FileExistsError):
        create_private_file(target)
