"""Consent, identity confirmation, plan display, and resume review workflows."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from engineering_journey_v3.auth import AuthBoundary, AuthenticationError, GitHubIdentity
from engineering_journey_v3.plan import Plan, approval_matches

Input = Callable[[str], str]


class ConsentCancelled(RuntimeError):
    """Raised when the safe default or an explicit cancellation ends the workflow."""


class ApprovalError(RuntimeError):
    """Raised when approval is absent or does not bind to the displayed plan."""


def _ask(input_fn: Input, prompt: str) -> str:
    try:
        return input_fn(prompt).strip().casefold()
    except (EOFError, KeyboardInterrupt) as error:
        raise ConsentCancelled("cancelled; no work was started") from error


def _read_exact(input_fn: Input, prompt: str) -> str:
    """Read confirmation without normalizing user input or weakening exact consent."""
    try:
        return input_fn(prompt)
    except (EOFError, KeyboardInterrupt) as error:
        raise ConsentCancelled("cancelled; no work was started") from error


def confirm_identity(identity: GitHubIdentity, *, input_fn: Input, output: TextIO) -> str:
    """Display and explicitly confirm one identity before returning its login."""
    print(f"GitHub identity to use: {identity.login}", file=output)
    answer = _read_exact(input_fn, f"Type the exact login '{identity.login}' to confirm: ")
    if answer != identity.login:
        raise ConsentCancelled("identity was not confirmed; no plan was constructed")
    return identity.login


def choose_identity(*, auth: AuthBoundary, input_fn: Input, output: TextIO) -> str:
    """Offer use/switch/cancel, with cancel as the default, then confirm the result."""
    current = auth.detect_identity()
    if current is None:
        print("Detected GitHub session: none", file=output)
        choice = _ask(input_fn, "[a] Authenticate with browser/device flow; [c] Cancel (default): ")
        if choice != "a":
            raise ConsentCancelled("cancelled; no work was started")
        selected = auth.authenticate_different()
        print(f"Authenticated GitHub login: {selected.login}", file=output)
        return confirm_identity(selected, input_fn=input_fn, output=output)

    print(f"Detected GitHub session: {current.login}", file=output)
    choice = _ask(
        input_fn,
        "[u] Use displayed account; [a] Authenticate a different account; [c] Cancel (default): ",
    )
    if choice == "u":
        return confirm_identity(current, input_fn=input_fn, output=output)
    if choice == "a":
        selected = auth.authenticate_different()
        if selected.login.casefold() == current.login.casefold():
            raise AuthenticationError(
                "authenticate-different returned the displayed account; identity switch stopped"
            )
        print(f"Authenticated new GitHub login: {selected.login}", file=output)
        return confirm_identity(selected, input_fn=input_fn, output=output)
    raise ConsentCancelled("cancelled; no work was started")


def render_plan(plan: Plan) -> str:
    """Render every approval-bound plan field deterministically."""
    lines = [
        "Engineering Journey v3 immutable plan",
        f"identity: {plan.identity}",
        f"UTC interval: {plan.start_utc} through {plan.end_utc}",
        f"repository policy: {plan.repository_policy}",
        f"repository snapshot digest: {plan.repository_snapshot_digest}",
        f"source semantics: {plan.source_semantics_version}",
        f"mode: {plan.mode}",
        f"stages: {', '.join(plan.stages)}",
        f"private data: {plan.private_data_behavior}",
        "outputs:",
        *(f"  - {path}" for path in plan.outputs),
        f"run id: {plan.run_id}",
        f"plan digest: {plan.digest}",
    ]
    return "\n".join(lines)


def require_approval(plan: Plan, supplied_digest: str | None) -> None:
    """Fail closed unless approval is bound to the exact displayed plan."""
    if supplied_digest is None:
        raise ApprovalError("stopped by default; approve only with this plan's exact digest")
    if not approval_matches(plan, supplied_digest):
        raise ApprovalError("approval digest does not match the displayed immutable plan")


@dataclass(frozen=True, slots=True)
class ResumeState:
    """Minimum saved state that must be redisplayed before a resume is approved."""

    plan: Plan
    stage: str
    progress: str

    @classmethod
    def from_json(cls, document: str) -> ResumeState:
        value = json.loads(document)
        if not isinstance(value, dict) or set(value) != {"plan", "stage", "progress"}:
            raise ValueError("resume state fields do not match the resume schema")
        plan_value = value["plan"]
        if not isinstance(plan_value, dict):
            raise ValueError("resume state plan must be an object")
        stage = value["stage"]
        progress = value["progress"]
        if not isinstance(stage, str) or not stage or not isinstance(progress, str) or not progress:
            raise ValueError("resume stage and progress must be non-empty strings")
        return cls(plan=Plan.from_dict(plan_value), stage=stage, progress=progress)


def render_resume(state: ResumeState) -> str:
    """Render saved identity/range/snapshot/stage/progress and the bound plan."""
    return "\n".join(
        (
            "Engineering Journey v3 resume review",
            render_plan(state.plan),
            f"saved stage: {state.stage}",
            f"saved progress: {state.progress}",
        )
    )
