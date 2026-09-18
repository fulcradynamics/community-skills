---
name: fulcra-meeting-crm
description: Keep a Fulcra Vault CRM populated automatically from meetings — the calendar supplies WHO attended, meeting-summary emails from any note-taker supply WHAT was discussed, and the two are joined and written to person notes. Use when a user wants briefings that remember prior conversations, wants a CRM that fills itself instead of being hand-maintained, or asks why their meeting notes never reach their contact records.
---

# Fulcra Meeting CRM

A read-write loop on top of the **`fulcra-vault`** skill. Vault gives you durable,
versioned person notes; this skill decides **who belongs in them and what to say**.

```
calendar event ─┐
                ├─► join on (date, title) ─► resolve person ─► upsert vault note
summary email ──┘
```

## When to use it

- The user's briefings have no history ("you just briefed me for the PREVIOUS call").
- A CRM exists but only ever gets read — nothing writes back, so it cannot compound.
- Meeting summaries arrive by mail but never reach any contact record.

## The one rule that makes it work

**The calendar is the attendee authority. The summary email is the content.**

Do not take attendees from the summary email. That mail is sent by whoever *shared*
the notes, and its prose only names people it happens to mention. In a real
61-meeting corpus this attributed **one sharer to 41 meetings** while the actual
counterparties never appeared at all. Calendar invitees carry real addresses, which
also gives you the correct match key: **email first, then name.**

## Safety invariants — do not weaken these

These exist because each one corrupted real data before it was enforced.

1. **Never create a person from a single-token name.** `barrie@…` → "Barrie" collides
   with an existing "Barrie Segal" and, once written, *poisons resolution* so the real
   note is never found again.
2. **Never create a person when resolution is `ambiguous`.** Ambiguous means several
   candidates matched; minting a new note there forks an identity that already exists
   more than once.
3. **Never write a robot address onto a person.** `no-reply@otter.ai` paired with a
   human's display name is the default shape of these emails.
4. **Skip mass meetings.** A 50-person all-hands is not a relationship event; writing a
   note per invitee buries real counterparties in noise.
5. **Dry-run first, always.** Then verify no junk-titled notes were created before the
   next run.

When an attendee cannot be identified confidently, record nothing. A missing note is
recoverable; a wrong or duplicated identity is not.

## Usage

```bash
python3 scripts/meeting_crm.py --config <config.json> --calendar 2026-08-22 2026-08-30
python3 scripts/meeting_crm.py --config <config.json> --calendar 2026-08-22 2026-08-30 --live
```

Dry-run by default. `--live` writes. See `config.example.json` for the config schema,
`references/ingest-format.md` for the record every source must emit, and
`references/design-notes.md` for why each guard exists.

## Two deployment modes — and why you might not want the direct one

The skill runs either way. The difference is **whose credentials the agent holds.**

### A. Local connection (agent-held)

The agent talks to the meeting source itself — a vendor API key, or an MCP
connection in the bot it runs inside — via a `command` or `mcp` source. Nothing
transits Fulcra.

- Fewest moving parts, lowest latency, works offline from Fulcra entirely.
- **But the agent is now authenticated as the user** against Otter/Gmail/etc. It
  holds a credential that can read far more than meeting summaries, and every
  agent you run this way is another copy of that credential.

### B. Fulcra Files (relay-mediated)

A collection relay — running under the user's own authority, not the agent's —
selects the emails the user has approved and writes them to Fulcra Files at a
deterministic path. The agent reads only that.

- **Given a credential scoped to the published files, the agent holds no session
  against the meeting source at all** — no Otter session, no mailbox access, no
  vendor API key — and its reach is exactly the summaries the relay chose to
  publish. That scoping is yours to enforce when you configure the credential:
  this skill invokes whatever `fulcra-api` you hand it and cannot verify what
  that credential can reach.
- The relay's selection is auditable and revocable centrally: narrow what it
  publishes and every agent downstream narrows with it, with no agent redeployed.
- Payload paths are deterministic and content-addressed, so re-ingest is
  idempotent and a crashed run cannot duplicate records.
- Costs an extra hop and a relay to operate.

**Prefer B when more than one agent needs the data, when the agents are not all
equally trusted, or when you would rather not have a user-scoped mailbox
credential sitting in an agent's environment.** Choose A for a single agent under
the user's direct control, or where no relay exists.

The two are not exclusive — configure both and records are merged, keeping the
richer summary per meeting.

## Configuration

Nothing about a particular user, machine, or account belongs in this skill. All of it
comes from a config file or environment. See `config.example.json`.
