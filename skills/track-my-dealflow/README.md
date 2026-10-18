# track-my-dealflow

An agent skill for [Track My Dealflow](https://track-my-dealflow.my.fulcra.ai), a free Fulcra app where content creators manage brand deals from pitched to paid.

Deals, contracts and payments live in the creator's own Fulcra account under `/track-my-dealflow/`. With this skill, the creator's agent runs the board for them:

- reads new contracts and pulls out the terms, with exact quotes
- keeps due dates, follow-ups and payment dates on their calendar
- sends the emails to brands that the creator approves
- watches their social accounts for posts and updates the deal
- answers questions like "What's due this week?" and "Who still owes me?"

## Requirements

- A Fulcra account, signed in at https://track-my-dealflow.my.fulcra.ai
- An agent connected to Fulcra (Claude, ChatGPT, or another MCP-capable agent)
- Optional: email, calendar and social access in the agent, for sending emails, calendar reminders and post tracking

## Setup

Install the skill:

```bash
npx skills add fulcradynamics/community-skills --skill track-my-dealflow
```

Or send your agent this once:

> Read the Track My Dealflow instructions at https://track-my-dealflow.my.fulcra.ai/agent.md and use them from now on to track all incoming deals, manage my deal flow and support my content creator business. Set up a scheduled task to check it twice a day.

The agent extracts and flags contract terms; it is not legal advice.
