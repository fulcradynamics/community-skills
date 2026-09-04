"""Fulcra SDK browser/device authentication with private credential persistence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from fulcra_api.core import FulcraAPI  # type: ignore[import-untyped]

from engineering_journey_v3.config import ensure_private_directory
from engineering_journey_v3.fulcra_gateway import FulcraAuthError


def authenticate(credentials_path: Path | None = None) -> Path:
    """Run the SDK device flow and save credentials owner-only."""
    path = credentials_path or Path.home() / ".config/fulcra/credentials.json"
    client = FulcraAPI()
    try:
        client.authorize()
    except Exception as error:
        raise FulcraAuthError("Fulcra SDK authentication failed") from error
    credentials = cast(Any, client.fulcra_credentials)
    if credentials is None:
        raise FulcraAuthError("Fulcra SDK authentication returned no credentials")
    parent = ensure_private_directory(path.expanduser().parent)
    target = parent / path.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    try:
        os.write(descriptor, credentials.to_json().encode("utf-8"))
    finally:
        os.close(descriptor)
    target.chmod(0o600)
    return target
