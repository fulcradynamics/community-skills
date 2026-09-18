# Harness Control Flow

Lifecycle for the fulcra-app-starter harness. A single **harness run** processes one
milestone; the Nurse re-triggers runs (cron, manual, etc.) to advance the project.

Roles:

- 🩺 **Nurse** — monitors and fixes the harness itself: health-check, fix attempts, escalation. The only role that modifies the harness.
- 🎛️ **Coordinator** — operates each harness run (flow control and milestone state), but **cannot modify the harness itself**.
- ✍️ **Generator** — builds the product (typically code) for the current milestone, including a reasonable — not excessive — number of tests.
- ⚖️ **Evaluator** — independently evaluates what the Generator produced for the current milestone: its correctness, its compatibility with previously completed milestones, and its fit with the overall plan and spec. Does **more than run tests** — reads the code and reasons about it against the spec.

## Rules

- **No role may modify the spec to make a milestone pass.** The spec is fixed for the harness. If a milestone cannot be satisfied as specified, the Nurse escalates to the user; only the user's response can change the spec (escalation is the sole path to a spec change).
- Only the Nurse modifies the harness. The Coordinator, Generator, and Evaluator operate within it.

```mermaid
flowchart TD
    LoopStart([RUN LOOP START]) --> PrevRun{🩺 Previous harness run completed?}

    PrevRun -->|✅| InnerLoopStart([HARNESS RUN START])
    PrevRun -->|❌| FixRemain{🩺 Fix attempts remain?}

    FixRemain -->|✅| FixAttempt[🩺 Attempt to fix harness and notify user]
    FixRemain -->|❌| Escalate[🩺 Escalate to user]

    FixAttempt --> InnerLoopStart

    subgraph InnerLoop["Harness Run"]
        InnerLoopStart --> FindIncompleteMilestone[🎛️ Find earliest incomplete milestone]
        FindIncompleteMilestone --> HasMilestone{🎛️ Any incomplete milestone?}

        HasMilestone -->|✅| GenerateCode[✍️ Generate code to implement milestone]
        HasMilestone -->|❌| ProjectComplete([PROJECT COMPLETE])

        GenerateCode --> ReviewCode[⚖️ Review generated code]
        ReviewCode --> ReviewPassed{🎛️ Review passed?}

        ReviewPassed -->|✅| MarkComplete[🎛️ Mark milestone as complete]
        ReviewPassed -->|❌| RetriesRemain{🎛️ Retries remain?}

        MarkComplete --> CompleteRun([COMPLETE HARNESS RUN])

        RetriesRemain -->|✅| LeaveIncomplete[🎛️ Leave milestone as incomplete]
        RetriesRemain -->|❌| BreakInnerLoop[🎛️ End run; mark run as incomplete]

        LeaveIncomplete --> CompleteRun
        BreakInnerLoop --> EndRunIncomplete([END RUN — INCOMPLETE])
    end

    Escalate --> BreakLoop([BREAK RUN LOOP])

    subgraph Legend["🔑 Roles"]
        L1[🩺 Nurse - Harness control]
        L2[✍️ Generator - Code generation]
        L3[⚖️ Evaluator - Code review]
        L4[🎛️ Coordinator - Flow control]
    end

    classDef processStyle fill:#e1f5ff,stroke:#0288d1,stroke-width:2px
    classDef decisionStyle fill:#fff9c4,stroke:#f57f17,stroke-width:2px
    classDef doctorStyle fill:#ffe0b2,stroke:#f57c00,stroke-width:2px
    classDef generatorStyle fill:#e0f2f1,stroke:#26a69a,stroke-width:2px
    classDef evaluatorStyle fill:#bbdefb,stroke:#1976d2,stroke-width:2px
    classDef coordinatorStyle fill:#d1c4e9,stroke:#5e35b1,stroke-width:2px
    classDef startCompleteStyle fill:#c8e6c9,stroke:#388e3c,stroke-width:2px
    classDef breakStyle fill:#ffcdd2,stroke:#d32f2f,stroke-width:2px

    class PrevRun,FixRemain,FixAttempt,Escalate doctorStyle
    class GenerateCode generatorStyle
    class ReviewCode evaluatorStyle
    class FindIncompleteMilestone,HasMilestone,ReviewPassed,MarkComplete,RetriesRemain,LeaveIncomplete,BreakInnerLoop coordinatorStyle
    class LoopStart,InnerLoopStart,CompleteRun,ProjectComplete startCompleteStyle
    class BreakLoop,EndRunIncomplete breakStyle
    class L1 doctorStyle
    class L2 generatorStyle
    class L3 evaluatorStyle
    class L4 coordinatorStyle

    linkStyle default stroke:#888888,stroke-width:2px
    style InnerLoop fill:#f5f5f5,stroke:#999999
    style Legend fill:#f5f5f5,stroke:#999999
```

## Tracking System

The harness tracks progress using two mechanisms:

1. **Custom Annotation** — Append-only log of run events (step starts, completions, errors)
2. **Workspace Files** — Persistent state (overview.md, progress.md, outstanding-issues.md)

The custom annotation enables the harness dashboard to show live run status. Workspace files enable resume capability, issue tracking, and the dashboard's human-readable overview.

## Setup

When setting up the harness (before first run), create a custom data type to
hold run events. Use `MomentAnnotation` as the base type — it stores a free-form
`note` (where we pack each run event as JSON) plus a timestamp:

```bash
uvx fulcra-api data-type create MomentAnnotation "Harness Runs: <project-name>"
```

Save the returned data type ID (of the form `MomentAnnotation/<UUID>`). This is
used as `PUBLIC_HARNESS_ANNOTATION_ID` in the dashboard's environment variables.

## Recording Run Events

Write records at key points in the flow with `fulcra-api record`. Pack the event
fields (`run_id`, `step`, `status`, `detail`) into the `note` as a JSON string;
the record's timestamp is set automatically:

```bash
uvx fulcra-api record MomentAnnotation/<UUID> \
  --note='{"run_id": "<run-id>", "step": "GENERATE", "status": "started", "detail": ""}'
```

The dashboard reads each record's `recorded_at` for timing and parses `note` for
the event fields, so nothing else needs to be set. The JSON shapes below show
the `note` payload for each kind of event.

### Run Start
```json
{
  "note": "{\"run_id\": \"<unique-run-id>\", \"step\": \"RUN_START\", \"status\": \"started\", \"detail\": \"Starting harness run\"}",
  "recorded_at": "<ISO-8601>"
}
```

### Step Transitions
Write records when each step starts and completes:

**Step Start:**
```json
{
  "note": "{\"run_id\": \"<run-id>\", \"step\": \"<STEP_NAME>\", \"status\": \"started\", \"detail\": \"\"}",
  "recorded_at": "<ISO-8601>"
}
```

**Step Complete:**
```json
{
  "note": "{\"run_id\": \"<run-id>\", \"step\": \"<STEP_NAME>\", \"status\": \"completed\", \"detail\": \"<result-summary>\"}",
  "recorded_at": "<ISO-8601>"
}
```

**Step Failed:**
```json
{
  "note": "{\"run_id\": \"<run-id>\", \"step\": \"<STEP_NAME>\", \"status\": \"failed\", \"detail\": \"<error-message>\"}",
  "recorded_at": "<ISO-8601>"
}
```

### Progress Updates (long-running steps)

`FIX_ATTEMPT`, `GENERATE`, and `REVIEW` can each run for a long time. To keep the
dashboard live while they run, emit an extra progress record for the currently
running step every few minutes — reuse `status: "started"` and update `detail`
with what is happening now:

```json
{
  "note": "{\"run_id\": \"<run-id>\", \"step\": \"<STEP_NAME>\", \"status\": \"started\", \"detail\": \"<progress-summary>\"}",
  "recorded_at": "<ISO-8601>"
}
```

Keep these coarse — every few minutes, not every action — so a run accumulates a
handful of progress records, not hundreds. The dashboard keeps the newest record
per step, so the step box shows the latest `detail` and switches to
`status: "completed"` (or `"failed"`) when you write that step's final record.

### Key Steps to Track

- `FIND_MILESTONE` — Coordinator finding next incomplete milestone
- `GENERATE` — Generator writing code
- `REVIEW` — Evaluator reviewing code  
- `MARK_COMPLETE` — Coordinator marking milestone complete
- `ESCALATE` — Nurse escalating to user
- `FIX_ATTEMPT` — Nurse attempting fix
- `RUN_COMPLETE` — Run finished successfully
- `RUN_INCOMPLETE` — Run ended without completion

### Run IDs and terminal steps

The dashboard groups records by `run_id` and infers which branch of the flow a
run took from the steps present, so record them consistently:

- **Mint a new `run_id`** at the top of each run-loop iteration, before the
  Nurse health-check. Record the Nurse's `FIX_ATTEMPT` or `ESCALATE` under that
  new `run_id` — the dashboard treats them as the start of the run they precede.
  An escalation writes only an `ESCALATE` record for that new `run_id` (no
  harness run follows); the dashboard shows it as an "escalated" run.
- When a review fails but **retries remain**, the run leaves the milestone
  incomplete yet still ends with **`RUN_COMPLETE`** (flow: *Leave milestone
  incomplete → COMPLETE HARNESS RUN*). Use **`RUN_INCOMPLETE`** only when retries
  are **exhausted** (*End run → END RUN — INCOMPLETE*). The dashboard uses this
  distinction to show "Retry Next Run" versus "End Run — Incomplete".
- When no incomplete milestone remains, still write a `FIND_MILESTONE` record
  (with no `GENERATE` after it) so the dashboard renders "Project Complete".

## Workspace Updates

### overview.md

The Nurse rewrites `workspace/<project-name>/overview.md` on **every loop** — a
concise, human-readable summary the dashboard renders at the top as styled
markdown. It is a snapshot, not a log: overwrite it each loop rather than
appending. Keep it short (it is a summary, not progress.md) and cover:

- **Overall status** — one line on whether the project is on track, and what the
  harness is doing right now.
- **Milestone list** — every milestone with its state (complete / in progress /
  pending). A checklist with emoji reads well in the dashboard.
- **Recent activity** — a sentence or two on what the last run(s) accomplished
  and any blockers.

Because the dashboard renders it as markdown, the Nurse can style it with
headings, bold, lists, and links. Example:

```markdown
# Project Overview

**Status:** On track — 3 of 7 milestones complete. Currently generating code for
Milestone 4.

## Milestones

- ✅ **M1 — Auth & user shell** — complete
- 🔄 **M4 — Leaderboard API** — in progress
- ⬜ **M5 — Sharing** — pending

## Recent activity

Last run completed the entry-logging milestone after one review retry. No
outstanding blockers.
```

Write it with `fulcra-api file upload`:

```bash
uvx fulcra-api file upload overview.md "workspace/<project-name>/overview.md"
```

### outstanding-issues.md

Update `workspace/<project-name>/outstanding-issues.md` when issues occur:

**On Escalation:**
Add issue with timestamp, run ID, and description. Include what the user needs to do.

**On Resolution:**
Remove or mark resolved when user addresses the issue or a subsequent run succeeds.

**Format:**
```markdown
# Outstanding Issues

## [ISO-8601 timestamp] - Run <run-id>

**Issue:** <description>
**Action Needed:** <what user should do>

---

## [timestamp] - Run <older-run-id> [RESOLVED]

**Issue:** <description>
**Resolution:** <how it was resolved>
```

### progress.md

Update `workspace/<project-name>/progress.md` after each harness run (see workspace.md for full structure). Include:
- Harness State section with current run status, retry count, last run timestamp
- Active Milestone
- Recent Completions (when milestones complete)
