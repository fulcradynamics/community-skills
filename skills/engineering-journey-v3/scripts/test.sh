#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v uv >/dev/null 2>&1; then
  printf 'error: uv is required; install from https://docs.astral.sh/uv/\n' >&2
  exit 2
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/engineering-journey-v3-uv}"

uv sync --frozen --group dev
uv run --frozen --group dev ruff format --check src tests
uv run --frozen --group dev ruff check src tests
uv run --frozen --group dev mypy
uv run --frozen --group dev pytest
bash scripts/verify_install.sh
