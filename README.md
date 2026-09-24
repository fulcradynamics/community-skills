# community-skills

Community-contributed skills for agents powered by the Fulcra platform.

This repo is not maintained or reviewed to the same bar as the official
[fulcradynamics/agent-skills](https://github.com/fulcradynamics/agent-skills)
repo. Skills here are written and submitted by community members, may be
experimental, and may not be kept up to date. If you want the core, supported
Fulcra skills (connecting to Fulcra, tracking data, dashboards, agent memory,
workspaces, preferences), start with agent-skills instead.

## Skills

| Skill | What it does | Contributor |
|---|---|---|
| [fulcra-agent-coordination](skills/fulcra-agent-coordination/) | Coordination layer over fulcra-workspaces: presence and liveness, durable roles with leases, resumable continuity, a review handshake, directed work with acks, and fleet health, folded deterministically by a vendored, stdlib-only engine. | ashfulcra |
| [fulcra-app-starter](skills/fulcra-app-starter/) | Scaffolds a new project using one of the Fulcra web app template repositories for someone to build on top of using the Fulcra sign in / sign up flow and data back end. | Leif Meyer |
| [fulcra-computed-data-types](skills/fulcra-computed-data-types/) | Generates custom Python scripts to parse raw data exports and ingest them as computed Fulcra data types, dynamically tagging records by a specific data dimension (e.g., Artists, Genres, Categories). | Treecle |
| [fulcra-harness-dashboard](skills/fulcra-harness-dashboard/) | Adapts fulcra-project-dashboard into a safe, manager-facing view for a task-specific agent control harness: milestone/PR timeline, run evidence, durable status summary, decision requests, escalations, and optional curated publication. | early-access-leif-only-bot |
| [fulcra-project-dashboard](skills/fulcra-project-dashboard/) | Builds a management dashboard for an agent-teams workspace, showing progress, logs, a generated summary, timeline/milestone charts, and a word map of agent activities. | Treecle |
| [fulcra-prototype-grill-me](skills/fulcra-prototype-grill-me/) | Act as the lead prototyping engineer for Fulcra. Guides the user through a strict 6-step prototyping pipeline (Intake & Interview -> Architecture -> Plan -> Prototype -> Build -> Retro) using a Grill Me intake: ask exactly one clarifying question at a time. | early-access-leif-only-bot |
| [fulcra-rapid-prototype](skills/fulcra-rapid-prototype/) | Scaffold a project-specific Fulcra runtime harness and its separate control harness. Orchestrates fulcra-prototype-grill-me, one shared Fulcra Workspace, milestone/PR evaluation, and the recommended harness dashboard without duplicating those skills' detailed contracts. | schr3b3r |
| [fulcra-sister-cities](skills/fulcra-sister-cities/) | Run or facilitate Sister Cities, an asynchronous city-trade social game for 3-10 players. Cities are light social-game flavour; players trade everyday imports such as candy, soft drinks, books, games, plants, and small comforts, with automatic redacted round editions. | early-access-leif-only-bot |
| [fulcra-vault](skills/fulcra-vault/) | Manage a durable, Obsidian-like shared markdown knowledge vault using Open Knowledge Format (OKF) stored in Fulcra, enabling persistent shared memory across all agents. | Treecle |
| [fulcra-watch-together](skills/fulcra-watch-together/) | Compare two consenting people's viewing histories and recommend mutually appealing movies with Fulcra. | Treecle |

`fulcra-mesh` used to live here but has been promoted and moved to
[agent-skills](https://github.com/fulcradynamics/agent-skills/tree/main/skills/fulcra-mesh);
the folder in this repo is just a pointer to the new location.

Contributor names come from each skill's first commit in git history.

## Installation

The [skills CLI](https://github.com/vercel-labs/skills) installs every skill in
this repo into the current project, for Claude Code, Codex, Cursor and the
other agents it supports:

```bash
npx skills add fulcradynamics/community-skills -y
```

To install one skill for one agent, name both. The agent is the CLI's own
name for it, for example `claude-code`, not `claude`:

```bash
npx skills add fulcradynamics/community-skills -y -s fulcra-watch-together -a claude-code
```

The `fulcra-mesh` pointer folder is skipped automatically.

Or copy a skill by hand into your agent's skills directory (for example
`.claude/skills/` for Claude Code):

```bash
git clone https://github.com/fulcradynamics/community-skills
cp -r community-skills/skills/<skill-name> .claude/skills/
```

## Safety

Community skills run with your agent's permissions. They are not reviewed
the way agent-skills is. Read a skill's `SKILL.md` (and any scripts or
references it pulls in) before installing it, the same way you'd read code
before running it.

## Contributing

There's no CONTRIBUTING doc yet. To contribute a skill, open a PR that adds
`skills/<name>/SKILL.md` with at least `name` and `description` frontmatter,
following the shape of the existing skills in this repo.

## License

The repo has no top-level LICENSE file yet. Several skills declare a
license (MIT) in their own `SKILL.md` frontmatter; check the skill you use.
