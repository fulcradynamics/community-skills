#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
project_root="$PWD"

work="$(mktemp -d)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

uv build --wheel --out-dir "$work/dist"
uv venv --python 3.11 "$work/venv"
uv pip install --python "$work/venv/bin/python" "$work"/dist/*.whl
(
  cd "$work"
  "$work/venv/bin/engineering-journey" --help
  "$work/venv/bin/engineering-journey" journey --help
  "$work/venv/bin/python" -m engineering_journey_v3 --version

  # Prove that the actual wheel carries and installs the agent skill without
  # consulting the checkout.
  "$work/venv/bin/engineering-journey" install-skill --destination "$work/installed-skill"
  test -s "$work/installed-skill/SKILL.md"
  cmp "$project_root/SKILL.md" "$work/installed-skill/SKILL.md"
  grep -q '^name: engineering-journey-v3$' "$work/installed-skill/SKILL.md"
  if "$work/venv/bin/engineering-journey" install-skill \
    --destination "$work/installed-skill" >/dev/null 2>&1; then
    printf 'error: install-skill overwrote an existing destination\n' >&2
    exit 1
  fi

  # Exercise first-use account switching through the installed console script.
  # This fake gh is a process boundary, not an injected Python test double.
  mkdir "$work/mock-bin"
  printf '%s\n' \
    '#!/usr/bin/env sh' \
    'if [ "$1 $2" = "api user" ]; then' \
    '  if [ -f "$MOCK_GH_SWITCHED" ]; then printf "%s\\n" fresh-account; else printf "%s\\n" old-account; fi' \
    '  exit 0' \
    'fi' \
    'if [ "$1 $2" = "auth login" ]; then : > "$MOCK_GH_SWITCHED"; exit 0; fi' \
    'exit 2' > "$work/mock-bin/gh"
  chmod +x "$work/mock-bin/gh"
  switch_output="$(printf 'a\nfresh-account\n' | env \
    PATH="$work/mock-bin:$PATH" MOCK_GH_SWITCHED="$work/switched" \
    "$work/venv/bin/engineering-journey" plan \
      --start 2025-01-01T00:00:00Z --end 2026-01-01T00:00:00Z)"
  printf '%s\n' "$switch_output"
  grep -q 'Detected GitHub session: old-account' <<<"$switch_output"
  grep -q 'Authenticated new GitHub login: fresh-account' <<<"$switch_output"
  grep -q 'identity: fresh-account' <<<"$switch_output"
  grep -q 'STOPPED: stopped by default' <<<"$switch_output"
)
