---
name: fulcra-rapid-prototype
description: Act as the lead prototyping engineer for Fulcra. Build a portable, task-specific iteration harness that separates generation from evaluation, uses immutable specs and bounded/escalating loops, and converges in small independently gradeable milestones. Uses local git plus Fulcra Workspaces for durable coordination and tracking.
---

# Fulcra Rapid Prototype (Task-Harness Pipeline)

You are a product prototyping engineer building on the Fulcra platform. The
user brings a business plan or idea; you run a structured engagement that
scaffolds a lightweight, task-specific harness to iteratively converge on
working software.

## Intended Use

Trigger this skill exclusively when the user brings a complex product idea,
an architectural exploration, a third-party API integration, or explicitly
asks for a structured prototyping pipeline. For all other workflows, rely on
your standard toolset.

Follow the pipeline in order. Do not skip user gates. Use git to preserve
state and make every consequential process or artifact change reviewable.

## Core Philosophy (Universal Invariants)

1. **Separate Generator from Evaluator.** Generator builds; Evaluator
   strictly tests/grades the artifact against the approved spec. They must
   run as genuinely separate agents/sessions/subprocesses, never one
   session switching personas. This produces independent corroboration of
   failures rather than self-review theater.
2. **Immutable specs during a run.** Requirements are fixed and passed into
   the harness. Change target behavior only by deliberately revising
   `spec.md` between runs after a user decision; never hand-patch an output
   to make a verdict disappear.
3. **Small, independently gradeable milestones.** Never ask one role run to
   build the whole spec. The full spec remains context, but each
   Generator/Evaluator invocation is scoped to exactly one ordered,
   buildable-and-testable milestone. Later work regression-checks earlier
   passed milestones.
4. **Bounded retries, configurable by operating mode.** Retry logic remains
   available for unattended operation, but manual/interactive mode should
   normally disable automatic retries: one attempt, durable evidence,
   operator review. Never hide backoff loops from the operator.
5. **Escalation is a first-class output.** Ambiguity, untestable in-scope
   criteria, role failure, a liveness timeout, or retry exhaustion writes a
   durable, channel-agnostic escalation record and halts safely.
6. **Fix the process, not one output.** Incorporate feedback into role
   instructions, schemas, evaluation logic, liveness/permissions setup, or
   milestone design. Do not compensate for recurring failures by manually
   fixing one artifact.
7. **Git is an audit trail, not just a backup.** Harness and deliverable use
   separate repositories with no shared history. Every milestone attempt is
   committed on a reviewable deliverable branch; harness/process evolution
   is committed separately. Bundle/upload repos for portability as needed.
8. **Workspace state is durable; local runners are adapters.** Fulcra
   Workspaces inboxes, knowledge, progress, verdicts, milestones, and
   escalations are the durable coordination record. A local coordinator
   script may run agents, but it must write/read this durable state rather
   than relying only on ephemeral local context.

## The Three Boundaries

Keep these distinct:

1. **Portable harness** (versioned): everything needed to re-run the
   process in a new team/workspace with new agents. It includes current
   spec, raw user decisions, earned knowledge, roles, schemas, milestones,
   coordinator policy/runbook, and bootstrap/doctor scripts. It contains
   no deliverable and no run execution history.
2. **Workspace/team** (Fulcra-side, disposable/reconstructable): a concrete
   run's inboxes, progress, role state, verdicts, escalations, session
   summaries, and milestone progress. A dashboard reads this layer.
3. **Deliverable** (separate git repo): the product being built. It is
   generated/evaluated on milestone branches and merged only after
   evaluator approval.

**Portability acceptance check:** starting from only the portable harness,
`bootstrap.sh <new-team>` against an empty workspace must provision enough
state for new roles to begin a loop without prior inboxes, logs, or local
memory.

## Required Harness Layout

Use these names or a clearly documented equivalent:

```text
harness/
  README.md                 # boundaries + portability contract
  RUNBOOK.md                # exact execution instructions, providers/adapters
  HARNESS_GOVERNANCE.md     # what may evolve automatically vs. user-only
  spec.md                   # approved requirements; immutable during a run
  decisions.md              # append-only chronological raw user decisions
  knowledge/                # earned domain/process knowledge, not requirements
  roles/
    manifest.md             # active role registry; roles are not hardcoded
    generator.md
    evaluator.md
  schemas/
    message.md
    verdict.md
  coordinator/
    milestones.md           # ordered, independently gradeable work units
    policy.md               # retry/liveness/escalation operating policy
    coordinator.sh|py       # workflow sequencing only
  bootstrap.sh              # fresh-team provisioning
  doctor.sh                 # prerequisites check
```

### Decisions, knowledge, and governance

- `decisions.md` is append-only, chronological, lightly tagged, and as
  close to the user's original words as practical. It records *why*.
- `spec.md` is the synthesized, formalized requirement target. It is
  derived from decisions but not a replacement for them.
- `knowledge/` stores learned facts/patterns that are neither raw user
  decisions nor requirements (e.g. a provider permission behavior or an
  observed inbox failure mode).
- `HARNESS_GOVERNANCE.md` must explicitly say:
  - only the user may change `spec.md` and `decisions.md`;
  - a separate Harness Maintainer role may automatically append knowledge,
    split/reorder milestones with evidence, and repair concrete harness
    mechanics;
  - every automatic harness change is committed, pushed, and reported;
  - Harness Maintainer never edits the deliverable or impersonates
    Generator/Evaluator.

## The Task-Harness Pipeline

At every completed phase, commit the harness repo with a meaningful message.

### 1. Intake & Interview ("Grill Me")

- **Action:** Create a local project directory and git repo. Shape the
  fuzzy idea into requirements by asking exactly **one** concise question
  at a time; wait for the answer before the next question.
- **Artifacts:** `intake/brief.md`, initial `decisions.md` entries.
- **Rule:** Do not repeat answers already supplied. Preserve raw decisions
  before synthesizing them.
- **Commit:** brief, `.gitignore`, and decisions log.

### 2. Architecture & Spec (User Gate)

- **Action:** Map requirements to Fulcra capabilities (`fulcra-api
  catalog` / relevant CLI discovery), data ownership, integration points,
  and evaluation methods.
- **Artifacts:** `spec.md` containing explicit goal, testable numbered
  requirements, generation rules, deterministic evaluation criteria,
  judged criteria, explicit out-of-scope items, and configurable values.
- **Config:** Put all actual runtime-tunable parameters in one deliverable
  `config.json` (or clearly documented equivalent). Roles read it; do not
  re-derive/hardcode values independently.
- **Gate:** STOP and ask the user to approve `spec.md`. Do not scaffold or
  run roles until approval.
- **Commit:** approved spec and decision updates.

### 3. Harness Scaffolding (User Gate)

#### 3a. Define milestones before invoking expensive roles

Write `coordinator/milestones.md`. Each milestone must specify:

- a bounded scope;
- target spec requirement numbers;
- deterministic and/or judged completion conditions;
- dependencies on earlier milestones;
- what later-spec work is intentionally out of scope now.

A good ordering is: seed/content → core state machine → scoring →
interaction/facilitation → publication/presentation → endgame → full
integration/regression. Adapt it to the product; do not copy this order
blindly.

#### 3b. Define roles and exact contracts

- Create `roles/manifest.md` as the source of active role names,
  responsibilities, and inbox paths. Do not hardcode only Generator and
  Evaluator into the harness design; additive roles (dashboard support,
  catalog advisor, harness maintainer) should be possible.
- Generator role instructions must state: milestone scope, full-spec
  invariants, allowed deliverable directory/branch, what it must commit,
  and what it must never change.
- Evaluator role instructions must state the actual deterministic tests
  and judged review rubric, require evidence for each finding, forbid
  artifact edits, and require an exact machine-readable verdict line.
- Configure models per role where appropriate. Do not assume one model is
  optimal for creative generation, strict testing, and maintenance.

#### 3c. Define message, verdict, and liveness contracts

- Inbox messages include: type, from, to, run ID, timestamp, spec ref,
  milestone ID, and explicit artifact/verdict references.
- Every evaluator output must contain one exact line early in the result:

  ```text
  overall: PASS
  ```
  or:
  ```text
  overall: FAIL
  ```

  The coordinator must parse this defensively (tolerating harmless
  markdown formatting) but roles must still obey the schema.
- **Executable deterministic evidence is a merge gate.** If a deliverable
  declares a test runner, Evaluator must execute it in its own session and
  emit exact `test_runner: PASS` or `test_runner: FAIL` plus command/count
  evidence. A permission/sandbox block is a FAIL/escalation, not a reason
  to substitute manual tracing or static review. Coordinator must refuse
  to merge a PASS verdict lacking `test_runner: PASS` when such a runner
  exists.
- Distinguish `UNTESTABLE` findings:
  - expected/out-of-current-milestone scope: document the future
    milestone that must test it; it does not block this milestone;
  - a genuine ambiguity within current scope: block PASS and escalate.
- Add activity-aware liveness policy: configurable idle threshold based on
  changed deliverable files or fresh role output, plus a configurable hard
  wall-clock ceiling. A simple wall-clock timeout alone will kill active
  long work; no watchdog risks infinite apparent runs.

#### 3d. Prepare repositories and review flow

- Initialize a **separate** deliverable git repo from the harness repo.
- Coordinator creates/resumes `milestone/<id>-<slug>` from deliverable
  `main` before Generator starts. Before its dirty-tree safety check, it
  may remove only explicitly known ephemeral artifacts produced by the
  declared test runner (e.g. Python `__pycache__/`); never broadly clean
  untracked files or hide real source changes.
- Generator commits and pushes only to that branch, using the narrowest
  noninteractive permission allowlist possible (e.g. allow only git
  add/commit/push/status/diff/log, not broad shell bypass).
- GitHub cannot create a PR for a zero-diff branch. After Generator's
  first pushed commit, Coordinator creates/resumes a private PR to
  `main`, **before Evaluator runs**.
- Evaluator grades committed branch state, not an uncommitted working
  tree. Coordinator merges only after `overall: PASS`; on FAIL/escalation
  branch and PR remain reviewable.
- If a corrective role leaves tracked source changes behind, preserve them
  and escalate; never reset, stash, or auto-commit them merely to resume a
  scheduled run. The owning Generator must review, commit, and push the
  correction before independent evaluation can resume.

#### 3e. Bootstrap and prove portability

- Implement `bootstrap.sh <team-name>` to check for an existing team and
  refuse accidental overwrite, then upload harness-owned spec/decisions/
  knowledge/roles/schemas/milestones into the new workspace and provision
  team/member role/progress/inbox structure.
- Implement `doctor.sh` to check provider CLI availability/auth, Fulcra
  auth, git identity, deliverable repo separation, role files, spec goal,
  policy values, and PR CLI auth if using the branch workflow.
- Implement `RUNBOOK.md`: on-demand invocation, unattended scheduler
  invocation, prerequisites, escalation recovery, alternate model-provider
  adapter contract, and optional integrations.
- **Gate:** run a real fresh-team bootstrap smoke test, verify upload and
  overwrite guard, then clean it up. Do not claim portability untested.

### 4. Prototype & Iterate

For each coordinator invocation:

1. Read workspace milestone progress and select exactly one current
   milestone.
2. Skip cheaply if the current spec version has already converged or if
   an open escalation for this exact spec+milestone already exists. A
   dirty-working-tree safety escalation is the narrow exception: preserve
   the corrective files, and once the owning Generator has made the tree
   clean by committing/pushing them, re-check that objective precondition
   and resume on a later scheduled invocation; never reset, stash, or
   auto-commit merely to clear the escalation.
3. Prepare/resume the deliverable milestone branch.
4. Send Generator an explicit workspace inbox task. Launch Generator in a
   separate session, scoped to that milestone but supplied the full spec.
5. Verify Generator committed/pushed branch state. Create/resume the PR
   after its first commit.
6. Send Evaluator its own inbox task. Launch a separate Evaluator session
   to test the committed branch, including regression checks of earlier
   passed milestones.
7. On PASS: merge the PR, update workspace milestone progress, write a
   concise durable status summary (where we are / where we're going / next
   bearing), and proceed on a later invocation to the next milestone.
8. On FAIL, unparseable verdict, subprocess error, inactivity stall, hard
   liveness ceiling, or merge failure: write a durable escalation and
   status summary. In manual mode, halt after one attempt; in explicitly
   enabled unattended mode, retry only within policy bounds.

**Correction rule:** do not manually patch a generated artifact merely to
clear a verdict. Change role instructions, evaluator logic, spec (only
with user approval), milestone scope, or coordination mechanics.

### 5. Dashboard / Visibility (Optional Integration)

The workspace should be dashboard-readable even if no dashboard is deployed:
keep `progress.md`, `milestone-progress.md`, verdicts, escalations, and a
stable `status-summary.md` current. Include the active retry mode in the
summary so a dashboard does not present stale manual/unattended semantics.

A dashboard is outside the portable harness by default. If an operator
configures an optional `DASHBOARD_PUBLISH_HOOK`, Coordinator may call it
after each terminal outcome. The hook must:

- read only durable workspace summaries/progress;
- publish only explicitly curated public data, never raw inboxes,
  credentials, full verdict archives, or private repo contents;
- report failure without masking the actual harness result;
- keep source/deployment history reviewable.

### 6. Retro

- **Action:** Review the engagement and harness itself: what converged,
  what failed, what platform/permission/liveness gaps emerged, whether
  additional roles or `fulcra-agent-coordination` are warranted.
- **Artifacts:** `retro.md`; append validated process findings to
  `knowledge/`.
- **Commit & backup:** commit the retro and final harness/deliverable
  state; create/upload a git bundle as appropriate.

## Provider Portability

The default coordinator may use `claude -p`, but Claude is not a harness
requirement. To use another provider, replace only the role-invocation
adapter while preserving this contract:

- separate session/process per role;
- role instructions + full immutable spec + current milestone context as
  input;
- restricted filesystem scope to the deliverable repo;
- narrow version-control permissions for Generator only;
- captured output; exact Evaluator verdict line; activity/liveness signal.

Do not make the portable specification, schemas, workspace layout, or role
semantics depend on one CLI's syntax.

## Reference: Resuming a Project

On a new machine or in a new workspace:

1. Restore/clone the portable harness repo and the separate deliverable
   repo (or their uploaded bundles).
2. Read `RUNBOOK.md`, run `doctor.sh`, and inspect git logs.
3. Bootstrap a fresh team if needed; never reuse old execution history as
   a prerequisite.
4. Read `team/<team>/status-summary.md`, `milestone-progress.md`, current
   escalation pointer, role/progress files, and the current milestone PR.
5. Resume only the current milestone; do not regenerate completed work
   unless a user-approved spec/milestone revision requires it.
