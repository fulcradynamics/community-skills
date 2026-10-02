# fulcra-meeting-crm

Keeps a [`fulcra-vault`](../fulcra-vault/) CRM populated from meetings. Vault gives you
durable, versioned person notes; this decides who belongs in them and what to say, by
joining two records you already have:

```
calendar event  ──┐
                  ├── join on (date, title) ──► resolve person ──► upsert vault note
meeting summary ──┘
```

The calendar says **who** was in the room. The summary says **what** was discussed.

## What it fixes

A CRM that is only ever read cannot accumulate. The symptom is a briefing that opens
with the previous call instead of the coming one, while meeting summaries sit in a
mailbox next to a contact record that never hears about them.

## Install

```bash
cp config.example.json my-config.json   # fill it in
python3 scripts/meeting_crm.py --config my-config.json --calendar 2026-08-01 2026-09-01
```

Dry-run by default; `--live` writes. Read a dry run first.

Other flags: `--month YYYY-MM` (repeatable) selects collect shards, `--cache DIR`
sets the cache location (default `.meeting-crm-cache`), `--json` emits the run report
as JSON instead of text.

## Where summaries come from

Any mix of sources, all emitting the same [ingest format](references/ingest-format.md):

| source | use when |
|---|---|
| `fulcra_files` | a collection relay publishes approved emails to Fulcra Files |
| `mcp` | the agent hosting this skill has an MCP connection to a note-taker |
| `command` | you have a vendor API key or CLI |
| `file` | you already have exports on disk |

The `mcp` source is server-agnostic by construction. A script cannot speak MCP — the
connection lives in the agent runtime, not here — so the agent calls whatever tool it
has and emits normalized records, either through `bridge_argv` or into an `inbox`
directory. Nothing in this skill knows which server produced them.

### Getting summaries into Fulcra Files

If you want the relay-mediated posture but have no relay, there is a working Gmail
collector — it selects approved messages and writes them to Fulcra Files at a
deterministic path — in the **unofficial** community fulcra-tools repo:
<https://github.com/ashfulcra/fulcra-tools>, under `packages/gmail/`
(`collect_plugin.py`, `files_writer.py`). It is not an official Fulcra product, and it
is one method rather than the method: any process that writes records matching
[the ingest format](references/ingest-format.md) to the configured path will do.

## Credentials: pick your posture

- **Local connection** — the agent holds a vendor API key or MCP session. Simple, but
  the agent is then authenticated as the user against a system that can read far more
  than meeting summaries, and every agent run this way is another copy of that
  credential.
- **Fulcra Files** — a relay running under the user's own authority publishes only
  approved summaries, and the agent reads those. *If* the credential you give this
  skill is scoped to those published files and nothing else, the agent holds no
  session against the meeting source at all, its reach is exactly what the relay
  published, and narrowing the relay narrows every agent downstream without
  redeploying any of them. That scoping is a property of the deployment, not of
  this code: the engine invokes whatever `fulcra-api` credential you configure and
  cannot establish its principal or scope. Grant it a narrow one — the posture is
  worth nothing if the credential behind it is broad.

Both are supported, and they compose: configure both and records are merged, keeping
the richer summary per meeting. The trade-off in full is under "Two deployment modes"
in [SKILL.md](SKILL.md).

## Not tied to any note-taker

Nothing in the engine knows a vendor. How a summary mail is recognised, how its title
is cleaned, and how the sharer is identified are all regex lists in `config.detection`
with vendor-neutral defaults. Otter, Fireflies, Granola, Gong, Read.ai and plain
human-written recaps go through the same three patterns; a service the defaults miss
is a config change, not a code change.

## The attendee rule

**Attendees come from the calendar, never from the summary email.** That mail is sent
by whoever *shared* the notes, and its prose names only the people it happens to
mention. Across a 61-meeting corpus, taking the sender as a participant attributed one
sharer to 41 meetings while the actual counterparties never appeared at all.

Calendar invitees carry real addresses, which also gives the right match key: email
first, then name. A source may supply `attendees`, but they are advisory unless the
record declares `attendees_authoritative`.

## Safety

The loop refuses to guess at identity, because a wrong write is self-reinforcing: a
bad note wins subsequent resolution and hides the real one. It never creates a person
from a single-token name (`barrie@` → "Barrie"), never creates when resolution is
ambiguous, never writes a robot address onto a human, skips meetings above
`limits.max_attendees`, and refuses to run on a `fulcra-api` older than
`cli.min_version` — a stale CLI surfaces as *missing data*, not as a broken tool.

When it cannot identify someone confidently it records nothing. A missing note is
recoverable; a forked identity is not.

Each of those guards was added after that failure corrupted real data. The nine
stories, with the numbers, are in [references/design-notes.md](references/design-notes.md).

## Files

```
SKILL.md                      what it is, when to use it, deployment modes
README.md                     this file
config.example.json           full config schema, commented
scripts/meeting_crm.py        the engine (no machine-specific paths)
references/ingest-format.md   THE CONTRACT — the record every source emits
references/design-notes.md    why each guard exists
```

## Provenance

Extracted from a working Arc deployment and generalized: nothing user-, machine- or
account-specific remains in the skill. All of that lives in config or the environment.
