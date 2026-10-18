---
name: track-my-dealflow
description: "Use when a content creator asks about their brand deals, contracts, what's due, who owes them, or anything in Track My Dealflow (track-my-dealflow.my.fulcra.ai)."
homepage: "https://track-my-dealflow.my.fulcra.ai"
repository: "https://github.com/fulcradynamics/community-skills"
license: "MIT"
user-invocable: true
metadata: { "openclaw": { "emoji": "💼" } }
---

# Track My Dealflow

Track My Dealflow keeps a creator's brand deals in their own Fulcra account. You (the creator's agent) read and update everything with the Fulcra tools (list_files, read_file, write_file). All files live in `/track-my-dealflow/`. The creator sees every change in the app at https://track-my-dealflow.my.fulcra.ai.

Your role: track all incoming deals, manage the creator's deal flow and support their content creator business. The latest full instructions are always at https://track-my-dealflow.my.fulcra.ai/agent.md (and in `/track-my-dealflow/AGENT.md`); if they differ from this skill, follow them.

Only change what the creator asked for. Never delete a deal unless they say so.

## First: set up a twice-daily check

The first time you use this skill for a creator, set up a scheduled task so you check twice a day without being asked:
- Ask what times suit them, or use 9am and 4pm in their time zone.
- Task prompt: "Check Track My Dealflow: read new contracts, sync calendar reminders, send approved emails in the outbox, look for new posts, and tell me what's due and who still owes me." Include the agent.md link so a fresh session can find the instructions.
- Tell them when it's set and how to change or stop it.
- If you can't create scheduled tasks, say so plainly and suggest a reminder to ask you twice a day.

## The board: deals.json

```json
{ "version": 1, "deals": [ {
  "id": "unique id (never change it)",
  "brand": "Juice Lab", "fee": 1200,
  "stage": "Pitched | Negotiating | Signed | In progress | Posted | Invoiced | Paid",
  "terms": "Net 30 after posting",
  "deliverables": [{ "what": "1 TikTok", "due": "YYYY-MM-DD", "done": false }],
  "usageRights": "...",
  "exclusivity": { "text": "...", "until": "YYYY-MM-DD" },
  "brandContact": { "name": "...", "email": "..." },
  "lookFor": "brand handle or hashtag",
  "followUp": "YYYY-MM-DD", "paymentDue": "YYYY-MM-DD",
  "status": "reading (only while a contract waits to be read)"
} ] }
```

Read it, edit it, write the whole file back, keeping every field you didn't change. New deals need a new unique id.

Answer from it: what's due this week, who still owes money (stage Posted or Invoiced), what's been paid, and whether a new offer clashes with an exclusivity window.

## Reading a contract

When the creator drops in a contract, the app adds a deal with `"status": "reading"` and saves `contracts/<id>.pdf` and `contracts/<id>.txt`. For each reading deal with no inbox file, read the .txt and write `inbox/<id>.json`:

```json
{ "brand": "", "fee": 0, "stage": "Signed", "terms": "",
  "deliverables": [{ "what": "", "due": "" }],
  "usageRights": "", "exclusivity": { "text": "", "until": "" },
  "quotes": { "fee": "exact sentence", "terms": "", "usageRights": "", "exclusivity": "", "deliverables": [""] },
  "flags": ["anything to double-check, in plain words"] }
```

- Quotes are copied word for word from the .txt; the app checks them. Leave a field empty rather than guess.
- Fees are numbers in US dollars; use "" for a date the contract doesn't give.
- Don't edit deals.json for a contract: the creator confirms your inbox file in the app.
- You flag terms; it isn't legal advice. Say so if asked.

## Calendar reminders

If `reminders.json` has `"on": true` and you can reach their calendar: one all-day event per reminder titled "Dealflow: <title>", alert `daysBefore` days ahead (on the day if 0). Record events in `calendar-sync.json` (`{ "syncedAt", "calendar", "events": { "<reminder id>": "<event id>" } }`). On later syncs add, move and delete only events listed there. If `"on"` is false, delete those events and empty `events`. No calendar access: tell them once.

## Emails to brands

For each `outbox/<id>.json` with `"status": "ready"` and no `<id>.sent.json`: send exactly that email (same to, subject, body) from the creator's own email, then write `<id>.sent.json` with `{ "sentAt" }` or `{ "error" }`. Skip `"cancelled"`. Never email a brand anything the creator didn't approve this way. Can't send email: say so.

## Watching for posts

The app can't watch social accounts; you do, with whatever access you have. If `settings.json` has `"posts": { "track": true }`:
- Check the handles in `settings.json` `socials` for posts since `posts.json` `checkedAt`.
- Match posts to unpaid deals by `lookFor`, brand name and #ad / paid-partnership labels. Unsure: ask.
- Add matches to `posts.json` (`dealId, url, platform, postedAt, views?, likes?`), never the same url twice; set `checkedAt`.
- Move the deal to Posted if earlier and mark the deliverable done.
- If `"autoShare": true` and the deal has a brand email, write an outbox file with `"kind": "post"`, `"approvedBy": "auto-share setting"`, the link and a short friendly note, then send it as above. Only post-is-live emails, never anything else.
- Can't see a platform: say so once.

## Deals brands share

Brands on Fulcra can share a folder with the creator; those deals show read-only on the board. Read them with list_shares and read_file with the brand's fulcra_userid; include them in answers but never change them.

## What the creator might say

- "Read my new contract in Track My Dealflow"
- "What's due this week?" / "Who still owes me?"
- "Move Juice Lab to Posted" / "Add a $500 deal with Snack Club"
- "Does this new offer clash with any of my exclusivity deals?"
- "Sync my reminders to my calendar"
- "Send anything waiting in my outbox"
- "Check my socials for new posts"
