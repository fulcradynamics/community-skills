from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "engineering_journey_v3"
FIXTURES = ROOT / "tests" / "fixtures"


def test_runtime_has_no_provider_or_harness_dependency() -> None:
    forbidden_imports = re.compile(
        r"^\s*(?:from|import)\s+(?:harness|anthropic|openai|google\.genai)\b", re.M
    )
    for source in PACKAGE.glob("*.py"):
        assert not forbidden_imports.search(source.read_text(encoding="utf-8")), source


def test_project_has_only_approved_sdk_and_no_provider_key_check() -> None:
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    assert project["project"]["dependencies"] == ["fulcra-api==0.1.40"]
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py"))
    assert not re.search(r"(?:OPENAI|ANTHROPIC|GEMINI|MODEL)_API_KEY", runtime)


def test_all_committed_json_fixtures_declare_synthetic_origin() -> None:
    fixtures = list(FIXTURES.glob("*.json"))
    assert fixtures, "at least one scrubbed fixture is required"
    for fixture in fixtures:
        document = json.loads(fixture.read_text(encoding="utf-8"))
        assert document["fixture_origin"] == "synthetic"
        assert document["contains_private_repository_data"] is False
        assert "token" not in fixture.read_text(encoding="utf-8").casefold()


def test_fixture_policy_forbids_real_identity_and_private_evidence() -> None:
    policy = (FIXTURES / "README.md").read_text(encoding="utf-8")
    for required_rule in ("synthetic", "Never copy", "private", "credentials"):
        assert required_rule in policy
