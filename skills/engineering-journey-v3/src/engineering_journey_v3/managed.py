"""Managed subprocess supervision with user-visible relays at bounded intervals."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from engineering_journey_v3.progress import ProgressError, latest_status

MAX_RELAY_INTERVAL_SECONDS = 15.0


class ManagedProcessError(ValueError):
    """Managed orchestration settings or command are invalid."""


def run_managed(
    command: Sequence[str],
    *,
    progress_path: Path,
    output: TextIO,
    relay_interval: float = MAX_RELAY_INTERVAL_SECONDS,
    popen: Callable[[Sequence[str]], subprocess.Popen[bytes]] = subprocess.Popen,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run long work as a child and relay status even when progress is unchanged.

    This foreground supervisor owns a managed background child. It emits an immediate
    launch update, then a natural-language relay no farther than ``relay_interval`` apart.
    Reading the progress file more frequently is intentionally avoided: internal polling
    is not presented as user-visible progress.
    """
    if not command or not 0 < relay_interval <= MAX_RELAY_INTERVAL_SECONDS:
        raise ManagedProcessError("command is required and relay interval must be >0 and <=15s")
    process = popen(command)
    print(f"Engineering Journey started managed process {process.pid}", file=output, flush=True)
    last_relay = monotonic()
    try:
        while process.poll() is None:
            now = monotonic()
            remaining = relay_interval - (now - last_relay)
            if remaining > 0:
                sleep(remaining)
            try:
                status = latest_status(progress_path)
            except ProgressError:
                status = (
                    "Engineering Journey is running; waiting for its first durable progress event"
                )
            print(status, file=output, flush=True)
            last_relay = monotonic()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
        print("Engineering Journey interrupted; child process terminated", file=output, flush=True)
        return 130
    return_code = process.wait()
    try:
        status = latest_status(progress_path)
    except ProgressError:
        status = "Engineering Journey stopped without a durable progress event"
    print(f"{status}; process exit {return_code}", file=output, flush=True)
    return return_code
