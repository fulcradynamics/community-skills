# M5 — the newspaper's rendering core

Spec #25 (the *sentence*, where M4 supplied the arithmetic), #28, #29 and #30.
The engine states facts; this milestone is the first that publishes English.

| # | Rule | Where it is settled |
| --- | --- | --- |
| #25 | aggregate answers written in "clever" ways — and *true of the distribution* | `newspaper/wire.py`, licensed by `engine/aggregate.py` |
| #28 | mayors named by city and office only, never a real name or handle | `newspaper/redact.py` + `newspaper.player_identity_style` |
| #29 | one image per edition; raster preferred, deterministic SVG an allowed fallback | `newspaper/imagery.py`, `newspaper/svg.py` + `newspaper.image.*` |
| #30 | funny, colourful, pointed-but-not-mean | `content/newspaper.json` + `newspaper/tone.py` + `newspaper.tone.*` |

Hosting is **not** here. Serving these editions at a fixed, unguessable,
non-publicly-discoverable URL with the archive browsable (#26, #27) is M6's
separate integration boundary — see [`docs/m6-hosting.md`](m6-hosting.md) —
and `newspaper/publish.py` deliberately stops at the filesystem.

## The shape of it

```
python3 run_tests.py                     # 350 tests, standard library only
newspaper.build_edition(engine, round)   # one edition, checked
newspaper.build_archive(engine)          # every edition, oldest first (#27)
newspaper.publish.publish_game(engine)   # ... written to editions/<label>/
```

A rendered sample game — twelve editions, all three resolution paths, every
aggregate outcome the ladder can select — is committed at
[`editions/sample-game/`](../editions/sample-game). `index.md` is the archive
index; each round has its prose (`.md`), its structured payload (`.json`) and
its image (`.svg`).

The paper is assembled from frames in `content/newspaper.json`, not from string
literals in Python. That file is content for the same reason the phrasing ladder
is: which words the paper uses is a writing decision. `newspaper/copy.py` loads
it and owns the three mechanical decisions — which frame, whether tone policy
permits it, and whether it filled. A frame with an unfillable `{placeholder}` is
a failure to publish rather than a brace on the page.

Frame selection is deterministic, keyed on the round's own facts rather than on
a counter or a random number: two mayors reading the same edition must read the
same words, and a game replayed from its seed must produce the paper it produced
the first time.

## Why an edition can refuse to publish

`Paper.edition` is the only place that decides an edition does not ship, and it
decides three ways — over the *rendered markdown and the image*, not just the
structured payload, because a leak that exists only in the prose is still in the
paper:

- **Redaction** (#21, #22, #25, #28) — a handle, a player id, a losing export's
  origin, or anything `config.json` says to withhold. Handles are checked as
  substrings on a word boundary, because a sentence is exactly where a handle
  would end up; `engine.audit` is reused rather than reimplemented.
- **Tone** (#30) — `content/newspaper.json`'s forbidden register, run over the
  finished prose *and* the image's cutline, since a caption is as published as
  the copy.
- **Filling** — see above.

A losing export is reprinted only if its own text names no city in the game. A
mayor who signs their work would otherwise leak their origin as thoroughly as
printing a field would, so the paper withholds that one and says, in character,
that it has.

## The two things #25 is judged on, and how each is prevented

The judged criterion is not whether the sentence sounds clever. It is whether it
is **true of the distribution it describes** — "present-looking language over an
actually-wrong aggregate" is an explicit fail. Two mechanisms, because there
turned out to be two ways to fail it:

**The claim.** `newspaper/wire.py` may use no wording `engine.aggregate` has not
licensed for the actual counts. `choose_phrase` draws only from the outcome's
`phrases` (true of *every* distribution that can select that outcome) and from
`conditional_phrases` the ladder marked licensed; `assert_licensed` re-checks
after the fact, so a future frame that interpolated its own aggregate language
would raise rather than publish. One branch per outcome kind, because the
*grammar* differs — a tier has one leading bucket, a tie exactly two, a
fragmented world no leader at all, and the floor no shape to describe.

**The heading.** Every question's `newspaper_hook` in `content/questions.json`
is written at world scale — "Contents of the world's desks" — because that is
how the column reads when there *is* an aggregate. It is therefore only usable
when the item makes a licensed aggregate claim. Over an empty postbag, or over
the one or two replies of the low-respondent floor, the hook is precisely the
judged failure: aggregate language in the headline above a body that then says
the paper cannot speak for the world. `wire.licenses_aggregate_heading` gates
it, and those rounds are headed after the postbag instead ("From the postbag"),
claiming nothing about it. `provenance.aggregate_heading_used` records which
happened.

A related trap, since fixed: a ladder phrase is a **fragment**, and the frame it
lands in decides its case via `{phrase}` or `{Phrase}`. Selecting it with a
method that sentence-cases lines took that choice away from the frame and
printed *"And then One lone municipality, from the Mayor of Bergen"* — a capital
mid-sentence. `Chooser.pick` now returns frames verbatim and is what fragments
are chosen with; `Chooser.rotate`/`line` fill and sentence-case, and are for
things that are themselves sentences.

## The image (#29)

`newspaper/imagery.py` resolves the modality in the order
`newspaper.image.modality_preference` asks for, and does three things it refuses
to fudge:

1. **Raster is genuinely preferred**, not preferred on paper. A registered,
   available provider wins; the test suite registers a stub to prove the
   preference order is real rather than documented.
2. **No silent downgrade.** Naming a provider that is not registered is a
   `ConfigError`. A typo must not present as "we tried raster and it wasn't
   there."
3. **The actual modality and provider are recorded**, per provider considered,
   with the reason, in each edition's own `image.provenance` — and in the
   publish manifest.

This deployment configures no provider, so every edition here falls back to
`svg_procedural` via `builtin_svg` and **says so in as many words** rather than
quietly shipping an SVG that looks like a choice. Adding a raster provider is an
adapter with `available()` and `generate()`, registered and named in config;
nothing else changes, because the SVG stays last in the preference list, which
is what makes it a fallback rather than a default.

The fallback is materially informed by the edition, which is the substantive
half of #29's clause (the deterministic half is free): the crates on the quay
are that round's offers and the ribboned one is its winner, the dice are its
actual roll, the skyline is the live standing, the pennants overhead are one per
reply to the mayor question, and the stamp is the need's category. Ballot
positions are used, never exporter identity. Every edition also carries alt
text, built in code rather than content because it describes the drawing and
should not be revisable independently of it.

## The four tone flags are load-bearing

Spec #30's judged half is the Evaluator's. The mechanical floor is a register of
words whose only job in a sentence is to attack somebody, and it lives in
content because which words are out of bounds is an editorial decision. Passing
it does not mean an edition is kind; it means the edition does not contain the
vocabulary that is never kind.

The other three flags are honoured for real rather than echoed, and there is a
test that renders the whole paper with all four off:

| flag | false does what |
| --- | --- |
| `funny` | drops the editorial asides; the paper reports facts |
| `colorful` | switches the edition image to the monochrome palette |
| `allow_pointed_humor` | drops every frame content marks `pointed` |
| `disallow_snide_or_mean` | stops blocking publication on the register |

A frame is "pointed" when the joke has a target that is an institution, a
decision, or the paper itself. A joke whose target is a person is not pointed,
it is mean, and it does not belong in the content file at any setting. Every
family keeps at least one unpointed frame, so nothing is left with nothing to
say when the flag is off — that is enforced, not merely intended.

## One engine change this milestone needed

An edition is a historical document: round 3's paper must go on saying what
round 3's table was, however the game ends (#26, #27). So `RoundRecord` now
carries a `standings` snapshot, frozen once when the round's lockstep finishes,
and `views.newspaper_leaderboard(engine, round_index)` prefers it over the live
table. Without it, an archive rendered from a finished game prints the closing
table twelve times, which is the failure
`test_the_standing_printed_is_that_round_s_standing_not_the_final_one` exists to
prevent. The exposure decision (#22) is still taken in exactly one place.

`engine/views.py` also now carries the need's `category_label` and
`exporter_prompt` (both already public — the prompt is shown to every exporting
mayor at check-in) and a city-only `roster`, so the paper reads views rather
than engine internals and every consumer sees the same redaction decisions taken
in one module. The `[[M5 ...]]` stubs the engine used to carry are now replaced
by the name of the thing that renders each piece; the remaining `[[M6 ...]]`
stub was hosting, and M6 replaced it with the name of the thing that serves it.
