# Design notes — why each guard exists

Every rule below was added *after* it corrupted real data in a live 320-person CRM.
None of them are theoretical. If you are tempted to relax one, read its story first.

## 1. The calendar is the attendee authority, not the summary email

Meeting-summary mail (Otter, Boardy, Fireflies) is sent by **whoever shared the notes**,
in the shape `"Christine Acoba via Otter.ai" <no-reply@otter.ai>`. Two failures follow:

- Treating the `From:` sender as a participant attributed **one person to 41 of 61
  meetings** in a single month, including meetings they did not attend.
- The prose only names people it happens to mention, so the real counterparties
  (the external people the CRM exists for) never appeared at all.

Calendar invitees carry real addresses in `participants[].url = "mailto:…"`. That gives
both the correct attendee set *and* the correct match key.

**Record the sharer as provenance, never as an attendee.**

## 2. Name/email pairing in summary mail is unreliable

A naive token parse of that `From:` header produces
`{"name": "Christine Acoba", "email": "no-reply@otter.ai"}` — a real human bound to a
robot address. Written to a CRM, that address becomes their contact detail forever.

Observed independently: one corpus paired a person's name with a *different* person's
address. **Treat the email as the key and the name as a hint, never the reverse.**

## 3. Dedupe on the person, not on whichever field is present

Keying dedupe on `email or name` splits one human into two records whenever they appear
once with an address and once without. Merge on the normalised name and let a real
address win over a blank one.

## 4. "A and B discussed…" — the opener that drops attendees

A pattern requiring `X discussed … with Y` silently misses the far more common
`Alice and Bob discussed …`. The second attendee vanishes from **every** such summary.
This is easy to miss because the pipeline reports success: it found *an* attendee.

## 5. Never create a person from a single-token name

`barrie@company.com` yields "Barrie". Creating `Barrie.md` beside an existing
`Barrie Segal.md` does more than duplicate — the new note **wins subsequent
resolution**, so the real note with all its history is never found again. A bad write
here is self-reinforcing.

First-name-only work addresses (`brad@`, `greg@`, `mjjt@`) are the common case.
**Record nothing rather than guess.** A missing note is recoverable; a forked identity
is not.

## 6. `ambiguous` is not `none`

This one defeated two earlier guard attempts. A resolver returning `ambiguous` means
*several* candidates matched — precisely when creating a new person is most harmful,
because the identity already exists more than once. A guard that only checks for "no
match" sails straight past it.

**Treat `ambiguous` exactly like `none` for creation, and never enrich on it either:
you do not know which person you would be enriching.**

## 7. Mass meetings are not relationship events

A 50-person all-hands and a 16-person board meeting produce 66 CRM writes that bury the
handful of real counterparties. Cap by attendee count.

## 8. Verify writes by reading the store back

`upsert` returning without an exception is not proof. Read the people directory after a
live run and look for junk titles — lowercase names, raw email local-parts. Three
separate rounds of malformed notes were caught this way and only this way.

## 9. Truncated output reads exactly like absence

A `list | head -8` hid a file that existed and led to a confident report that it was
missing; the real fault was a stale CLI crashing. Related: a stale client crashing on a
changed API shape surfaced as `download failed for <path>`, which reads as "file not
found". **A traceback in stderr is never a missing file.** Check the tool before
concluding anything about the data.
