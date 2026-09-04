from __future__ import annotations

import subprocess
import sys

import pytest

from engineering_journey_v3 import __version__
from engineering_journey_v3.cli import main


def test_no_arguments_is_offline_and_successful(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert captured.err == ""


def test_module_entrypoint_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "engineering_journey_v3", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "engineering-journey" in result.stdout
    assert "usage:" in result.stdout
    assert result.stderr == ""


def test_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "engineering_journey_v3", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"engineering-journey {__version__}"
