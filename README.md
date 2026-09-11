# community-skills

Community led skills for agents powered by the Fulcra platform and the core Fulcra skills in the agent-skills repo

**What this is:** community-contributed skills for AI agents connected to [Fulcra](https://fulcradynamics.com) — the personal data platform your agent reads and writes on your behalf.

**Who it's for:** anyone running an agent (Claude Code, or any agent that loads skills) who wants it to do more with their Fulcra data than the core skills cover.

**Install one skill:**

```bash
npx skills add https://github.com/fulcradynamics/community-skills/tree/main/skills/fulcra-project-dashboard
```

## Installation

Using the [skills CLI](https://github.com/vercel-labs/skills):

```bash
# one skill
npx skills add https://github.com/fulcradynamics/community-skills/tree/main/skills/<skill-name>

# all of them
npx skills add fulcradynamics/community-skills
```

Or clone the repo and copy the skill folders you want into your agent's skills directory (e.g., `.claude/skills/` for Claude Code).

## Skills

| Skill | What it does | Install |
|---|---|---|
| [fulcra-agent-coordination](skills/fulcra-agent-coordination/) | Presence, durable roles, resumable continuity, a review handshake, and directed work for several agents sharing one workspace | `npx skills add https://github.com/fulcradynamics/community-skills/tree/main/skills/fulcra-agent-coordination` |
| [fulcra-computed-data-types](skills/fulcra-computed-data-types/) | Turn a raw data export into a computed Fulcra data type, tagged by a dimension you choose (artists, genres, categories) | `npx skills add https://github.com/fulcradynamics/community-skills/tree/main/skills/fulcra-computed-data-types` |
| [fulcra-project-dashboard](skills/fulcra-project-dashboard/) | Build a management dashboard for an agent-teams workspace — progress, logs, timeline charts, and a word map of agent activity | `npx skills add https://github.com/fulcradynamics/community-skills/tree/main/skills/fulcra-project-dashboard` |
| [fulcra-rapid-prototype](skills/fulcra-rapid-prototype/) | Run a strict 7-step prototyping pipeline (intake → interview → architecture → plan → prototype → build → retro) | `npx skills add https://github.com/fulcradynamics/community-skills/tree/main/skills/fulcra-rapid-prototype` |

## Related

- **[fulcradynamics/agent-skills](https://github.com/fulcradynamics/agent-skills)** — the core Fulcra skills. Start there if you have not connected an agent to Fulcra yet; `fulcra-get-started` walks through the CLI, login, and setup.
- **[ashfulcra/fulcra-tools](https://github.com/ashfulcra/fulcra-tools)** — a live reference deployment. A working fleet of agents runs on these skills day to day, so the repo shows what the coordination skill looks like in sustained real use rather than in a demo.

## Contributing

Skills live in `skills/<skill-name>/` with a `SKILL.md` at the root. Match the shape of the existing ones — a `name` and a `description` in the frontmatter are what let an agent decide when to reach for your skill, so make the description say when it applies, not just what it does.
