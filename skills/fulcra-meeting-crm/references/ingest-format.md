# The ingest format

This is the contract. Everything else in this skill is an adapter around it.

A source — Fulcra Files, an MCP connection in the host agent, a vendor API, a
dumped file — is only required to emit **meeting summary records** in this shape.
Get this right and the source stops mattering.

## Record

```json
{
  "schema":      "meeting-summary/1",
  "title":       "Weekly 1:1 Ash & Tin",
  "date":        "2026-08-28",
  "summary":     "Christine and Elizabeth discussed automating the research workflow…",
  "source":      "otter",
  "external_id": "1a04a16bbbcd47a5",
  "shared_by":   "Michael Tiffany",
  "attendees":   [{"name": "Christine Acoba", "email": "christine@example.com"}],
  "url":         "https://otter.ai/u/…"
}
```

### Required

| field | rule |
|---|---|
| `title` | Non-empty. The meeting's name, **not** the email subject line. Strip `Meeting Summary for …` prefixes and any tracking URL the vendor appended. |
| `date` | `YYYY-MM-DD`, **the day the meeting happened** — not the day the mail was sent. Vendors routinely send at 03:00 the next morning; using the send date makes the join to the calendar miss entirely. |
| `summary` | The prose. May be empty, must be present. Strip tracking links. |

### Optional

| field | meaning |
|---|---|
| `schema` | `meeting-summary/1`. Absent is treated as v1. |
| `source` | Provenance label (`otter`, `fireflies`, `gmail-relay`). Ends up in the note's log line. |
| `external_id` | Stable per-meeting id, scoped to `source`. Supply both and re-ingesting is idempotent. Ids are treated as provider-local — Otter's `123` and Fireflies' `123` are different meetings — so an id without a `source` dedupes only against other sourceless records. |
| `shared_by` | Who shared the notes. **Provenance only — never an attendee.** See below. |
| `attendees` | Advisory. See below. |
| `action_items` | List of strings, or `{owner, task}` objects. |
| `url` | Link back to the source record. |

## Two rules that are easy to get wrong

**1. `shared_by` is not an attendee.** Meeting-summary mail is sent by whoever
shared the notes — `"Christine Acoba via Otter.ai" <no-reply@otter.ai>`. Treating
that sender as a participant attributed **one person to 41 of 61 meetings** in a
real corpus. Record them as provenance so the information is not lost, and never
let them reach the CRM as an attendee.

**2. `attendees` is ADVISORY, always.** The calendar is the attendee authority,
because invitees carry real addresses. A source that derives attendees from prose
is guessing, and its guesses are wrong in a specific, damaging way: it names the
people the summary happens to mention and silently omits the counterparties the
CRM exists for. Supply `attendees` if you have it — it is used to enrich a
calendar-matched person — but the loop must never depend on it.

If your source genuinely has authoritative invitee data (a calendar-aware API),
say so with `"attendees_authoritative": true` and it will be trusted for emails.

## Tolerated aliases

To keep adapters trivial, these are accepted and normalized:
`subject` → `title`; `text` / `notes` → `summary`; `start` / `created_at` → `date`;
`participants` → `attendees`; a bare string in `attendees` is read as an email if
it contains `@`, else as a name.

A raw collected email (`{headers, bodies, …}`) is also accepted and parsed, which
is what the `fulcra_files` adapter passes through.

## Emitting it

Any of: a JSON array, a single JSON object, or JSON-lines. All three are accepted
from every adapter, so `jq`, a shell loop, or an agent writing one file per meeting
all work without ceremony.
