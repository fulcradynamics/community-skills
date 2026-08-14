# Community Skills README Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-line README with a concise index and useful summaries of every community-contributed Fulcra skill in the repository.

**Architecture:** Keep `skills/*/SKILL.md` as the source of truth and make `README.md` a curated discovery layer. The README will establish the relationship to the official skills repository, provide installation commands, offer a compact index, and expand each indexed skill into a short plain-language section.

**Tech Stack:** GitHub-flavored Markdown, shell validation, Python 3 standard library

## Global Constraints

- Modify `README.md`; do not modify files under `skills/`.
- Preserve the committed design record at `docs/superpowers/specs/2026-08-14-community-skills-readme-index-design.md`.
- Describe this repository as community-contributed extensions built on Fulcra and complementary to `fulcradynamics/agent-skills`.
- Use current `fulcra-workspaces` terminology for workspace-based skills.
- Do not reproduce YAML frontmatter in the README.
- Do not assert a repository-level license while no root `LICENSE` file exists.
- Do not add generators, automation, or new contribution policy.

---

### Task 1: Build the Curated README Catalog

**Files:**
- Modify: `README.md`
- Reference: `skills/fulcra-agent-coordination/SKILL.md`
- Reference: `skills/fulcra-computed-data-types/SKILL.md`
- Reference: `skills/fulcra-project-dashboard/SKILL.md`
- Reference: `skills/fulcra-rapid-prototype/SKILL.md`

**Interfaces:**
- Consumes: the four authoritative `skills/*/SKILL.md` files and the approved design specification.
- Produces: a standalone `README.md` whose index anchors link to one detail section per community skill.

- [ ] **Step 1: Confirm the authoritative skill set before editing**

Run:

```bash
find skills -mindepth 2 -maxdepth 2 -name SKILL.md -print | sort
```

Expected output:

```text
skills/fulcra-agent-coordination/SKILL.md
skills/fulcra-computed-data-types/SKILL.md
skills/fulcra-project-dashboard/SKILL.md
skills/fulcra-rapid-prototype/SKILL.md
```

- [ ] **Step 2: Replace the one-line README with the approved structure**

Write `README.md` with these sections, in this order:

```markdown
# Fulcra Community Skills

Community-contributed skills for agents building on
[Fulcra](https://fulcradynamics.com). They extend the core capabilities in
Fulcra's official [`agent-skills`](https://github.com/fulcradynamics/agent-skills)
repository with more involved workflows, integrations, and examples.

Start with the official skills for Fulcra's supported foundation. Add this
collection when your agent needs one of the community use cases below.

## Installation

Install the official skills first:

```bash
npx skills add fulcradynamics/agent-skills
```

Then add the community collection:

```bash
npx skills add fulcradynamics/community-skills
```

## Skills

| Skill | What it does | Builds on |
|---|---|---|
| 🧭 [fulcra-agent-coordination](#fulcra-agent-coordination) | Add deterministic presence, roles, continuity, review, directives, and health to a shared agent workspace | [`fulcra-workspaces`](https://github.com/fulcradynamics/agent-skills/tree/main/skills/fulcra-workspaces) |
| 🛠️ [fulcra-computed-data-types](#fulcra-computed-data-types) | Turn raw data exports into tagged, queryable Fulcra data types with generated parsers | [`fulcra-ingest`](https://github.com/fulcradynamics/agent-skills/tree/main/skills/fulcra-ingest) |
| 📈 [fulcra-project-dashboard](#fulcra-project-dashboard) | Build a manager-oriented dashboard for an agent workspace | [`fulcra-workspaces`](https://github.com/fulcradynamics/agent-skills/tree/main/skills/fulcra-workspaces), [`fulcra-dashboard`](https://github.com/fulcradynamics/agent-skills/tree/main/skills/fulcra-dashboard) |
| 🚀 [fulcra-rapid-prototype](#fulcra-rapid-prototype) | Run a gated, git-backed product prototyping pipeline on Fulcra | [Fulcra primitives](https://github.com/fulcradynamics/agent-skills/tree/main/skills/fulcra-primitives) and the File Store |

## fulcra-agent-coordination

[`skills/fulcra-agent-coordination/SKILL.md`](skills/fulcra-agent-coordination/SKILL.md)

Use this skill when multiple agents already share a `fulcra-workspaces`
workspace and need an operational coordination layer. It adds presence and
liveness, leased roles, resumable continuity, review handshakes, directed work
with acknowledgements, and fleet health.

A vendored, standard-library-only engine computes shared state as deterministic
folds, so agents agree on role, review, and health status without independently
interpreting prose or timestamps.

## fulcra-computed-data-types

[`skills/fulcra-computed-data-types/SKILL.md`](skills/fulcra-computed-data-types/SKILL.md)

Use this skill to derive a new dimension—such as artists, genres, or
categories—from a raw personal-data export. The agent adapts the included
Python template to the export's shape, generates deterministic record IDs,
creates or reuses tags, and produces JSONL for ingestion.

It builds on `fulcra-ingest`, including its source mapping and ingest log, so
the computed data remains idempotent, traceable, and queryable in Fulcra.

## fulcra-project-dashboard

[`skills/fulcra-project-dashboard/SKILL.md`](skills/fulcra-project-dashboard/SKILL.md)

Use this skill to turn a `fulcra-workspaces` project into a management view. It
combines workspace files and relevant Fulcra annotations into an executive
summary, recent work log, progress overview, milestone timeline, and activity
word map.

The preferred output is a lightweight dashboard built with
`fulcra-dashboard`, Alpine.js, and D3.js, with simpler HTML, image, or Markdown
views available when the environment calls for them.

## fulcra-rapid-prototype

[`skills/fulcra-rapid-prototype/SKILL.md`](skills/fulcra-rapid-prototype/SKILL.md)

Use this skill for complex product ideas, architecture explorations, and
third-party integrations. It leads a seven-stage engagement: Intake,
Interview, Architecture, Plan, Prototype, Build, and Retro.

Git commits make each stage durable, explicit approval gates protect the
architecture and prototype decisions, and git bundles uploaded to the Fulcra
File Store make the engagement portable across sessions and machines.

## Official Fulcra Skills

For Fulcra's supported foundational skills—including getting started,
tracking, dashboards, memory, workspaces, preferences, and ingestion—see
[`fulcradynamics/agent-skills`](https://github.com/fulcradynamics/agent-skills).
```

- [ ] **Step 3: Review copy against the authoritative skill bodies**

Check each README detail section against its `SKILL.md` and confirm:

```text
fulcra-agent-coordination: names all six folded coordination capabilities
fulcra-computed-data-types: mentions generated parsers, deterministic IDs, tags, and ingest integration
fulcra-project-dashboard: uses fulcra-workspaces terminology and names the required dashboard views
fulcra-rapid-prototype: names the seven stages, git-backed state, user gates, and Fulcra bundle backup
```

- [ ] **Step 4: Inspect the documentation diff**

Run:

```bash
git diff -- README.md
git diff --check
```

Expected: only the intended README rewrite appears, with no whitespace errors.

### Task 2: Validate the Index and Publish the Draft PR

**Files:**
- Validate: `README.md`
- Validate: `skills/*/SKILL.md`
- Preserve: `docs/superpowers/specs/2026-08-14-community-skills-readme-index-design.md`
- Preserve: `docs/superpowers/plans/2026-08-14-community-skills-readme-index.md`

**Interfaces:**
- Consumes: the completed README from Task 1.
- Produces: a documentation commit pushed on `agent/community-skills-readme-index` and a draft PR targeting `main`.

- [ ] **Step 1: Validate catalog coverage and local links**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
import re

readme = Path("README.md").read_text()
skills = sorted(path.parent.name for path in Path("skills").glob("*/SKILL.md"))

for skill in skills:
    assert readme.count(f"[{skill}](#{skill})") == 1, skill
    assert len(re.findall(rf"^## {re.escape(skill)}$", readme, flags=re.MULTILINE)) == 1, skill
    assert readme.count(f"](skills/{skill}/SKILL.md)") == 1, skill

local_links = re.findall(r"\[[^]]+\]\((?!https?://|#)([^)]+)\)", readme)
for target in local_links:
    assert Path(target).exists(), target

assert len(skills) == 4, skills
print("README catalog coverage and local links: PASS")
PY
```

Expected:

```text
README catalog coverage and local links: PASS
```

- [ ] **Step 2: Confirm scope and clean Markdown**

Run:

```bash
git diff --check
git status --short
git diff --name-only HEAD
```

Expected: `README.md` is the only uncommitted implementation file; no file under `skills/` is modified.

- [ ] **Step 3: Commit the README implementation**

Run:

```bash
git add README.md
git commit -m "docs: index community Fulcra skills"
```

Expected: a commit containing only `README.md` is created after the already-committed design and plan records.

- [ ] **Step 4: Re-run validation against the committed tree**

Run:

```bash
git diff --check HEAD^ HEAD
git show --stat --oneline HEAD
git status -sb
```

Expected: no whitespace errors, the latest commit changes only `README.md`, and the branch is clean.

- [ ] **Step 5: Push the branch**

Run:

```bash
git push -u origin agent/community-skills-readme-index
```

Expected: the branch is available on `origin` with upstream tracking configured.

- [ ] **Step 6: Open a draft pull request**

Create a draft PR against `main` with:

```text
Title: docs: index community Fulcra skills

Body sections:
- Summary: positions the repo as the community extension layer and indexes all four skills.
- Details: notes installation guidance, the compact table, and the per-skill summaries.
- Validation: records catalog coverage, local-link validation, and `git diff --check`.
```

Expected: a draft PR in `fulcradynamics/community-skills` from `agent/community-skills-readme-index` to `main`.
