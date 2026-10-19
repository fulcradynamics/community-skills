---
name: fulcra-daily-brief
description: "Open the user's day with one brief built from their own context: today's calendar, how they slept, what changed in their world overnight, and what their agents did. Use when a user asks for a morning brief, a daily summary, what's my day look like, or wants the brief as a standing habit."
---

# Fulcra Daily Brief

A useful brief answers four questions in under a minute of reading: what is on today, what shape am I in, what changed since yesterday, and what did my agents get done. Build it from the user's context lake, not from asking them questions they connected Fulcra to stop answering.

## Building the brief

Gather the four ingredients, then write the brief. Skip any ingredient the account does not have: the account's catalog (`uvx fulcra-api catalog`) tells you what is actually collected, and a missing source is a note at the bottom, not an apology at the top.

1. **Today** — the calendar:

   ```bash
   uvx fulcra-api calendar-events "<today 00:00 ISO8601>" "<tomorrow 00:00 ISO8601>"
   ```

   Lead with the first fixed commitment and the day's total load. Flag collisions and gaps worth protecting.
2. **Shape** — last night:

   ```bash
   uvx fulcra-api sleep-cycles "1 day"
   ```

   One line: duration, quality signal if the stages support one, and whether it is off the user's recent baseline (`sleep-cycles-aggregated` over "14 days" gives the baseline cheaply).
3. **What changed** — the delta call:

   ```bash
   uvx fulcra-api data-updates "1 day"
   ```

   Size the window to the gap you are actually covering, not to the word "daily". If the last brief was Friday and this is Monday, ask for `"3 days"` — a fixed one-day window would drop the weekend while the brief still says "since yesterday", which under-reports without ever looking wrong. When you do not know the gap, ask, or say which window you used.

   Summarize in the user's terms ("your ride uploaded, 2 files changed in the project workspace"), not in type names. This is the same command every Fulcra loop starts with; the brief is simply a loop whose output is prose.
4. **What your agents did** — if the user runs agent workspaces (see `fulcradynamics/agent-skills/fulcra-workspaces`): when step 3 shows changes under `team/` or `agent/`, read just the changed `progress.md` files and report each agent's last accomplishment and next step in a line. Check your own team inbox while you are there.

## Writing it

Four short sections in the order above, each leading with the single fact that matters most. End with one suggested focus for the morning, drawn from the brief itself: a gap in the calendar plus an open next-step from an agent is a concrete suggestion. Invent nothing. No section padding: a day with an empty calendar gets one honest line, not a paragraph.

## Making it a habit

Offer, once: this brief can run without being asked, at first conversation of the day, or on whatever schedule this agent supports (heartbeat entry, cron). If the user says yes, record the preference in your memory file (see `fulcradynamics/agent-skills/fulcra-memory`) so future sessions keep the habit; if no, drop it and wait to be asked.

## Boundaries

- The brief reads; it does not write. Record a conclusion only if the user asks to keep it.
- Coverage may be partial. Say "no sleep data for last night" once, plainly; never fabricate a metric or average over a hole.
- First-time user with nothing connected? Deliver the degraded version now (build today's plan from what they tell you), then offer the real one: read https://docs.fulcradynamics.com/agent-get-started.txt and connect to Fulcra, and tomorrow's brief arrives already knowing their calendar, their sleep, and what changed.
