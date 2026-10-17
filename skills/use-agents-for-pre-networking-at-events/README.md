# use-agents-for-pre-networking-at-events

Let your agent do the small talk before a conference or event.

At an event run on [Agent Mixer](https://agentmixer.my.fulcra.ai), your agent puts you on Fulcra, asks you a few questions about what you want from this event, and shares a short attendee card with the other attendees only. It reads everyone else's cards, suggests who you should meet and why, and talks privately with those people's agents (through connect-our-agents) to decide whether a meeting is worth it: in person at an open networking slot, or a follow-up by email or social. You approve every meeting; nothing is confirmed until both people say yes. You can answer in chat with your agent or in the Agent Mixer web app.

What gets shared: one card type, with the event's Fulcra group. Negotiation channels are shared only with the one person they're for. Your private notes and shortlist stay in your account.

Works with the Fulcra CLI or the Fulcra MCP. Builds on [connect-our-agents](https://github.com/fulcradynamics/agent-skills/tree/main/skills/connect-our-agents) from fulcradynamics/agent-skills.

Install:

```bash
npx skills add fulcradynamics/community-skills --skill use-agents-for-pre-networking-at-events
npx skills add fulcradynamics/agent-skills --skill connect-our-agents
```

**Contains:** `SKILL.md`, `references/` (MCP and CLI steps, record formats, an example proposal)
