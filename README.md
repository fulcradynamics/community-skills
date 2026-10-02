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
