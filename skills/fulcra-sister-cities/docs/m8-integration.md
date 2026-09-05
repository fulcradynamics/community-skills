# M8 — one whole game, and all thirty-five rules at once

No new features. M2 through M7 each proved one milestone's rules on a game built
to exercise them; this milestone plays **one complete game** — eight mayors, each
played by its own separately spawned agent session — publishes it, builds its
site, and asks whether all thirty-five requirements hold at the same time, on
the same game.

They are different questions. A queue rule and an exposure rule can each be
perfectly correct on their own fixture and still disagree about a mayor who
joined in round 9 and never exported. Nothing but a full run finds that, and a
full run found six things (below).

```
python3 run_tests.py                 # 540 tests, standard library only
python3 -m playtest.run              # replay, publish, build the site, report
python3 -m playtest.run --check      # the report only; writes nothing
python3 -m playtest.run --json       # the report as JSON
```

| Artifact | What it is |
| --- | --- |
| [`playtest/transcript.json`](../playtest/transcript.json) | the recorded game: every export, answer and winner pick, as the mayors wrote them |
| [`playtest/conformance.json`](../playtest/conformance.json) | spec #1–#35 checked against the finished game, its editions and its published bytes |
| [`editions/playtest-game/`](../editions/playtest-game) | seventeen editions and the final one, rendered |
| [`site/playtest/`](../site/playtest) | the same paper as served, at its own private address |

## The table

Eight mayors, and the seating plan is in [`playtest/table.py`](../playtest/table.py).
Spec's Generation Rules ask for simulated players who are genuinely separate
agents; M8 asks for varying engagement levels. Those are two different things,
and the file only decides the second — *what* a mayor says was written by that
mayor's own agent, *whether they were at their desk* is the table's decision,
because somebody has to be away for #16's silent skip and #19's lapsed window to
happen at all.

| Mayor | Engagement | Why they are at this table |
| --- | --- | --- |
| Reykjavík | facilitator, diligent | plays under the same rules as everybody (#7), first in the queue (#4) |
| Valparaíso | eager | the always-present case |
| Hobart | steady | misses one round on their own (#16) |
| Kampala | erratic | misses three, then acts as if they hadn't |
| Kópavogur | steady, joined a beat late | **asked for Reykjavík, which was taken** (#2) |
| Naoshima | lurker, joins round 3 | **off-gazetteer pick** (#2), mid-game arrival (#3) |
| Belgrade | late but keen, joins round 4 | queued only by exporting (#5) |
| Trieste | very late, joins round 9 | arrives **after rotation 1 closed**, so is owed one import turn, not two (#12) |

### The long weekend

Round 6 is empty: every mayor is away, which is a thing that happens to a
24-hour-round async game played by adults with jobs. It is the single most
load-bearing round in the game, because one quiet day drives three fallbacks at
once — the need that *opened* collects nothing and its city ramps up its own
industry and is still paid (#17); the need that *closed* gets no pick and splits
its profit evenly (#19); and the round's question gets no answers, so the paper
has to write an empty postbag without inventing a distribution (#25).

## How the game was actually played

Spec #34 and the Generation Rules require genuinely separate sessions, not one
session wearing eight hats. So:

1. **One agent session per mayor**, given only its own city's brief — its
   persona, its engagement level, and the notices its own check-ins put in front
   of it. Never another city's offers, which is #18 and #21 enforced on the
   *briefing* rather than only on the paper. The briefs are in
   [`playtest/_briefs/`](../playtest/_briefs) and the returned work in
   [`playtest/_agent/`](../playtest/_agent).
2. **Winner picks in a second pass**, by those same eight sessions with their
   personas intact, from the real blind ballots of the replayed game. A mayor
   cannot judge offers that do not exist yet, and a ballot handed to them names
   no city (#18).
3. **A ninth session, playing the facilitator**, to cluster each round's answers
   into buckets — because #25's aggregate is measured over a grouping the engine
   deliberately refuses to invent (see `engine/aggregate.py`; a clustering is a
   judgement, and a judgement dressed up as arithmetic is the failure mode that
   module exists to avoid).

A game played by language models is not reproducible; a regression artifact has
to be. So the result is recorded once, and everything downstream replays it:
`playtest/transcript.json` plus the seed in `playtest/table.py` reproduces the
game, the editions and the site exactly, and `test_rebuilding_produces_the_same
_bytes` asserts it.

`playtest.run.assert_schedule_matches` guards the one thing that could make the
briefs dishonest: which need a city draws depends on the seed, the city and the
categories that city has already had, and nothing else — so a stand-in game and
the real game must agree need for need and round for round, differing only in
what was said and who won. If that ever stopped being true, the briefs would
describe a game nobody played.

## The pipeline

`playtest.run.play` is five steps in the order a real game night happens in:
**replay** the recorded game through the engine → **verify** the schedule the
mayors were briefed on → **publish** every edition → **build** the site → **check
all thirty-five requirements at once**.

Steps 3 and 4 are not decoration. Half the requirements are properties of
*published bytes* — the archive, the identity rules, the images, the exposure
policy — and there is no way to check a published byte without publishing it.

## The report

`playtest/conformance.py` is spec #1–#35 as executable checks, one per
requirement, each carrying its own evidence. Nothing in it re-implements a rule:
where the engine, the paper or the publication guard already enforces something,
the check calls *that* enforcement and records that it held. A second copy of the
blind-voting rule living in a test file is a copy that can disagree with the one
that matters.

**35 findings: 28 pass, 4 judged, 3 process.** No failures.

The four judged ones are exactly spec's four judged criteria, and each is handed
to the Evaluator with the material to judge rather than a verdict:

| # | Judged criterion | What the finding attaches |
| --- | --- | --- |
| #25 | aggregate phrasing reflects the real distribution | each round's buckets **and** the line The Wire printed about them |
| #30 | funny, colourful, pointed but never mean | 534 printed passages; the mechanical floor (the forbidden register) held |
| #32 | per-city descriptions informed by real history | all 8 portraits and all 8 descriptions |
| #33 | the name and the seed list | the name, and 48 needs across 16 categories, 15 drawn |

The three "process" findings — #8 (a facilitator relaying for a player), #34
(separate sessions), #35 (a separate repository) — are **not decidable from game
state**, and say so rather than passing themselves. Each records the evidence a
human can check: that every action entered through the same public engine
methods a relaying facilitator would use, how the sessions were spawned, and
that this repository shares no commit history with the harness.

## What playing the whole game found

Every one of these passed its own milestone's tests. That is the point of the
milestone.

1. **The Crown's third standfirst could not be rendered.** It used `{n_needs}`,
   which the department declares and the standfirst family was rendered without.
   Which frame gets chosen is a CRC of game state, so it was invisible through
   all of M7 and refused to publish the final edition of the first eight-mayor
   game that hashed onto it. Fixed by giving standfirsts and closers their
   department's substitutions like every other family — and, so the class cannot
   recur, [`tests/test_frame_coverage.py`](../tests/test_frame_coverage.py) pins
   the chooser to frame *i* of every family and rebuilds the whole paper, for
   every *i*, until every frame in the file has been rendered by the code that
   owns it.
2. **The forbidden register matched substrings.** A mayor wrote "plant them
   closer together"; "closer" contains "loser", and an edition was blocked over
   an ordinary sentence in a paper whose whole job is to reprint exports exactly
   as written. Now anchored at the start of a word — and deliberately not at the
   end, because the register contains stems (`humiliat`) on purpose.
3. **A seeded question tripped the register too.** "The most useless thing you
   refuse to throw away" is innocent about an object and identical, to a matcher,
   to an insult. The content file's own note says the cost of a false positive is
   a rewrite and the trade is not close, so the question was rewritten — and the
   seed files are now checked against the register at build time instead of at
   3am on game night.
4. **The `_placeholders` table had drifted.** `arrivals` renders `{counted}` and
   never declared it. Found by the static half of the same new test file, which
   checks the whole document at once rather than one department per game.
5. **Two games were publishing to one address.** The integration game built its
   site into `hosting.site_dir`, on top of the sample game's. Spec #27 makes an
   address an append-only archive, so the guard refused — correctly — to delete
   seventeen back issues to make room for twelve. The recorded game now has its
   own address (`config.playtest.site_dir`); same build, same manifest, same
   privacy policy, different directory.
6. **The identity audit fired on correct data.** Ballot refs are letters
   assigned per need and starting again at "A" for the next one, so a record of
   the pick made in need 12 matched the ref-C submission of every *other* need,
   and a whole game's worth of correct records read as a leak. `engine/audit.py`
   now honours the scope. An audit that fires on correct data is an audit people
   learn to wave through.

Two more, in the checks themselves rather than in the game: `_tone` and
`_aggregate_phrasing` walked a department shape that does not exist, so both
**passed while attaching nothing** — a judged criterion handed to a grader with
no material to grade. That is the quietest failure mode in this repository and
the reason every judged finding above is quoted by its evidence, not its status.

## Spec #2, which no milestone had built

M1 produced the seeded content and the gazetteer; M2 built `register_player`,
which *refuses* a duplicate city pick and hands back the candidates. Nothing
resolved one. Spec #2 requires that a duplicate is "reassigned to a
geographically close alternative, never silently allowed to collide", and it is a
deterministic evaluation criterion, so the integration pass could not have
reported it as holding.

[`engine/join.py`](../engine/join.py) is that resolution, and it executes the
procedure written down in `content/gazetteer.json` rather than inventing one:
first claimant keeps the city, walk its `nearby` list, then the nearest unclaimed
city in the same region inside
`config.cities.max_reassignment_search_radius_km`, then ask for a free re-pick
rather than assigning something absurd — and announce the outcome either way,
because the gazetteer's own rule is that reassignment is announced, never silent.

The split from `register_player` is kept deliberately: the low-level seat must
never quietly move a mayor to a different city, and the joining door must never
simply tell a player "no". `tests/test_join.py` covers both, including the branch
where every listed neighbour is taken and the one where the city is not in the
gazetteer at all — where the engine refuses rather than guessing at a neighbour
for a city it has never heard of.

## Two addresses, on purpose

`hosting.site_dir` (`site/`) is the live game's address and holds the scripted
sample run. `config.playtest.site_dir` (`site/playtest/`) is the recorded
integration game's. Both are built by the same `hosting.build_site` under the
same privacy policy — unguessable subdomain, `noindex` in three places, no
external origins — and both are safe to commit for the same reason: the pages are
public, the address is not, and `hosting/guard.py` fails the build if any
published byte contains it.

## What is deliberately not audited

`playtest/transcript.json` and the replay journal know which mayor wrote which
losing offer. They are the game's **input**, and every game — played live or
replayed — has that at the moment of submission; the engine holds the same
mapping itself, in a ledger that answers only for an audited reason and that the
paper is never handed. Spec #21 forbids *exposure*: to the importing mayor while
they vote, and to every reader afterwards. So the #21 audit runs over everything
this run published and nothing it read, which is stated in the finding rather
than left implicit — and what must be true of the two input records is checked
directly instead: picks are recorded by ballot ref and never by city, and no
player id, handle or journal line reaches a published page.
