from __future__ import annotations

import io
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from engineering_journey_v3.auth import AuthenticationError, GitHubCLIAuth, GitHubIdentity
from engineering_journey_v3.cli import main
from engineering_journey_v3.plan import PlanValidationError, approval_matches, build_plan
from engineering_journey_v3.workflow import (
    ConsentCancelled,
    ResumeState,
    choose_identity,
    render_resume,
)

START = "2025-01-02T03:04:05Z"
END = "2026-01-02T03:04:05Z"


class FakeAuth:
    def __init__(self, current: str | None, switched: str = "account-b") -> None:
        self.current = GitHubIdentity(current) if current else None
        self.switched = GitHubIdentity(switched)
        self.switch_calls = 0

    def detect_identity(self) -> GitHubIdentity | None:
        return self.current

    def authenticate_different(self) -> GitHubIdentity:
        self.switch_calls += 1
        return self.switched


def answers(*values: str):  # type: ignore[no-untyped-def]
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_use_current_account_requires_exact_post_selection_confirmation() -> None:
    output = io.StringIO()
    identity = choose_identity(
        auth=FakeAuth("account-a"), input_fn=answers("u", "account-a"), output=output
    )
    assert identity == "account-a"
    assert "Detected GitHub session: account-a" in output.getvalue()
    assert "GitHub identity to use: account-a" in output.getvalue()


@pytest.mark.parametrize("inexact", ["Account-A", "account-a ", " account-a"])
def test_identity_confirmation_rejects_normalized_but_inexact_login(inexact: str) -> None:
    with pytest.raises(ConsentCancelled, match="not confirmed"):
        choose_identity(
            auth=FakeAuth("account-a"),
            input_fn=answers("u", inexact),
            output=io.StringIO(),
        )


def test_account_a_can_be_rejected_and_account_b_confirmed_after_browser_boundary() -> None:
    auth = FakeAuth("account-a", "account-b")
    output = io.StringIO()
    identity = choose_identity(auth=auth, input_fn=answers("a", "account-b"), output=output)
    assert identity == "account-b"
    assert auth.switch_calls == 1
    assert "Authenticated new GitHub login: account-b" in output.getvalue()
    assert output.getvalue().index("account-b") < output.getvalue().index("identity to use")


def test_authenticate_different_must_actually_change_login() -> None:
    with pytest.raises(AuthenticationError, match="switch stopped"):
        choose_identity(
            auth=FakeAuth("account-a", "account-a"),
            input_fn=answers("a"),
            output=io.StringIO(),
        )


@pytest.mark.parametrize("choice", ["", "c", "unexpected"])
def test_cancel_is_the_default_and_never_switches(choice: str) -> None:
    auth = FakeAuth("account-a")
    with pytest.raises(ConsentCancelled, match="cancelled"):
        choose_identity(auth=auth, input_fn=answers(choice), output=io.StringIO())
    assert auth.switch_calls == 0


def test_no_existing_session_can_authenticate_then_confirm() -> None:
    auth = FakeAuth(None, "account-b")
    output = io.StringIO()
    assert (
        choose_identity(auth=auth, input_fn=answers("a", "account-b"), output=output) == "account-b"
    )
    assert "Detected GitHub session: none" in output.getvalue()


def test_production_auth_uses_visible_supported_web_flow_then_redetects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, options))
        if command[1:3] == ["auth", "login"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "account-b\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert GitHubCLIAuth().authenticate_different().login == "account-b"
    assert calls[0][0] == ["gh", "auth", "login", "--web", "--git-protocol", "https"]
    assert "capture_output" not in calls[0][1]
    assert calls[1][0] == ["gh", "api", "user", "--jq", ".login"]
    assert calls[1][1]["capture_output"] is True


def test_plan_is_canonical_and_bound_to_every_immutable_scope_dimension() -> None:
    plan = build_plan(
        identity="account-b",
        start_utc=START,
        end_utc=END,
        repository_snapshot_digest="sha256:snapshot-one",
    )
    assert approval_matches(plan, plan.digest)
    assert (
        plan.run_id
        == build_plan(
            identity="account-b",
            start_utc=START,
            end_utc=END,
            repository_snapshot_digest="sha256:snapshot-one",
        ).run_id
    )

    variants = (
        replace(plan, identity="account-c"),
        replace(plan, start_utc="2025-01-02T03:04:06Z"),
        replace(plan, end_utc="2026-01-02T03:04:06Z"),
        replace(plan, repository_policy="public-only"),
        replace(plan, repository_snapshot_digest="sha256:snapshot-two"),
        replace(plan, mode="rewrite"),
        replace(plan, outputs=("/different/narrative.md", "/different/sources.md")),
        replace(plan, source_semantics_version="github-activity/v2"),
    )
    for modified in variants:
        assert modified.digest != plan.digest
        assert modified.run_id != plan.run_id
        assert not approval_matches(modified, plan.digest)


def test_plan_rejects_non_utc_or_reversed_bounds() -> None:
    with pytest.raises(PlanValidationError, match="ending in Z"):
        build_plan(identity="account-a", start_utc=START.removesuffix("Z"), end_utc=END)
    with pytest.raises(PlanValidationError, match="earlier"):
        build_plan(identity="account-a", start_utc=END, end_utc=START)


def test_interactive_cli_displays_plan_and_stops_without_approval() -> None:
    output = io.StringIO()
    result = main(
        ["plan", "--start", START, "--end", END],
        auth=FakeAuth("account-a"),
        input_fn=answers("u", "account-a"),
        output=output,
    )
    rendered = output.getvalue()
    assert result == 0
    assert rendered.index("identity to use") < rendered.index("immutable plan")
    for required in (
        f"UTC interval: {START} through {END}",
        "repository policy:",
        "mode: write",
        "stages:",
        "private data:",
        "outputs:",
        "plan digest:",
        "STOPPED: stopped by default",
    ):
        assert required in rendered


def test_interactive_cli_accepts_only_the_unchanged_digest() -> None:
    plan = build_plan(identity="account-a", start_utc=START, end_utc=END)
    common = ["plan", "--start", START, "--end", END, "--approve-plan"]

    approved = io.StringIO()
    assert (
        main(
            [*common, plan.digest],
            auth=FakeAuth("account-a"),
            input_fn=answers("u", "account-a"),
            output=approved,
        )
        == 0
    )
    assert "APPROVED" in approved.getvalue()

    tampered = io.StringIO()
    assert (
        main(
            [*common, plan.digest, "--end", "2026-01-02T03:04:06Z"],
            auth=FakeAuth("account-a"),
            input_fn=answers("u", "account-a"),
            output=tampered,
        )
        == 2
    )
    assert "does not match" in tampered.getvalue()


def test_noninteractive_prints_complete_candidate_plan_and_stops_even_with_approval() -> None:
    plan = build_plan(identity="account-a", start_utc=START, end_utc=END)
    output = io.StringIO()
    result = main(
        [
            "plan",
            "--start",
            START,
            "--end",
            END,
            "--non-interactive",
            "--approve-plan",
            plan.digest,
        ],
        auth=FakeAuth("account-a"),
        output=output,
    )
    assert result == 2
    assert "UNCONFIRMED" in output.getvalue()
    assert "immutable plan" in output.getvalue()
    assert "STOPPED" in output.getvalue()
    assert "APPROVED" not in output.getvalue()


def test_resume_redisplays_saved_scope_stage_progress_and_requires_bound_approval(
    tmp_path: Path,
) -> None:
    plan = build_plan(
        identity="account-b",
        start_utc=START,
        end_utc=END,
        mode="resume",
        repository_snapshot_digest="sha256:frozen-repositories",
    )
    state = ResumeState(plan=plan, stage="github-ingestion", progress="repository 3 of 8")
    rendered = render_resume(state)
    for expected in (
        "identity: account-b",
        f"UTC interval: {START} through {END}",
        "sha256:frozen-repositories",
        "saved stage: github-ingestion",
        "saved progress: repository 3 of 8",
    ):
        assert expected in rendered

    state_path = tmp_path / "resume.json"
    state_path.write_text(
        json.dumps({"plan": plan.as_dict(), "stage": state.stage, "progress": state.progress}),
        encoding="utf-8",
    )
    stopped = io.StringIO()
    assert main(["resume", "--state", str(state_path)], output=stopped) == 0
    assert "STOPPED" in stopped.getvalue()

    approved = io.StringIO()
    assert (
        main(
            ["resume", "--state", str(state_path), "--approve-plan", plan.digest],
            output=approved,
        )
        == 0
    )
    assert "APPROVED" in approved.getvalue()


def test_strict_saved_plan_rejects_added_tampering() -> None:
    plan = build_plan(identity="account-a", start_utc=START, end_utc=END)
    payload = plan.as_dict()
    payload["unapproved"] = True
    with pytest.raises(PlanValidationError, match="schema"):
        type(plan).from_dict(payload)
