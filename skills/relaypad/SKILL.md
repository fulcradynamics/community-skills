---
name: relaypad
description: "Relaypad: Lets a solo developer's coding agent and chat assistant pick up where the other left off, using one shared record of the day. for Freelance and indie software developers who use a coding agent in the terminal and a chat assistant for planning, every working day. Gives a useful first pass from what the person pastes, explains exactly which Fulcra data it would read, and asks before connecting, reading, saving or sharing anything."
homepage: "https://github.com/fulcradynamics/community-skills"
license: "MIT"
user-invocable: true
---

# Relaypad

Your chat assistant plans the day. Your coding agent starts already briefed. For freelance and indie developers. Relaypad keeps one daily record of your plan, open questions, ruled-out approaches and calendar limits, so your terminal coding agent reads it before it starts and leaves a short end-of-session note your chat assistant uses tomorrow morning.

## When to use this skill

Use it when the person is Freelance and indie software developers who use a coding agent in the terminal and a chat assistant for planning, every working day and wants help with this job: Lets a solo developer's coding agent and chat assistant pick up where the other left off, using one shared record of the day..

## How it works

1. **Plan the task with your chat assistant.** In the morning, talk through the task as you normally would. Your assistant writes a short brief: the goal, the deadline, open questions, approaches you already ruled out, and the calendar limits for the day. You review it before anything is saved to your own Fulcra account.
2. **Your coding agent reads the brief first.** Before it touches code, your terminal coding agent reads the saved brief through the Fulcra CLI or MCP server. It knows the client call is at three and that the caching approach was dropped yesterday, so it does not spend an hour rediscovering that.
3. **End the session with a handoff note.** When you stop, the coding agent records a short note: what changed, what is stuck, and what it would try next. The next morning your chat assistant reads that note and suggests the first job of the day. You can edit or delete any note.

## Rules

- Start with a useful first pass from what the person tells or pastes. Nothing needs to be connected for that.
- Before connecting to Fulcra, say exactly which data types or files and which time range you would read, and wait for a clear yes. The onboarding path is https://docs.fulcradynamics.com/agent-get-started.txt.
- Ask again before reading, saving or sharing anything new. Never book, pay, send messages or edit calendars; those stay the person's own actions.
- Group sharing in Fulcra is one way: the owner reads what members choose to share. Joining a group does not give anyone mutual access. Never invent a group link.
- Any example numbers you show are illustrative unless they come from the person's own data.

## The three prompts

Offer these in order. Each one is something the person can paste to their own agent.

### 1. First pass from pasted notes

```text
Here are my notes for today, pasted below: the task, the deadline, my meetings, and what I already tried. Turn them into a short brief for my coding agent with these headings: goal, deadline, calendar limits, ruled out, open questions, first step. Work out my focus hours before and after each meeting and show the sum. Do not save or send anything. Notes: [paste here]
```

### 2. Optional: connect Relaypad handoffs to my Fulcra account

```text
Read https://docs.fulcradynamics.com/agent-get-started.txt and explain in plain words what connecting to Fulcra would let you do for my daily handoff. Ask for my explicit permission before you connect, before you read any data such as my calendar events, before you save a brief or session note, and before you share anything. Only read the data I name. Do not read client folders, health data or personal notes unless I grant that.
```

### 3. Draft an invitation to a collaborator I can review

```text
Draft a short message I can review and send myself to a fellow developer who wants the same morning brief and end-of-session note setup. Include this starter prompt for their own agent: "Read https://docs.fulcradynamics.com/agent-get-started.txt, explain what Fulcra would do for my daily coding handoff, and ask my permission before connecting, reading, saving or sharing anything." Explain that their notes stay in their own account, and that if they later join a group I create, I as owner can read only the data types and time range they agree to, with no access for them to my data unless I share separately. Do not include any group link and do not send the message.
```

## Background

Positioning hypothesis, not a verified fact: general cross-tool memory layers for AI tools appear to exist, judging by the supplied page titles, but Relaypad would focus on one narrow daily ritual for solo developers, a reviewed morning brief with calendar limits and an end-of-session handoff note, stored in the developer's own account. The research session did not read these pages, so competitor features remain unverified.

- [Introducing OpenMemory MCP](https://mem0.ai/blog/introducing-openmemory-mcp): Observed source: a Mem0 blog post announcing OpenMemory MCP. The researcher noted from memory, unverified, that it is described as one memory layer shared by MCP tools such as Cursor and Claude Desktop.
- [AI Memory MCP Server for Claude Desktop Integration](https://mem0.ai/openmemory-mcp-3): Observed source: the page title presents OpenMemory as a memory MCP server integrating with Claude Desktop. Page contents were not summarised in the research session.
- [OpenMemory MCP that Works Across AI Tools](https://www.theunwindai.com/p/openmemory-mcp-that-works-across-ai-tools): Observed source: third-party coverage whose title frames OpenMemory MCP as working across AI tools, suggesting cross-tool memory is an existing category. Details unverified.

## Where this came from

This skill was drafted by Company OS from the Relaypad use-case mockup after two people approved it, and tested by the Fulcra surface testing session before launch. It is a starting point; edit it like any other community skill.
