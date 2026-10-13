---
name: whose-move-handoffs
description: "Whose Move: handoffs for Freelancers and small studio leads who pass work back and forth with clients and subcontractors. Gives a useful first pass from what the person pastes, explains exactly which Fulcra data it would read, and asks before connecting, reading, saving or sharing anything."
homepage: "https://github.com/fulcradynamics/community-skills"
license: "MIT"
user-invocable: true
---

# Whose Move

Know whose move it is on every client project Paste your project notes and threads. Your AI agent sorts every open handoff into two lists: what is waiting on you, and what you are waiting on from clients and collaborators.

## When to use this skill

Use it when the person is Freelancers and small studio leads who pass work back and forth with clients and subcontractors and wants help with this job: handoffs.

## How it works

1. **Paste what you already have.** Copy in project notes, email snippets or a chat export from your current client threads. No account or connection is needed for a first pass. Your agent reads only what you paste.
2. **Get two plain lists.** Your agent returns open handoffs split into waiting on you and waiting on others, with who, what and the last date mentioned in your notes. You check it, correct anything wrong, and decide what to send. Your agent does not message anyone for you.
3. **Keep the list between sessions, if you choose.** If you want the list remembered, your agent can connect to Fulcra with your permission and save handoffs as records in a custom data type you own. A studio lead can create a Fulcra group so collaborators who join share their own selected handoff records read-only with the lead. Members do not see each other's data.

## Rules

- Start with a useful first pass from what the person tells or pastes. Nothing needs to be connected for that.
- Before connecting to Fulcra, say exactly which data types or files and which time range you would read, and wait for a clear yes. The onboarding path is https://docs.fulcradynamics.com/agent-get-started.txt.
- Ask again before reading, saving or sharing anything new. Never book, pay, send messages or edit calendars; those stay the person's own actions.
- Group sharing in Fulcra is one way: the owner reads what members choose to share. Joining a group does not give anyone mutual access. Never invent a group link.
- Any example numbers you show are illustrative unless they come from the person's own data.

## The three prompts

Offer these in order. Each one is something the person can paste to their own agent.

### 1. First pass with pasted notes

```text
Below are my notes and message snippets from my current client projects. List every open handoff in two groups: waiting on me, and waiting on someone else. For each, give the project, the person, the task and the last date it was mentioned. Flag anything unclear instead of guessing. Do not draft or send any messages yet.

[paste notes here]
```

### 2. Optional: keep my handoff list in Fulcra

```text
Read https://docs.fulcradynamics.com/agent-get-started.txt. Explain in plain words what connecting to Fulcra would let you do with my handoff list and what it would store. Ask me before you connect, before you read anything, before you save any record, and before you share anything with anyone. If I agree, save each open handoff as a record in a custom data type I can review and delete.
```

### 3. Invitation for a collaborator to try it with their own agent

```text
Draft a short note I can review and send myself to a collaborator. It should say: I keep a list of who owes what on our projects with my AI agent. If you want the same, paste this into your own agent: "From my notes below, list what I owe on our shared project and what I am waiting on from others. Do not send anything." If you want your agent to keep that list, it can start here: https://docs.fulcradynamics.com/agent-get-started.txt. Nothing is shared with me unless you choose to join a group I set up, and then only the data you approve.
```

## Background

Positioning hypothesis: all-in-one freelancer tools appear to center on client portals, contracts and invoices. A narrow agent job that only tracks whose turn it is on each handoff, using notes the freelancer already has, may serve people who do not want another portal. This is untested.

- [HoneyBook Client Portal: Features, Limits, and Alternatives](https://fast.io/resources/honeybook-client-portal/): Third-party guide from a competing vendor says HoneyBook's client portal lets clients sign contracts, pay invoices, swap files, message in a project and see a timeline. Not confirmed by HoneyBook.
- [Best CRM for Freelancers: Streamline Sales & Relationships](https://www.honeybook.com/crm/freelancers): Observed HoneyBook page title positions its product as a CRM for freelancers focused on sales and relationships. Page contents were not retrieved.
- [Best Client Management Software for Freelancers (2026)](https://www.selfemployed.com/cliemt-mangagement-software-freelancers/): Observed title indicates a category of client management software aimed at freelancers. Page contents were not retrieved.

## Where this came from

This skill was drafted by Company OS from the Whose Move use-case mockup after two people approved it, and tested by the Fulcra surface testing session before launch. It is a starting point; edit it like any other community skill.
