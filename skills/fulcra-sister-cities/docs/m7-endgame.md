# M7 — the last edition

Spec #31 and #32: at game end, crown the cumulative-profit winner, publish a
tongue-in-cheek twist article about the problems the game's trade caused, and
give every city a description and an image built from its own history, with
non-chosen exports treated as "excess".

| # | Rule | Where it is settled |
| --- | --- | --- |
| #31 | crown the cumulative-profit winner | `engine/endgame.py:_crown`, `newspaper/endgame.py:the_crown` |
| #31 | the tongue-in-cheek twist article | `newspaper/endgame.py:consequences` + `content/newspaper.json` |
| #32 | a description per city, from real history | `engine/endgame.py:_city_dossier`, `newspaper/endgame.py:the_excess` |
| #32 | an image per city, same modality policy as #29 | `newspaper/portrait.py:render_city` via `newspaper/imagery.py` |
| #32 | non-chosen exports treated as "excess" | this document, and the section below it |

```
python3 run_tests.py                       # 485 tests, standard library only
newspaper.build_final_edition(engine)      # the last edition, or None
python3 -m newspaper.publish               # ... written to editions/sample-game/
```

The last edition of the committed sample run is
[`editions/sample-game/final.md`](../editions/sample-game/final.md), with its
finale illustration and five city portraits beside it. The same edition served
at the paper's private address is `site/public/final.html`.

## Three articles, and why they are three

The names come from `NAME.md`, written in M1:

| Department | Spec | What it is |
| --- | --- | --- |
| The Crown | #31 | who won on cumulative profit, by how much, and how |
| Consequences | #31 | what the year's actual arrivals did to the cities that took them |
| The Excess | #32 | one portrait and one description per city |

Each has its own switch in `config.endgame`, and with all three off there is no
final edition at all rather than an empty one with a masthead on it. `#31` and
`#32` are two requirements, so the crown and the portraits fail independently:
switching portraits off does not silence the crown.

The twist article is built from `report["arrivals"]` — every export that was
actually chosen, quoted verbatim, credited to the city that sent it and the city
that took it, followed by a consequence keyed to *that need's own category*.
`content/newspaper.json` carries a line per category for exactly this, and
`_pick_arrivals` spreads the article across categories before it fills up, so
four consequences come from four kinds of need rather than four from one. A
twist article whose items could have been printed before the game began would be
a comedy column with a misleading heading; `TwistArticleTest` asserts every
quoted export is one somebody really sent and somebody really chose.

## The excess: where #32 meets #21

This is the whole design of the milestone, and it is worth reading before the
code.

Spec #32 wants each city's **non-chosen exports** on the page as "excess". Spec
#21 says a non-winning export's origin city is **never** exposed — not during the
round, not after it, not in the newspaper. Read literally, #32 asks for a list of
what each city sent and nobody wanted, and #21 forbids publishing exactly that
list.

They are the same pile counted from opposite ends. Every offer one city *sent*
and nobody chose is an offer some other city *received* and passed over. So:

- **The world's excess is published in full, once, from the importing end.**
  A city's portrait carries the offers that arrived on its own quay and were
  declined: how many, what the seed content calls that kind of leftover, and up
  to `endgame.max_excess_offers_printed_per_city` of them reprinted with no
  sender. Which city declined an offer has been public all game — the notice was
  theirs. Which city *sent* it has never been anywhere.
- **The sender's end is stated, not itemised.** Each portrait says in as many
  words that the offers this city sent and nobody chose exist, are somewhere in
  that city, and are not the last edition's to open. The illustration draws a
  shed with the door shut, and the shed carries **no number** — a count is what
  would make the pile attributable.
- **The sender's-end view exists and goes to one reader.**
  `engine.views.mayor_excess_dossier` is that city's own mayor's account of what
  they sent and what came home again. It tells them nothing they did not already
  know, since they wrote it. It is marked `audience: facilitator`, which
  `hosting/guard.py` refuses structurally, and
  `endgame.write_private_excess_dossiers` is **off**: writing a dossier to disk
  in a repository anybody can read would publish precisely what #21 forbids.

### The leak that is not a field

A declined offer is printed with no origin field of any kind — not `None`, not
`"withheld"`, absent. That was never the hard part. Two ways the text itself can
give the sender away:

1. **The offer signs itself.** A mayor who writes their city's name into their
   own export has identified themselves, and the paper cannot rewrite what they
   wrote. So it declines to reproduce it at all
   (`newspaper.redact.may_reprint_declined`), and says so in character.
2. **The same words won somewhere else.** This one was found by reading the
   generated edition rather than by reasoning about it. The identical export can
   be sent to two different needs and win one and lose the other — the sample
   game does this — and the paper credits winners by name. Quoting
   *"Hobart wrote that"* in Consequences and reprinting the identical sentence
   as an unattributed declined offer in The Excess identifies the declined one
   just as plainly as a byline would.

`newspaper.redact.attributed_export_texts` closes (2): a declined offer that
reads word for word like one the paper credits to a city is withheld, and
`assert_edition_is_redacted` re-checks it over the finished edition so a
department added later cannot reintroduce the leak by forgetting the filter. The
two reasons for withholding are counted separately and reported separately,
because a column about redaction that misstates its own redaction is worse than
one that says nothing.

### What this deliberately does not do

The rule cannot reach forward across editions. A round edition asks only about
winners resolved **by that round** — a set fixed the moment the round closes —
because spec #27 makes an edition a historical document: rebuild round 5 in
round 12 and it must come out byte for byte as it went out. So an offer
reprinted unattributed in round 5 may be matched by an attribution the paper
prints in round 9, and nothing available here can prevent that: closing it would
mean either rewriting round 5 (forbidden by #27) or withholding round 9's winner
(required by #18 and #20).

The final edition passes the whole game's set, which is both safe and necessary
— it is published once, from a finished game, and it is the one edition that
prints game-wide reprints and game-wide attributions on the same page. So the
residue is narrow and named: cross-edition matching within the round archive.
It is recorded here rather than left for somebody to rediscover.

## The pictures

Spec #32 says to use #29's modality policy rather than having one of its own, so
the finale and the portraits go **through** `newspaper.imagery.make_image`, not
around it: one modality resolver, one provenance record, and a raster provider
that appears tomorrow gets asked for all three kinds of picture without anything
else changing. `scene["kind"]` (`edition`, `endgame_finale`, `city_portrait`) is
what would tell such a provider which it is being asked for. Only the *canvas*
is separate — `endgame.city_image` — because a portrait is not a broadsheet.

`newspaper/portrait.py` draws both, deterministically, from facts:

```
the finale                        the whole world on the last day
  the towers                      final cumulative profit, one per city
  the crown                       over the tallest, or over both when shared
  the fog bank instead            the standings, when config withholds them
  the stack on the quay           every offer sent and not chosen, in total,
                                  unlabelled and unattributed (spec #21)

a city portrait                   one city at the end of its game
  the skyline                     that city's own final standing
  the stamps                      the notices it opened
  the ribboned crates             the offers of its own the world kept
  the plain crates                the offers it received and declined
  the shed, door shut and sealed  the offers it sent that nobody chose
```

Portrait filenames are flat and folded to ASCII (`city-valparaiso.svg`): a
filename is a URL, and "Valparaíso" is two different URLs depending on who
encoded it. The city's real name, accents and all, is on the page.

## The crown is not an exposure decision

Spec #22 makes the *running leaderboard* configurable; spec #31 makes crowning
the winner a requirement. Those are different things, so a game that kept its
standings private all along still ends with a winner — named, without a figure
beside it, with `crown.profit_visible` recording which of those happened and the
figure **absent** rather than blanked. The margin is only claimed where the
figures are printed: "narrowly" over an unprinted total would be the paper
describing arithmetic it has withheld.

`engine.views.endgame_briefing` takes both exposure decisions by asking the same
functions every other newspaper payload asks — `newspaper_leaderboard` for the
standings (#22) and `answers_shared_in_newspaper` for the mayors' own answers
(#25). The endgame reads neither key itself; a payload that consulted config
directly would be a second reading of a decision that is supposed to have one
home.

## The last edition and the archive

The final edition is published in the same round as that round's own edition and
is a different document, so it gets its own permanent name (`final.html`,
`final.md`) and its own manifest category. That is not bookkeeping: the
`editions` category is checked for one page per round
(`hosting.guard.assert_publishable`), and a second page claiming round 12 would
— correctly — be refused as an edition overwriting an edition. Giving it its own
category says what it is instead of arguing with the check.

For the same reason `Paper.archive()` carries it as `archive["final"]` rather
than appending it to `archive["editions"]`: spec #26's "once per completed
round" is a rule about that list, and a list with two entries for the last round
would break it to make room for something that is not a round edition. The last
edition is still an issue of the same paper at the same private address, listed
in the archive index, audited by the same guard, and kept forever like every
other issue (#27).

## What the tests cover

`tests/test_endgame.py`, 62 tests. Beyond the sample game they play three more
to their end conditions, because the endgame must not depend on the sample's
convenient shape:

- a short cooperative game — the "nothing unusual happened" branch of every
  frame family;
- a game where **nobody ever exports** — every notice ramps up its own industry
  (#17), nothing is ever chosen, the world's excess is zero, and a crown is
  still awarded;
- a game with a **late joiner** — a city described by the year it actually had
  rather than the year the rotation planned for it (#5, #12).

The judged criteria (#31's twist article and #32's descriptions being *clearly
informed by actual game history* rather than generic filler) are the Evaluator's
to render. What is mechanised here is their checkable half: every export the
twist article quotes is one somebody really sent and somebody really chose, and
every portrait names that city's own notices by title.
