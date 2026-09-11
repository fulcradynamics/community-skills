---
name: fulcra-rapid-prototype
description: "Scaffold a project-specific Fulcra runtime harness and its separate control harness. Orchestrates fulcra-prototype-grill-me, one shared Fulcra Workspace, milestone/PR evaluation, and the recommended harness dashboard without duplicating those skills' detailed contracts."
author: schr3b3r
version: 1.2.0
metadata:
  tags: [fulcra, agent-harness, scaffolding, rapid-prototype, evaluation, milestones]
---

# Fulcra Rapid Prototype

Use this skill when the user wants an inspectable, project-specific Fulcra
agent harness — not merely a one-off agent coding session.

It composes four components rather than reimplementing each one:

```text
fulcra-prototype-grill-me  → requirements + early project Workspace
runtime harness scaffold   → inner model/tool execution loop
control harness            → milestones + Generator/Evaluator + Workspace state
fulcra-harness-dashboard    → operator visibility + curated publication
```

The **runtime harness** is the inner model/tool loop that executes a task.
The **control harness** is the outer project loop that decides which bounded
task runs, evaluates it independently, records state, and merges only
approved work.

## Use it when

- the project is built on Fulcra and needs a custom, inspectable agent loop;
- the user wants durable progress/decision history across sessions;
- the work needs milestone branches, independent evaluation, or unattended
  operation.

Do not use it for one-off scripts, projects with no Fulcra role, or a task
where the user wants an agent to build directly without a separate harness.

## Prerequisites

- `fulcra-prototype-grill-me`
- `fulcra-workspaces` and `fulcra-connect` (used by Grill-Me Step 1b)
- `fulcra-harness-dashboard` (recommended visibility layer)

Do not request model credentials during intake, architecture, plan, or
dry-run scaffolding. Request/configure a provider only immediately before
verifying the inner runtime harness. Prefer an already-authenticated provider
path when one is available; see the generated `.env.example` and
`harness/providers/` docs for current options.

# Flow

```text
╭──────────────────────────────╮   ╭──────────────────────────────╮   ╭──────────────────────────────╮
│ ① Shape the project 💡       │ ⟶ │ ② Architect the work 🧭      │ ⟶ │ ③ Scaffold the harness 📦    │
╰──────────────────────────────╯   ╰──────────────────────────────╯   ╰──────────────────────────────╯
                                                                              │
                                                                              ▼
                                           ④ Set up the live view 🗺️  ⟶  ⑤ Verify the runtime ✅
                                                                              │
                                                                              ▼
                                           ⑥ Build in tested pieces 🛠️  ⟶  ╭──── ⑦ Let it loop ⏱️ ────╮
                                                                                 ╰────── ∞ ──────╯
```

Rapid Prototype completes the first two outcomes by invoking Grill-Me
internally: it helps the user shape the idea, save the shared project record,
agree on the architecture, and plan the work. The user sees one continuous
journey here; Grill-Me's internal numbering is not displayed.

At each step below, the compact `✦ YOU ARE HERE` marker identifies the current
outcome. You may add a compact project-specific flourish (symbol, short label,
motif), but preserve the user-facing outcome, ordering, handoff boundary, and
current-step marker.

Follow these steps in order. Each referenced skill/template owns its detailed
rules; do not duplicate or weaken them here.

## 1. Establish requirements and one shared project Workspace

```text
① Shape the project 💡  ⟶  ② Architect the work 🧭  ⟶  ③ Scaffold the harness 📦
   ✦ YOU ARE HERE
```

Run `fulcra-prototype-grill-me` through Intake & Interview and its Step 1b
Workspace/authentication step. This establishes the project goal, captures the
initial user context, and creates/joins the single project Workspace:

```text
team/prototype-<project>/
```

It must contain the Grill-Me intake/interview result before Architecture
begins. On resume, confirm the existing approved intake context is current and
backfill missing Workspace records instead of rerunning discovery.

Stop before Grill-Me's Architecture phase; it is Rapid Prototype Step 2.

Required local artifact after this step:

```text
intake/brief.md
```

## 2. Architect the work

```text
① Shape the project 💡  ⟶  ② Architect the work 🧭  ⟶  ③ Scaffold the harness 📦
                               ✦ YOU ARE HERE
```

Continue `fulcra-prototype-grill-me` through its Architecture user gate and
Plan phase. Store the approved architecture and plan artifacts in the same
Workspace as they are created. Do not start Grill-Me's Prototype/Build phases:
the harness below replaces them.

Required local artifacts after this step:

```text
architecture.md   # user approved
plan.md
```

## 3. Scaffold and bootstrap the harness **before inner runtime work**

```text
② Architect the work 🧭  ⟶  ③ Scaffold the harness 📦  ⟶  ④ Set up the live view 🗺️  ⟶  ⑤ Verify the runtime ✅
                                 ✦ YOU ARE HERE
```

Locate this skill directory, then run the bundled scaffold script with
`--dry-run` first:

```bash
python scripts/scaffold.py \
  --project-name "<Project name>" \
  --rapid-prototype-dir <approved Grill-Me repo> \
  --output-dir <new project directory> \
  --dry-run
```

After user review of the dry-run manifest, run it without `--dry-run`.
The script preserves Grill-Me git history when possible (`--history=auto`).
Use `--history=preserve` only when loss of that history should be a hard
error.

The output project contains the concrete inner loop, provider adapters,
sandboxed tools, prompts, app skeleton, and smoke tests. Read the generated
README for its exact layout and setup instructions.

Before asking for runtime provider credentials, running inner smoke tests, or
calling `harness.run_task`, also create a sibling portable control-harness repo:

```bash
python scripts/scaffold_control_harness.py \
  --project-name "<Project name>" \
  --output-dir <new sibling control directory> \
  --dry-run
```

Review the dry-run, then scaffold it. A real scaffold initializes a non-empty
local Git repository on `main`, so its required terminal Git bundle can be
created without relying on operator Git identity or a manual `git init`. Fill
its `spec.md` and `coordinator/milestones.md` from the approved Grill-Me
artifacts. Configure genuinely separate Generator and Evaluator adapter
commands, then run:

```bash
./bootstrap.sh <team-name> --deliverable <project directory>
```

Do not run `./doctor.sh` yet: the dashboard decision in Step 4 is a
required readiness gate. This **extends the same Grill-Me Workspace**,
adding role member state, control artifacts, milestone tracking, decisions,
verdicts, and status. It does not create a second project tracker.

Use the control harness README/RUNBOOK as the source of truth for:

- provider/host adapters;
- local or remote Git lifecycle, candidate commit markers, and optional PR adapters;
- executable test-runner gate;
- retries, timeouts, and provider-limit handling;
- decision requests;
- interrupted-work recovery.

## 4. Decide and record the harness dashboard path (required gate)

```text
③ Scaffold the harness 📦  ⟶  ④ Set up the live view 🗺️  ⟶  ⑤ Verify the runtime ✅  ⟶  ⑥ Build in tested pieces 🛠️
                                 ✦ YOU ARE HERE
```

Ask the user exactly one question:

> The recommended path is to create and publish the curated harness dashboard
> at an unguessable URL. Do you confirm that path, defer it, or decline it
> for this project?

Record the raw answer in `decisions.md`, then resolve
`dashboard-decision.md` with one of:

```text
status: resolved
choice: create_and_publish
publication: confirmed

status: resolved
choice: defer
publication: deferred

status: resolved
choice: decline
publication: declined
```

Synchronize that resolved decision to the shared Workspace decision/status
state. **Do not proceed to runtime verification or deliverable work while
this file is pending/invalid.** Run `./doctor.sh` after recording the
choice; it enforces this gate.

- **create_and_publish:** invoke `fulcra-harness-dashboard`. It adapts
  `fulcra-project-dashboard` to show the flight plan, run timeline,
  checkpoint, decisions, escalations, and next bearing. If the skill is not
  locally available, say so explicitly and offer the user an install/invoke
  path; do not silently skip the decision. Build the isolated public
  manifest, show it, and obtain the separate explicit deployment
  confirmation before recording `publication: confirmed`.
- **defer / decline:** preserve the user reason in `decisions.md` and
  Workspace state. Do not repeatedly re-ask unless the user reopens it.

Creating a local dashboard does **not** authorize publication. The normal
publication flow is an isolated curated dashboard at an **unguessable URL**.
Before publishing: add `noindex,nofollow`, print the exact `public/` manifest,
state that anyone with the URL can access it, and obtain explicit user
confirmation. An unguessable URL and robots directive reduce discovery; they
are **not access control**. Never publish raw inboxes, full verdicts,
credentials, or private repository data.

## 5. Verify the inner runtime harness

```text
④ Set up the live view 🗺️  ⟶  ⑤ Verify the runtime ✅  ⟶  ⑥ Build in tested pieces 🛠️  ⟶  ⑦ Let it loop ⏱️
                                   ✦ YOU ARE HERE
```

Now configure a provider using the generated `.env.example`, install the
project environment, and run the complete six-command readiness suite in the
generated README's **Getting started** section. Use the documented `uv`
fallback if `python -m venv` fails because `ensurepip` is unavailable.

Do not report the runtime harness ready until its smoke tests pass. A single
known bytecode-cache artifact may be cleared and retried once; unrelated
failures are real failures.

## 6. Operate through the control harness

```text
⑤ Verify the runtime ✅  ⟶  ⑥ Build in tested pieces 🛠️  ⟶  ⑦ Let it loop ⏱️
                              ✦ YOU ARE HERE
```

Do not start deliverable work by directly invoking the inner runtime loop.
The control harness chooses one milestone, creates/resumes its branch, sends
Generator work, requires a committed artifact, invokes Evaluator, and records
durable Workspace state.

The non-negotiable operating rules are:

- user-approved spec and raw decisions change only by user decision;
- Generator and Evaluator are separate sessions/processes;
- one bounded milestone per invocation;
- Generator may make coherent incremental milestone commits, but the final
  candidate commit must carry the Coordinator-provided candidate identifier;
- Evaluator grades the final candidate's fixed SHA, never a mutable branch
  head; its `Harness-Candidate:` commit marker remains searchable in Git;
- declared test runner must pass before a PASS can integrate;
- GitHub/PRs are optional: local Git mode integrates a PASS candidate through
  a non-fast-forward completion merge marked `harness/<milestone>`;
- after every harness run, upload full-history Git bundles of the control
  harness and deliverable to the Fulcra Workspace; stable latest bundle names
  may replace older full bundles because the newest contains history; retain
  three File Store versions by default, but obtain and record explicit user
  approval before any version pruning;
- decision requests pause work and notify the user one question at a time;
- preserve/recover interrupted work; never discard source or let verifier
  roles patch deliverable code;
- use the delayed verifier pattern for unattended schedules.

When the dashboard decision is `create_and_publish`, `run_milestone.py`
invokes `HARNESS_DASHBOARD_REFRESH_CMD` after each terminal status/progress/
verdict update. The command refreshes local curated data; if that changes the
public manifest, persist `refresh_pending` and ask the user to approve the
exact new manifest before republishing. Never silently leave a published
dashboard stale or silently republish a changed manifest.

## 7. Offer independent scheduled operation (one-time user decision)

```text
⑥ Build in tested pieces 🛠️  ⟶  ╭──── ⑦ Let it loop ⏱️ ────╮
                                    ╰────── ∞ ──────╯
                                         ✦ YOU ARE HERE
```

After the first control-harness run is healthy, ask the user exactly once:

> Do you want this harness to run independently on a schedule? If so, what
> cadence, operating window/end, and notification channel should it use?

Record the answer in `decisions.md`, control-harness policy, Workspace status,
and dashboard. If approved, follow `coordinator/scheduled-operation.md` to
create a main Coordinator schedule plus delayed verifier. The user does not
need to approve or trigger each later run; the scheduler owns the bounded
milestone invocations. Defer/decline is valid and should not be repeatedly
re-asked unless the user reopens it.

# What this skill does not do

- It does not replace Grill-Me requirements gathering.
- It does not hardcode one model provider or PR host.
- It does not run unreviewed inner-loop tasks before the control plane exists.
- It does not treat dashboard publication as access control.
- It does not duplicate implementation detail already maintained in the
  scaffold scripts, templates, or dependency skills.
