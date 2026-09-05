"""
Tests for scripts/scaffold_control_harness.py.

Real, runnable tests: invoke the actual script (both --dry-run and a
real run) against a temp output directory and assert on the real files
it produces -- including, critically, that every file/directory
SKILL.md's "Required portable control-harness contract" documents as
required is actually generated. This test suite didn't exist before;
its absence is exactly why that contract and the actual scaffold output
drifted apart undetected (see the "Required portable control-harness
contract" list in SKILL.md vs. what --dry-run/real runs below assert).

Run with:
    python -m pytest scripts/tests/test_scaffold_control_harness.py
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SCRIPT_DIR / "scaffold_control_harness.py"

# The exact list from SKILL.md's "Required portable control-harness
# contract" section, translated from the doc's directory-implied names
# to the real relative file paths this scaffold should produce.
# `knowledge/` itself is a directory requirement -- checked separately.
REQUIRED_FILES = [
    "spec.md",
    "decisions.md",
    "dashboard-decision.md",
    "roles/manifest.md",
    "roles/generator.md",
    "roles/evaluator.md",
    "schemas/message.md",
    "schemas/verdict.md",
    "schemas/decision-request.md",
    "coordinator/milestones.md",
    "coordinator/policy.md",
    "coordinator/unattended-recovery.md",
    "coordinator/scheduled-operation.md",
    "coordinator/bootstrap.py",
    "coordinator/run_milestone.py",
    "RUNBOOK.md",
    "HARNESS_GOVERNANCE.md",
    "bootstrap.sh",
    "doctor.sh",
    "README.md",
]


def _run_scaffold(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "control"
    result = _run_scaffold(
        "--project-name", "Test Project", "--output-dir", str(target), "--dry-run"
    )
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    assert "Would copy" in result.stdout


def test_real_run_generates_every_documented_required_file(tmp_path: Path) -> None:
    """The core regression test: every file SKILL.md's control-harness
    contract documents as required must actually exist after a real
    (non-dry-run) scaffold -- not just the 8 files the original
    implementation happened to generate."""
    target = tmp_path / "control"
    result = _run_scaffold(
        "--project-name", "Test Project", "--output-dir", str(target)
    )
    assert result.returncode == 0, result.stderr

    missing = [f for f in REQUIRED_FILES if not (target / f).is_file()]
    assert not missing, f"Missing required control-harness files: {missing}"

    assert (target / "knowledge").is_dir(), "knowledge/ directory must exist"

    repository = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    assert repository.returncode == 0, repository.stderr
    assert repository.stdout.strip() == "true"
    initial_commit = subprocess.run(
        ["git", "-C", str(target), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
    )
    assert initial_commit.returncode == 0, initial_commit.stderr
    assert initial_commit.stdout.strip() == "chore: initialize control harness"


def test_project_name_placeholder_is_hydrated(tmp_path: Path) -> None:
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Acme Widget Tracker", "--output-dir", str(target))
    runbook = (target / "RUNBOOK.md").read_text()
    assert "Acme Widget Tracker" in runbook
    assert "{{PROJECT_NAME}}" not in runbook


def test_shell_scripts_are_executable(tmp_path: Path) -> None:
    """bootstrap.sh and doctor.sh are meant to be run directly
    (./bootstrap.sh, ./doctor.sh per RUNBOOK.md) -- confirm the scaffold
    itself sets the executable bit rather than requiring a manual
    chmod +x the first time someone tries them."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    for name in ("bootstrap.sh", "doctor.sh"):
        mode = (target / name).stat().st_mode
        assert mode & stat.S_IXUSR, f"{name} is not executable"


def test_refuses_to_overwrite_non_empty_directory(tmp_path: Path) -> None:
    target = tmp_path / "control"
    target.mkdir()
    (target / "existing.txt").write_text("pre-existing content")

    result = _run_scaffold(
        "--project-name", "Test Project", "--output-dir", str(target)
    )
    assert result.returncode != 0
    assert "Refusing to overwrite" in result.stderr
    # Confirm nothing was written into the non-empty target.
    assert list(target.iterdir()) == [target / "existing.txt"]


def test_readme_does_not_reference_nonexistent_scripts(tmp_path: Path) -> None:
    """Regression test for a real bug: the README template used to tell
    users to run `python coordinator/bootstrap.py` directly as the
    documented quick-start, while also (correctly) telling them to run
    ./bootstrap.sh — and coordinator/bootstrap.py now genuinely exists,
    so this just confirms the documented commands in README.md actually
    resolve to real files in the same scaffold output."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    readme = (target / "README.md").read_text()

    import re

    for match in re.finditer(r"`?(coordinator/[a-zA-Z_.]+\.(?:py|sh))`?", readme):
        referenced = match.group(1)
        assert (target / referenced).is_file(), (
            f"README.md references {referenced}, which was not generated"
        )
    for match in re.finditer(r"\./([a-zA-Z_-]+\.sh)", readme):
        referenced = match.group(1)
        assert (target / referenced).is_file(), (
            f"README.md references ./{referenced}, which was not generated"
        )


def test_doctor_sh_fails_on_fresh_unfilled_scaffold(tmp_path: Path) -> None:
    """A freshly scaffolded harness has template placeholder content in
    spec.md and no HARNESS_GENERATOR_CMD/HARNESS_EVALUATOR_CMD set --
    doctor.sh should say so clearly (non-zero exit), not falsely claim
    readiness."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))

    env = os.environ.copy()
    env.pop("HARNESS_GENERATOR_CMD", None)
    env.pop("HARNESS_EVALUATOR_CMD", None)
    result = subprocess.run(
        ["bash", str(target / "doctor.sh")],
        cwd=target,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "problem(s) found" in result.stdout
    assert "dashboard decision is pending or invalid" in result.stdout
    decision_template = (target / "dashboard-decision.md").read_text()
    assert "choice: create_and_publish" in decision_template
    assert "publication: confirmed" in decision_template


def test_run_milestone_extracts_correct_milestone_context(tmp_path: Path) -> None:
    """Unit-test coordinator/run_milestone.py's context-extraction logic
    directly (imported, not shelled out) against a real milestones.md
    with two milestones, confirming M1's context doesn't leak into M2's
    and vice versa."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))

    milestones_path = target / "coordinator" / "milestones.md"
    milestones_path.write_text(
        "# Milestones\n\n"
        "## M1: First thing\n\n**Scope:** Do the first thing.\n\n"
        "## M2: Second thing\n\n**Scope:** Do the second thing.\n"
    )

    sys.path.insert(0, str(target / "coordinator"))
    try:
        # Reload semantics: import fresh each time since different tests
        # in this file may scaffold different target dirs with the same
        # module name.
        import importlib

        if "run_milestone" in sys.modules:
            importlib.reload(sys.modules["run_milestone"])
            run_milestone = sys.modules["run_milestone"]
        else:
            import run_milestone  # type: ignore
        run_milestone.CONTROL_HARNESS_ROOT = target

        m1_context = run_milestone.extract_milestone_context("M1")
        m2_context = run_milestone.extract_milestone_context("M2")

        assert "First thing" in m1_context
        assert "Second thing" not in m1_context
        assert "Second thing" in m2_context
        assert "First thing" not in m2_context

        with pytest.raises(run_milestone.MilestoneError):
            run_milestone.extract_milestone_context("M99")
    finally:
        sys.path.remove(str(target / "coordinator"))


def _load_run_milestone_module(target: Path):
    """Shared helper: import coordinator/run_milestone.py from a scaffolded
    target as a fresh module, matching the reload pattern used elsewhere
    in this file."""
    import importlib

    sys.path.insert(0, str(target / "coordinator"))
    try:
        if "run_milestone" in sys.modules:
            importlib.reload(sys.modules["run_milestone"])
            return sys.modules["run_milestone"]
        import run_milestone  # type: ignore

        return run_milestone
    finally:
        sys.path.remove(str(target / "coordinator"))


def test_is_mergeable_requires_test_runner_pass_when_declared(tmp_path: Path) -> None:
    """Regression test for a real reported bug: an Evaluator reporting
    'overall: PASS' alongside 'test_runner: FAIL' (or no test_runner line
    at all) must NOT be treated as merge-eligible when a test runner is
    declared -- this is exactly the unverified-milestone failure mode the
    Generator/Evaluator separation exists to prevent. parse_verdict()
    alone does not enforce this; callers must use is_mergeable()."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    run_milestone = _load_run_milestone_module(target)

    # overall PASS + test_runner PASS -> mergeable when a runner is declared.
    assert run_milestone.is_mergeable({"overall": "PASS", "test_runner": "PASS"}, test_runner_declared=True)

    # overall PASS + test_runner FAIL -> NOT mergeable when a runner is declared.
    assert not run_milestone.is_mergeable({"overall": "PASS", "test_runner": "FAIL"}, test_runner_declared=True)

    # overall PASS with NO test_runner line at all -> NOT mergeable when a runner is declared.
    assert not run_milestone.is_mergeable({"overall": "PASS"}, test_runner_declared=True)

    # overall FAIL is never mergeable regardless of test_runner.
    assert not run_milestone.is_mergeable({"overall": "FAIL", "test_runner": "PASS"}, test_runner_declared=True)

    # When no test runner is declared for the project, overall PASS alone is mergeable.
    assert run_milestone.is_mergeable({"overall": "PASS"}, test_runner_declared=False)


def test_dashboard_refresh_hook_runs_only_for_active_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    run_milestone = _load_run_milestone_module(target)
    calls: list[tuple[str | None, dict[str, str], str]] = []
    monkeypatch.setenv("HARNESS_DASHBOARD_REFRESH_CMD", "refresh-dashboard")
    monkeypatch.setattr(run_milestone, "adapter", lambda command, env, label: calls.append((command, env, label)))

    (target / "dashboard-decision.md").write_text("status: resolved\nchoice: create_and_publish\n")
    run_milestone.refresh_dashboard_if_active("demo", "M1", "PASS")
    assert calls == [("refresh-dashboard", {
        "HARNESS_TEAM": "demo",
        "HARNESS_MILESTONE": "M1",
        "HARNESS_OUTCOME": "PASS",
        "HARNESS_DASHBOARD_DECISION": str(target / "dashboard-decision.md"),
    }, "dashboard-refresh")]

    (target / "dashboard-decision.md").write_text("status: resolved\nchoice: defer\n")
    run_milestone.refresh_dashboard_if_active("demo", "M1", "FAIL")
    assert len(calls) == 1


def test_terminal_evaluator_failure_persists_escalation_then_refreshes_dashboard(tmp_path: Path) -> None:
    """The real coordinator path must cover evaluator/provider failures too."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    deliverable = tmp_path / "deliverable"
    deliverable.mkdir()
    git_env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    subprocess.run(["git", "init", "-b", "main", str(deliverable)], check=True, env=git_env, capture_output=True, text=True)
    (deliverable / "README.md").write_text("base\n")
    subprocess.run(["git", "-C", str(deliverable), "add", "."], check=True, env=git_env, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(deliverable), "commit", "-m", "base"], check=True, env=git_env, capture_output=True, text=True)
    (target / "coordinator" / "milestones.md").write_text("# Milestones\n\n## M1: Runtime failure\n\nScope.\n")
    (target / "dashboard-decision.md").write_text("status: resolved\nchoice: create_and_publish\n")
    generator = tmp_path / "generator.sh"
    generator.write_text("#!/usr/bin/env bash\nset -euo pipefail\ncd \"$HARNESS_DELIVERABLE\"\nprintf generated > generated.txt\ngit add generated.txt\ngit commit -m $'candidate\\n\\nHarness-Candidate: '\"$HARNESS_CANDIDATE_ID\"\n")
    generator.chmod(0o755)
    evaluator = tmp_path / "evaluator.sh"
    evaluator.write_text("#!/usr/bin/env bash\necho evaluator unavailable >&2\nexit 3\n")
    evaluator.chmod(0o755)
    uploads, fake_bin = tmp_path / "uploads", tmp_path / "fake-bin"
    fake_bin.mkdir()
    uploader = fake_bin / "fulcra"
    uploader.write_text("#!/usr/bin/env python3\nimport os, shutil, sys\ndestination = os.path.join(os.environ['HARNESS_TEST_UPLOADS'], sys.argv[4])\nos.makedirs(os.path.dirname(destination), exist_ok=True)\nshutil.copyfile(sys.argv[3], destination)\n")
    uploader.chmod(0o755)
    refresh = tmp_path / "refresh.sh"
    refresh.write_text("#!/usr/bin/env bash\nprintf '%s' \"$HARNESS_OUTCOME\" > \"$HARNESS_REFRESH_RESULT\"\n")
    refresh.chmod(0o755)
    result = subprocess.run([sys.executable, str(target / "coordinator" / "run_milestone.py"), "--milestone", "M1", "--deliverable", str(deliverable), "--git-mode", "local", "--integration-branch", "main", "--team", "demo"], env={**git_env, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}", "HARNESS_TEST_UPLOADS": str(uploads), "HARNESS_GENERATOR_CMD": str(generator), "HARNESS_EVALUATOR_CMD": str(evaluator), "HARNESS_DASHBOARD_REFRESH_CMD": str(refresh), "HARNESS_REFRESH_RESULT": str(tmp_path / "refresh-result")}, capture_output=True, text=True)
    assert result.returncode == 1
    assert "Outcome:** ESCALATED" in (uploads / "team" / "demo" / "status-summary.md").read_text()
    assert (tmp_path / "refresh-result").read_text() == "ESCALATED"


def test_bootstrap_resolves_fulcra_or_fulcra_api_or_uvx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for a real reported bug: bootstrap.py used to
    unconditionally shell out to `fulcra`, even though bootstrap.sh's own
    preflight accepts `fulcra` OR `fulcra-api` on PATH -- an environment
    with only `fulcra-api` (or only `uvx fulcra-api`) would pass the shell
    preflight and then fail inside Python regardless."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))

    bootstrap_src = (target / "coordinator" / "bootstrap.py").read_text()
    assert "_resolve_fulcra_cli" in bootstrap_src
    # No remaining hardcoded ["fulcra", ...] call sites -- every real
    # invocation must go through the resolved FULCRA_CLI.
    assert '["fulcra", "file"' not in bootstrap_src

    import shutil as shutil_module

    original_which = shutil_module.which

    def fake_which(name: str):
        # Simulate an environment where only `fulcra-api` exists, not `fulcra`.
        if name == "fulcra-api":
            return "/usr/bin/fulcra-api"
        if name == "fulcra":
            return None
        return original_which(name)

    monkeypatch.setattr(shutil_module, "which", fake_which)

    sys.path.insert(0, str(target / "coordinator"))
    try:
        import importlib

        if "bootstrap" in sys.modules:
            del sys.modules["bootstrap"]
        import bootstrap  # type: ignore

        importlib.reload(bootstrap)
        assert bootstrap.FULCRA_CLI == ["fulcra-api"]
    finally:
        sys.path.remove(str(target / "coordinator"))
        if "bootstrap" in sys.modules:
            del sys.modules["bootstrap"]


def test_noop_generator_commit_guard_and_remote_branch_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression coverage for #46 review: unchanged Generator output must
    not reach PR/Evaluator, and a remote-only milestone branch must be
    resumed rather than reset from origin/main."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    module = _load_run_milestone_module(target)
    deliverable = tmp_path / "deliverable"
    deliverable.mkdir()

    # The pure no-op guard is independent of provider/host adapters.
    responses = iter(["same", "same"])
    monkeypatch.setattr(module, "run", lambda *args, **kwargs: type("R", (), {"stdout": next(responses), "returncode": 0})())
    assert not module.has_new_commit(deliverable, "same")

    calls: list[list[str]] = []
    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        text = ""
        if "status" in cmd:
            text = ""
        elif "rev-parse" in cmd and cmd[-1] == "remote-branch":
            return type("R", (), {"stdout": "", "returncode": 1})()
        elif "rev-parse" in cmd and cmd[-1] == "origin/remote-branch":
            return type("R", (), {"stdout": "origin-sha", "returncode": 0})()
        elif "rev-parse" in cmd and cmd[-1] == "HEAD":
            text = "remote-sha"
        return type("R", (), {"stdout": text, "returncode": 0})()

    monkeypatch.setattr(module, "run", fake_run)
    assert module.ensure_milestone_branch(deliverable, "remote-branch") == "remote-sha"
    assert ["git", "-C", str(deliverable), "checkout", "-B", "remote-branch", "origin/remote-branch"] in calls


def test_same_milestone_dirty_worktree_resumes_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Meaningful interrupted Generator work on its current milestone branch
    is resumed, while no fetch, checkout, stash, or reset can discard it."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    module = _load_run_milestone_module(target)
    deliverable = tmp_path / "deliverable"
    deliverable.mkdir()
    branch = "milestone/m1-input-contract"
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if "status" in cmd:
            return type("R", (), {"stdout": " M app/main.ts\n", "returncode": 0})()
        if "branch" in cmd:
            return type("R", (), {"stdout": f"{branch}\n", "returncode": 0})()
        if "rev-parse" in cmd and cmd[-1] == "HEAD":
            return type("R", (), {"stdout": "resume-sha\n", "returncode": 0})()
        raise AssertionError(f"Unexpected command during same-branch resume: {cmd}")

    monkeypatch.setattr(module, "run", fake_run)
    assert module.ensure_milestone_branch(deliverable, branch) == "resume-sha"
    assert not any("fetch" in cmd or "checkout" in cmd for cmd in calls)


def test_local_mode_uses_searchable_candidate_commit_and_integrates_multiple_commits(tmp_path: Path) -> None:
    """A local harness needs neither GitHub nor origin: it evaluates a fixed
    candidate SHA, then creates a separately identifiable completion merge."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    deliverable = tmp_path / "deliverable"
    deliverable.mkdir()
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    subprocess.run(["git", "init", "-b", "main", str(deliverable)], check=True, env=git_env, capture_output=True, text=True)
    (deliverable / "README.md").write_text("base\n")
    subprocess.run(["git", "-C", str(deliverable), "add", "."], check=True, env=git_env, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(deliverable), "commit", "-m", "base"], check=True, env=git_env, capture_output=True, text=True)
    (target / "coordinator" / "milestones.md").write_text("# Milestones\n\n## M1: Local candidate\n\nScope.\n")
    # No refresh adapter is configured below. An active dashboard must record
    # staleness without changing this otherwise successful run to exit 1.
    (target / "dashboard-decision.md").write_text("status: resolved\nchoice: create_and_publish\n")
    generator = tmp_path / "generator.sh"
    generator.write_text("""#!/usr/bin/env bash
set -euo pipefail
cd "$HARNESS_DELIVERABLE"
printf 'first\\n' > generated.txt
git add generated.txt
git commit -m 'feat: first incremental change'
printf 'second\\n' >> generated.txt
git add generated.txt
git commit -m $'feat: ready for evaluation\\n\\nHarness-Candidate: '"$HARNESS_CANDIDATE_ID"
""")
    generator.chmod(0o755)
    evaluator = tmp_path / "evaluator.sh"
    evaluator.write_text("#!/usr/bin/env bash\nset -euo pipefail\nprintf 'test_runner: PASS\\noverall: PASS\\n'\n")
    evaluator.chmod(0o755)
    uploads = tmp_path / "uploads"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    uploader = fake_bin / "fulcra"
    uploader.write_text("""#!/usr/bin/env python3
import os
import shutil
import sys
if sys.argv[1:3] != ['file', 'upload']:
    raise SystemExit(2)
destination = os.path.join(os.environ['HARNESS_TEST_UPLOADS'], sys.argv[4])
os.makedirs(os.path.dirname(destination), exist_ok=True)
shutil.copyfile(sys.argv[3], destination)
""")
    uploader.chmod(0o755)
    result = subprocess.run(
        [sys.executable, str(target / "coordinator" / "run_milestone.py"), "--milestone", "M1", "--deliverable", str(deliverable), "--git-mode", "local", "--integration-branch", "main", "--team", "demo"],
        env={**git_env, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}", "HARNESS_TEST_UPLOADS": str(uploads), "HARNESS_GENERATOR_CMD": str(generator), "HARNESS_EVALUATOR_CMD": str(evaluator)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Outcome:** PASS" in (uploads / "team" / "demo" / "status-summary.md").read_text()
    assert "refresh_failed_or_stale" in (uploads / "team" / "demo" / "dashboard" / "refresh-status.md").read_text()
    candidate = "harness/m1-candidate"
    head_sha = subprocess.run(["git", "-C", str(deliverable), "rev-parse", "main"], check=True, env=git_env, capture_output=True, text=True).stdout.strip()
    message = subprocess.run(["git", "-C", str(deliverable), "log", "-1", "--format=%B", "milestone/m1-local-candidate"], check=True, env=git_env, capture_output=True, text=True).stdout
    assert f"Harness-Candidate: {candidate}" in message
    assert (deliverable / "generated.txt").read_text() == "first\nsecond\n"
    merge_parents = subprocess.run(["git", "-C", str(deliverable), "show", "-s", "--format=%P", "main"], check=True, env=git_env, capture_output=True, text=True).stdout.split()
    merge_message = subprocess.run(["git", "-C", str(deliverable), "log", "-1", "--format=%B", "main"], check=True, env=git_env, capture_output=True, text=True).stdout
    assert len(merge_parents) == 2
    assert subprocess.run(["git", "-C", str(deliverable), "rev-parse", "milestone/m1-local-candidate"], check=True, env=git_env, capture_output=True, text=True).stdout.strip() in merge_parents
    assert merge_message.startswith("harness/m1: complete milestone")
    assert not subprocess.run(["git", "-C", str(deliverable), "tag", "--list"], check=True, env=git_env, capture_output=True, text=True).stdout.strip()
    for label in ("control-harness", "deliverable"):
        bundle = uploads / "team" / "demo" / "artifact" / "git-bundles" / "M1" / f"{label}-latest.bundle"
        assert bundle.is_file(), f"missing terminal {label} bundle from fresh --team run"


def test_repository_bundles_are_uploaded_after_a_harness_run(tmp_path: Path) -> None:
    """Portable full-history bundles for both repositories are written to the
    stable Workspace paths; the latter replace prior full bundles by design."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    module = _load_run_milestone_module(target)
    deliverable = tmp_path / "deliverable"
    deliverable.mkdir()
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    for repo in (deliverable,):
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, env=git_env, capture_output=True, text=True)
        (repo / "tracked.txt").write_text("tracked\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=git_env, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True, env=git_env, capture_output=True, text=True)
    uploads = tmp_path / "uploads"
    uploader = tmp_path / "fake-fulcra"
    uploader.write_text("""#!/usr/bin/env python3
import os
import shutil
import sys
if sys.argv[1:3] != ['file', 'upload']:
    raise SystemExit(2)
destination = os.path.join(os.environ['HARNESS_TEST_UPLOADS'], sys.argv[4])
os.makedirs(os.path.dirname(destination), exist_ok=True)
shutil.copyfile(sys.argv[3], destination)
""")
    uploader.chmod(0o755)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("HARNESS_TEST_UPLOADS", str(uploads))
    try:
        module.archive_repositories([str(uploader)], "demo", "M1", deliverable, pruning_approved=False)
    finally:
        monkeypatch.undo()
    for label in ("control-harness", "deliverable"):
        bundle = uploads / "team" / "demo" / "artifact" / "git-bundles" / "M1" / f"{label}-latest.bundle"
        assert bundle.is_file()
        repo = target if label == "control-harness" else deliverable
        verified = subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=repo, capture_output=True, text=True)
        assert verified.returncode == 0, verified.stderr


def test_control_scaffold_includes_codex_oauth_role_adapter(tmp_path: Path) -> None:
    """The portable control scaffold exposes Codex CLI OAuth without
    pretending its subscription token is a public OpenAI API credential."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    adapter = target / "adapters" / "codex_role.py"
    assert adapter.is_file()
    text = adapter.read_text()
    assert '"codex",' in text
    assert '"exec",' in text
    assert "OpenAI API key" in text
    assert "OPENAI_API_KEY" not in text


def test_templates_exclude_runtime_cache_copy() -> None:
    """The scaffold loop must only copy explicit .template source files;
    runtime __pycache__/pyc artifacts must never become harness files."""
    source = SCRIPT.read_text()
    assert 'rglob("*.template")' in source
    assert '"__pycache__"' in source


def test_role_timeout_kills_process_group_then_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung provider must receive group TERM and the bounded retry may
    proceed to a fresh successful provider process rather than leaking the
    child beyond the wall-clock timeout."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))
    module = _load_run_milestone_module(target)
    deliverable = tmp_path / "deliverable"
    deliverable.mkdir()

    class HungProcess:
        pid = 4242
        returncode = None
        calls = 0
        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("generator", timeout or 1)
            return ("", "")

    class PassingProcess:
        pid = 4343
        returncode = 0
        def communicate(self, timeout=None):
            return ("generator done", "")

    processes = iter([HungProcess(), PassingProcess()])
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: next(processes))
    monkeypatch.setattr(module.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setenv("HARNESS_GENERATOR_CMD", "trusted-generator")

    result = module.role_command("generator", "trusted-generator", "M1", "scope", deliverable, timeout=1, retries=2)
    assert result == "generator done"
    assert killed == [(4242, module.signal.SIGTERM)]


def test_bootstrap_sh_wrapper_accepts_uvx_only_environment(tmp_path: Path) -> None:
    """Regression test for a real reported bug: bootstrap.sh's own shell
    preflight rejected a real, valid environment where only `uvx` is
    available (no direct `fulcra`/`fulcra-api` executable on PATH), even
    after coordinator/bootstrap.py's Python resolver was fixed to accept
    exactly that case -- the shell wrapper never delegated to it and had
    its own, stricter, out-of-sync check. This test exercises the actual
    ./bootstrap.sh entry point users invoke (not just the Python module),
    with a fabricated PATH containing only a stub `uvx`, matching the
    reviewer's real reproduction steps."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))

    bootstrap_sh_src = (target / "bootstrap.sh").read_text()
    # The old, out-of-sync duplicate check must be gone -- resolution is
    # delegated to coordinator/bootstrap.py's Python resolver instead.
    assert "command -v fulcra " not in bootstrap_sh_src.replace("command -v fulcra-api", "")

    # Build a fake PATH with a stub `uvx` that responds just enough for a
    # --dry-run bootstrap to complete without needing real credentials:
    # `uvx fulcra-api file stat ...` exits 1 (team doesn't exist yet, so
    # bootstrap.py takes the "provisioning new team" -> dry-run path,
    # which never actually uploads anything).
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    uvx_stub = fake_bin / "uvx"
    uvx_stub.write_text("#!/usr/bin/env bash\nexit 1\n")
    uvx_stub.chmod(0o755)

    # Real python3/bash/dirname must still be reachable for the script
    # itself to run (bootstrap.sh uses dirname internally to resolve
    # SCRIPT_DIR) -- symlink the minimal set of real coreutils needed,
    # not a full real PATH, so the test genuinely proves the fulcra-CLI
    # check itself (not some other missing tool) is what used to fail.
    import shutil as shutil_module

    for tool in ("python3", "bash", "dirname", "cd"):
        real_path = shutil_module.which(tool)
        if real_path:
            (fake_bin / tool).symlink_to(real_path)
    real_python3 = shutil_module.which("python3")
    real_bash = shutil_module.which("bash")
    assert real_python3 and real_bash

    deliverable = tmp_path / "fake-deliverable"
    deliverable.mkdir()

    env = {"PATH": str(fake_bin)}
    result = subprocess.run(
        ["bash", str(target / "bootstrap.sh"), "review-team",
         "--deliverable", str(deliverable), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert "neither 'fulcra' nor 'fulcra-api' CLI found" not in result.stderr
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_doctor_sh_accepts_uvx_only_environment(tmp_path: Path) -> None:
    """Regression test for a real reported bug: doctor.sh had its own
    third, separate fulcra/fulcra-api-only tooling check that never
    learned about uvx even after bootstrap.sh and bootstrap.py were both
    fixed to accept it -- so a fresh bootstrap -> doctor sequence could
    pass bootstrap.sh and then fail doctor.sh in a genuinely valid
    uvx-only environment. Exercises the actual generated ./doctor.sh
    entry point with a fabricated PATH containing only a stub `uvx`."""
    target = tmp_path / "control"
    _run_scaffold("--project-name", "Test Project", "--output-dir", str(target))

    doctor_sh_src = (target / "doctor.sh").read_text()
    assert "uvx" in doctor_sh_src, "doctor.sh must accept uvx as a valid fulcra CLI route"

    # Fill spec.md so that check doesn't also fail and muddy this test's
    # specific assertion about the tooling check.
    spec_path = target / "spec.md"
    spec_text = spec_path.read_text()
    spec_text = spec_text.replace(
        "<!-- Fill after fulcra-prototype-grill-me Architecture/Plan approval. -->",
        "filled in for this test",
    )
    spec_path.write_text(spec_text)

    fake_bin = tmp_path / "fake_bin_doctor"
    fake_bin.mkdir()
    uvx_stub = fake_bin / "uvx"
    uvx_stub.write_text("#!/usr/bin/env bash\nexit 1\n")
    uvx_stub.chmod(0o755)

    import shutil as shutil_module

    for tool in ("python3", "bash", "dirname", "grep"):
        real_path = shutil_module.which(tool)
        if real_path:
            (fake_bin / tool).symlink_to(real_path)

    env = {
        "PATH": str(fake_bin),
        "HARNESS_GENERATOR_CMD": "true",
        "HARNESS_EVALUATOR_CMD": "true",
    }
    result = subprocess.run(
        ["bash", str(target / "doctor.sh")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert "no usable fulcra CLI found" not in result.stdout
    assert "fulcra CLI resolved: uvx fulcra-api" in result.stdout, result.stdout
