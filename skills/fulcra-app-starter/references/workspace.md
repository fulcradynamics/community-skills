# Workspace

Lightweight tracking structure for app-building progress and history. Enables resume capability without the complexity of multi-agent coordination.

## Purpose

The workspace provides:
- **Resume capability** — Pick up where you left off after interruption
- **History preservation** — Record of completed milestones and decisions
- **Current state visibility** — Single source of truth for what's done and what's next

All files live in Fulcra File Store under `workspace/<project-name>/`.

## Structure

```
workspace/<project-name>/
├── plan.md              # Approved enhancement plan (from step 1)
├── spec.md              # Requirements and milestones (from interview)
├── progress.md          # Current state snapshot
├── outstanding-issues.md # Issues requiring user attention
└── history/             # Timestamped milestone completion records
    └── YYYYMMDD-HHMMSS_milestone-name.md
```

### plan.md

Created in step 1 after user approval. Contains:
- Core app idea
- Fulcra-enabled enhancements
- High-level vision

This is the approved plan that guides spec creation and implementation.

### spec.md

Created during the interview step. Contains:
- App description and purpose
- Milestone breakdown
- Key features and requirements

Updated as requirements evolve.

### progress.md

Single source of truth for current state. Updated by Coordinator after each harness run.

Suggested sections:
- **Current Status** — Where we are, what's working
- **Active Milestone** — Current milestone name from spec.md
- **Harness State** — Current run status, retry count, last run timestamp
- **Next Actions** — Specific next steps
- **Recent Completions** — Last 3-5 completed milestones with dates
- **Open Questions** — Anything blocking or unclear
- **Notes** — Context worth preserving

### outstanding-issues.md

Issues requiring user attention. Updated by Nurse when escalations occur.

Format:
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

### history/

One timestamped file per completed milestone. Created by Coordinator when milestone passes review.

Suggested content:
- What was built
- Key decisions made during generation
- Review notes and issues found
- Any retries and what was attempted
- Context for next milestone

## Fulcra File Operations

Upload and download workspace files using `uvx fulcra-api file`:

```bash
# Upload to workspace
uvx fulcra-api file upload /local/path/spec.md "workspace/<project-name>/spec.md"

# Download from workspace
uvx fulcra-api file download "workspace/<project-name>/progress.md" /local/path/progress.md

# List workspace files
uvx fulcra-api file list "workspace/<project-name>/"
```

## Update Patterns

### During Idea and Enhancement (Step 1)
- Create plan.md with approved enhancement vision
- Upload to `workspace/<project-name>/plan.md`
- Initialize progress.md with empty state
- Upload to `workspace/<project-name>/progress.md`

### During Interview for Spec (Step 2)
- Create spec.md locally based on clarifying questions and plan
- Upload to `workspace/<project-name>/spec.md`

### During Harness Runs

**Coordinator** (after milestone completion):
- Downloads current progress.md
- Updates with new completion in Recent Completions
- Clears or updates Active Milestone
- Uploads updated progress.md
- Creates timestamped history file
- Uploads to `workspace/<project-name>/history/YYYYMMDD-HHMMSS_milestone-name.md`

**Generator** (before starting work):
- Downloads progress.md and spec.md
- Reads current state and milestone requirements
- May reference recent history for context

**Evaluator** (during review):
- May download recent history files to understand patterns/issues

**Nurse** (during health checks):
- Downloads progress.md to understand current state
- May review history when diagnosing stuck runs

## Resume Pattern

When resuming work after interruption:

1. Download and read `progress.md` → See active milestone, harness state, and current status
2. Download and read `spec.md` → Find milestone requirements
3. (Optional) Download `plan.md` → Understand original enhancement vision
4. (Optional) Download recent history files → Understand patterns from past work
5. Determine where to continue in the harness flow

The Coordinator uses this same pattern to find the next incomplete milestone.

## Integration with Harness Flow

Workspace updates happen at natural points in the harness cycle:

- **Before generate**: Generator reads workspace for context
- **After milestone passes review**: Coordinator updates progress and creates history
- **During health check**: Nurse reads workspace to diagnose issues

No additional harness steps needed—workspace reads/writes fit into existing role responsibilities.
