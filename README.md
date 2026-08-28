# community-skills

Community-led skills for agents powered by the Fulcra platform — more involved use cases and contributed workflows that build on the core skills in [fulcradynamics/agent-skills](https://github.com/fulcradynamics/agent-skills).

Install one, and your agent will know what to do when you ask.

## Installation

Using the [skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add fulcradynamics/community-skills
```

Or install a single skill:

```bash
npx skills add fulcradynamics/community-skills/<skill-name>
```

Or clone the repo and copy the skill folders you want into your agent's skills directory (e.g., `.claude/skills/` for Claude Code).

## Skills

| Skill | What it does |
|---|---|
| 🚦&nbsp;&nbsp;[fulcra-agent-coordination](#-fulcra-agent-coordination) | Presence, roles, reviews, and fleet health for multi-agent teams |
| 🧩&nbsp;&nbsp;[fulcra-computed-data-types](#-fulcra-computed-data-types) | Parse raw data exports into computed Fulcra data types |
| 📟&nbsp;&nbsp;[fulcra-harness-dashboard](#-fulcra-harness-dashboard) | Manager-facing view of an agent control harness |
| 📊&nbsp;&nbsp;[fulcra-project-dashboard](#-fulcra-project-dashboard) | Management dashboard for an agent-teams workspace |
| 🍖&nbsp;&nbsp;[fulcra-prototype-grill-me](#-fulcra-prototype-grill-me) | Strict six-step prototyping pipeline with a one-question-at-a-time intake |
| ⚡&nbsp;&nbsp;[fulcra-rapid-prototype](#-fulcra-rapid-prototype) | Scaffold and operate a project-specific Fulcra agent harness |
| 🗄️&nbsp;&nbsp;[fulcra-vault](#-fulcra-vault) | Durable shared markdown knowledge vault across all your agents |
| 🎬&nbsp;&nbsp;[fulcra-watch-together](#-fulcra-watch-together) | Recommend movies two people will both enjoy, from real viewing history |

## 🚦 fulcra-agent-coordination

`skills/fulcra-agent-coordination/`

A coordination layer over `fulcra-workspaces`: presence and liveness, durable roles with leases, resumable continuity, a review handshake, directed work with acks, and fleet health — folded deterministically by a vendored, stdlib-only engine.

**Contains:** `SKILL.md`, `README.md`, `ALIGNMENT.md`, `upstream-selection.json`, `references/`, `scripts/` (vendored engine)

## 🧩 fulcra-computed-data-types

`skills/fulcra-computed-data-types/`

Generates custom Python scripts that parse raw data exports and ingest them as computed Fulcra data types, dynamically tagging records by a data dimension you choose (artists, genres, categories, …).

**Contains:** `SKILL.md`, `README.md`, `examples/`, `templates/`

## 📟 fulcra-harness-dashboard

`skills/fulcra-harness-dashboard/`

Adapts `fulcra-project-dashboard` into a safe, manager-facing view for a task-specific agent control harness: milestone/PR timeline, run evidence, durable status summary, decision requests, escalations, and optional curated publication.

**Contains:** `SKILL.md`, `scripts/`, `templates/`

## 📊 fulcra-project-dashboard

`skills/fulcra-project-dashboard/`

Builds a management dashboard for an agent-teams workspace: progress, logs, a generated summary, timeline and milestone charts, and a word map of agent activities.

**Contains:** `SKILL.md`, `README.md`

## 🍖 fulcra-prototype-grill-me

`skills/fulcra-prototype-grill-me/`

Your agent acts as lead prototyping engineer and walks a strict six-step pipeline — Intake & Interview → Architecture → Plan → Prototype → Build → Retro — using a "grill me" intake that asks exactly one clarifying question at a time. State lives in a local git repository, backed up to your Fulcra file store via `git bundle`.

**Contains:** `SKILL.md`

## ⚡ fulcra-rapid-prototype

`skills/fulcra-rapid-prototype/`

Scaffolds a running, project-specific Fulcra agent harness (control loop, sandboxed tools, provider adapter), then operates it with an inspectable iteration discipline: immutable user-approved specs, separate generation and evaluation, milestone-sized loops, durable Fulcra Workspace state, and reviewable git/PR gates. Uses `fulcra-prototype-grill-me` for requirements gathering.

**Contains:** `SKILL.md`, `README.md`, `engine/`, `control_harness_templates/`, `templates/`, `scripts/`, `pyproject.toml`

## 🗄️ fulcra-vault

`skills/fulcra-vault/`

Manage a durable, Obsidian-like shared markdown knowledge vault in Open Knowledge Format (OKF), stored in Fulcra — persistent shared memory across all your agents.

**Contains:** `SKILL.md`, `references/`

## 🎬 fulcra-watch-together

`skills/fulcra-watch-together/`

Compares two consenting people's viewing histories and recommends movies both will enjoy. Consent and narrow sharing are part of the workflow, not an afterthought.

**Contains:** `SKILL.md`, `README.md`, `examples/`, `scripts/`

## Core skills

The foundational skills — connecting, memory, tracking, dashboards, workspaces — live in [fulcradynamics/agent-skills](https://github.com/fulcradynamics/agent-skills). Start there if you're new to Fulcra.

## Contributing

Open a PR adding your skill under `skills/<skill-name>/` with a `SKILL.md`. Skills here are community-maintained; each one documents what it reads and writes, and consent-gates anything that touches another person's data or installs recurring automation.

## License

MIT
