# M4 — the facilitator question mechanic

Spec #23, #24, and the *data* side of #25. Three things:

| # | Rule | Where it is settled |
| --- | --- | --- |
| #23 | a check-in has two slots: pending game actions first, then one question | `GameEngine.checkin` + `facilitator_questions.{enabled,ask_every_n_rounds,max_per_player_per_round,fill_second_slot_only_if_no_second_game_action_pending}` |
| #24 | freeform getting-to-know-you questions, framed to/about *the mayor* | `content/questions.json` + `facilitator_questions.{scope,framing}` |
| #25 | what the answers add up to — "the world", "some countries" | `engine/aggregate.py`, driven by the ladder in `content/questions.json` |

The prose is not here. #25 says the answers are phrased in clever aggregate ways,
and the harness judges that on whether the phrase is *true of the distribution*
— present-looking language over an actually-wrong aggregate is a fail. So this
milestone decides which aggregate is true, arithmetically, and hands M5 the
outcome plus the wordings that outcome licenses. Nothing in `engine/aggregate.py`
returns a sentence.

## The two slots

```
GameEngine.checkin(player_id) -> {"slots": [slot | None, slot | None], ...}
```

Slot 1 is a pending game action if one exists. Slot 2 is a *second* pending game
action if one exists, and otherwise the round's mayor question.

The load-bearing subtlety, already settled in M2 and re-tested here: "pending"
means pending *for the round*, not "still undone right now". If it meant the
latter, a mayor who submitted their export first would then be offered a
question, and answering it would consume the slot their still-outstanding winner
pick needed — so a mayor who did things in the wrong order would lose their
pick, and the round would fall through to spec #19's even split. The slot set is
therefore fixed when the round opens; `checkin` only omits the ones already
used.

`fill_second_slot_only_if_no_second_game_action_pending: false` un-gates it, and
then a mayor can be offered all three. That is what switching it off means.
`max_per_player_per_round` accepts 1 (ask) or 0 (suppress for this mayor while
the round's question still goes to everyone else) and *refuses* 2 rather than
silently capping it — spec #23 gives a mayor two slots of which at most one is a
question, so a config asking for two is a mistake worth surfacing.

## What makes a question legitimate (#24)

One question per round, asked of every mayor — not a different question each,
because an aggregate can only describe a distribution if everyone was asked the
same thing. Two config keys decide whether a bank may be used at all, and both
are checked when the game is built rather than when a question is first drawn:

* `facilitator_questions.scope` must match the bank's own declared `scope`.
  Spec #24 keeps this configurable for a future domain-specific run; pointing
  config at a bank of the wrong scope is a misconfiguration, not a silent
  downgrade.
* `facilitator_questions.framing` names a *mode* in `content.FRAMING_MODES`, and
  a mode says which per-question `framing` values are legal
  (`questions_to_about_the_mayor` → `to_the_mayor` / `about_the_mayor`). Every
  question in the bank is checked against it. An unknown mode is refused rather
  than treated as "anything goes", and a question with no framing at all is a
  content error — there is no default, because a question that silently inherits
  one is exactly how a question ends up addressed to the person instead of the
  persona.

If the bank runs dry, the round asks nothing. Silence is the right failure: a
repeated question would pool two rounds' answers into one aggregate.

## The aggregate, as data (#25)

The ladder — tiers, the tie and fragmented cases, the low-respondent floor, the
integrity rules and every wording — lives in `content/questions.json`, because
thresholds and phrasings are writing decisions. `engine/aggregate.py` is the
implementation of that document, and `Ladder` validates it at startup: tiers
must descend by `min_share`, no tier may declare a `min_respondents` below the
aggregate floor, and the *lowest* tier must accept everything that gets past
step 2 — otherwise a distribution could pass every step and match no tier, and
the "steps 2–5 are exhaustive" claim in the content would be false.

```
GameEngine.record_answer_buckets(round, {city: label})   # cluster the answers
GameEngine.mayor_question_report(round)                  # facilitator's view
views.newspaper_mayor_question(engine, round)            # gated by config
views.facilitator_question_report(engine, round)         # complete, always
```

A report carries the distribution (`buckets`, each with a role — headline,
subgroup, outlier), the `measure` (largest bucket, share as an exact fraction),
the selected `outcome` with the phrases it licenses, the `garnishes` for the
buckets that did not lead, and `integrity.must_disclose_partial_response` when
the aggregate covers only some of the mayors.

Two decisions worth naming:

**Shares are `Fraction`s, not floats.** 2-of-5 is exactly the plurality floor.
In binary floating point that comparison is the kind that falls the wrong way,
and the failure would be a paper reporting "the world is divided" about a bloc
that actually leads.

**Freeform answers are not clustered by the engine.** Deciding that "the fish
counter" and "the market" are the same answer is a judgement, so
`record_answer_buckets` takes a clustering from outside and the engine's job is
to refuse a bad one (one that drops a respondent, or invents one — either moves
the denominator and so changes the outcome) and then do the arithmetic exactly.
Until a clustering arrives the report says `bucketing.status: "pending"` and
offers no outcome. The alternative — bucketing verbatim — is worse than useless:
three mayors phrasing the same answer three ways would be reported as a
fragmented world, and the paper would confidently print "no two nations agree"
about a unanimous one. `aggregate.verbatim_buckets` exists for the genuinely
categorical case, as an explicit opt-in, never as a default.

The low-respondent floor is the exception: with one or two answers, no share is
needed to know that this paper cannot speak for the world, so the floor is
selected on the count alone and needs no clustering.

### Conditional wordings

Selecting the right outcome does not make every wording under it true. "The
world, with one hold-out" is fine at 4-of-5 and false at 8-of-10 — same tier,
same share, two hold-outs. So the ladder splits `phrases` (true of *every*
distribution that can select this outcome) from `conditional_phrases`, and every
conditional phrase carries both an English `only_if` and a machine-checkable
`only_if_test` over `R`, `largest`, `buckets` and `tied`:

```json
{ "phrase": "the world, with one hold-out",
  "only_if": "exactly one respondent falls outside the largest bucket (R - largest == 1)",
  "only_if_test": "R - largest == 1" }
```

`aggregate.Predicate` parses those into a deliberately tiny grammar — whole
numbers, those four names, `+ - *`, the six comparisons, `and`/`or`/`not` — and
refuses everything else, validated as a full AST walk at load time rather than
during evaluation (a short-circuiting comparison would never reach the illegal
node behind it). The report then marks each conditional wording `licensed: true`
or `false` against the actual counts. A conditional phrase with no
`only_if_test` is a content error, so a new wording cannot be added without
stating when it is true.

## Exposure and identity

`facilitator_questions.answers_shared_in_newspaper` decides whether the item is
published, and it is consulted in exactly one place —
`views.newspaper_mayor_question` — for the same reason the leaderboard's flag is
(M3): an exposure policy enforced in two views is one that one of them will
forget. `views.facilitator_question_report` stays complete either way and says
`newspaper_visible` so a caller cannot mistake it for the gated view.
`audit.find_exposure_violations` now checks both flags over any payload, so a
newspaper surface added in M5 is covered without being enumerated.

Answers are keyed by city everywhere — the handle never leaves the roster (#28)
— and the report never touches the export side of the game. The questions
channel and the blind-voting channel do not cross-reference each other (#18,
#21); an item quoting an answer beside an export could identify who submitted
what.

## What M5 inherits

`views.round_briefing(engine, round)["mayor_question"]` is the full report or
`None`. `outcome.id` names the register to write in, `outcome.phrases` are safe
by construction, `outcome.conditional_phrases[*].licensed` says which sharper
wordings this particular distribution earns, and `integrity.rules` is the list a
written item must not break. The one remaining stub,
`aggregate_phrasing_stub`, marks where the sentence goes.
`facilitator_questions.aggregate_phrasing_style` is deliberately still unread:
it selects a prose register, and this milestone writes no prose.
