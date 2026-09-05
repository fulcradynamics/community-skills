# M3 — the economy: profit rolls, the leaderboard, exposure

Spec #20, #21, #22. Three rules that look like one feature and are not:

| # | Rule | Where it is settled |
| --- | --- | --- |
| #20 | a winning export earns one 2d6-style roll, added to that city's cumulative total | `economy.profit_roll` in config.json |
| #22 | whether the newspaper prints the leaderboard | `economy.leaderboard_visible_in_newspaper` |
| #21 | whether a *losing* export's origin city is ever shown | **not configurable** — `engine/economy.py`, permanently off |

The interesting content of this milestone is the third row. #22 asks for
exposure policy to be config-driven so it can be iterated on; #21 asks for one
specific exposure to never happen. Those pull in opposite directions, and
"config-driven with a sensible default of off" satisfies only the first: a
default is a thing somebody edits in `config.json` without ever reading spec
#21. So the two are implemented differently on purpose, and there are tests
whose whole job is to assert that the difference still holds.

## Where the money lives

```
engine/economy.py   Economy -- the roll, the split, the credit, the leaderboard
engine/dice.py      "NdS" parsed from config (M2)
engine/money.py     exact Fraction arithmetic and the even-split modes (M2)
engine/views.py     newspaper_leaderboard() -- the one exposure chokepoint
engine/audit.py     find_exposure_violations / find_origin_exposure_knobs
tests/test_economy.py
```

`Economy` is built in `GameEngine.__init__`, not on first use. That is the whole
reason it is a class: a game whose `economy.profit_roll` reads `"2dd6"` now
refuses to start, where before it resolved two rounds and then raised — with a
need already on the record and profit already credited to somebody.

Every credit in the game goes through `Economy.credit`, and
`tests/test_economy.AccumulationTest.test_only_the_economy_moves_a_citys_total`
greps the package to keep it that way. A second place that writes
`cumulative_profit` is a second economy, and the per-city assertions would keep
passing while it drifted.

## The roll (#20)

`economy.profit_roll` is parsed as `NdS`, so "2d6" is data and not an
assumption. `Economy.min_roll` / `max_roll` / `in_range` come from the parse,
which is what lets the tests assert range for `3d4` and `5d10` as readily as for
the default.

In-range is a weak check on its own — `randint(2, 12)` would pass it while being
a different game, one where a 2 is as likely as a 7. So the suite also pins the
*shape*: 8000 draws from the engine's own per-need profit stream, asserted
against the 36-outcome 2d6 distribution within two percentage points, with 7
most common. It is deterministic rather than a sample: the stream is seeded by
`(rng_seed, "profit", need_key)`, so the numbers are identical on every run.

Profits are `Fraction`, never `float`, because #19's even split divides one roll
among an arbitrary number of cities. A leaderboard reporting
`11.699999999999999` is a bug the newspaper would faithfully print. Display
strings are rendered at the edge, at `economy.profit_display_decimals`; the
`exact` field alongside them is the authoritative value.

## The leaderboard (#20, shown per #22)

Cumulative per-city profit, richest first, ties broken alphabetically so the
order is deterministic rather than dependent on registration order. Every
registered city appears, including one that has earned nothing — "who scored
zero" is part of the standing.

Rows carry `tied: true` when another city holds the same total. Rank stays
positional (1, 2, 3, 4); the flag is what the endgame's crowning (#31) needs,
because a bare sequential rank silently turns a two-way tie into a winner.

Identity is city and mayor only (#28): no handle, no player id.

## Exposure (#22), and the one thing that isn't (#21)

`views.newspaper_leaderboard(engine)` is the single place the #22 decision is
taken. Newspaper-facing payloads call it instead of reading the config key, so
switching the key off cannot be defeated by one view that forgot to check.
`audit.find_exposure_violations` then checks the *payload* rather than the view,
so a second newspaper surface added in M5 is covered without being enumerated.

`views.standings` is deliberately not gated: it is the facilitator's own view,
labelled `audience: facilitator`, and it carries `newspaper_visible` so an M5
caller can see at a glance that it is not the gated view they wanted. A hidden
leaderboard is an exposure policy, not a mute button — the engine still needs
the totals to crown a winner at the end.

For #21 there is no knob, and four tests keep it that way:

1. `NON_WINNER_ORIGIN_EXPOSURE is False` — a module constant, with the reasoning
   next to it.
2. `config.json` contains no key that could turn it on
   (`audit.find_origin_exposure_knobs`).
3. That detector is proven to actually detect, at any nesting depth, and proven
   *not* to flag the legitimate privacy settings — `player_identity_style` is a
   real #28 knob, and a detector that cried wolf about it would be switched off
   within a week. Detection is compositional (a privacy noun paired with an
   exposing verb, or two privacy nouns) rather than a list of forbidden names,
   because no literal list catches both `reveal_non_winning_origins` and
   `reveal_non_winner_origin`.
4. The one that matters: fabricate the keys config.json does not have
   (`economy.reveal_non_winning_origins`, `newspaper.show_origin_for_all_submissions`),
   set them all true, play a whole game, and read the paper. Every losing
   submission still comes out `origin: withheld`, with no `origin_city` field at
   all. Origins are also asserted withheld across six other economy
   configurations and all three resolution paths.

## What this milestone did not touch

Newspaper prose, hosting, images, question phrasing and aggregation, and the
endgame articles — M4–M7. The leaderboard rows and `resolution.awards` are the
*facts* those milestones will write from; the `[[M5 ...]]` stubs mark where the
prose is due.

Run the tests:

```
python3 run_tests.py economy     # this milestone
python3 run_tests.py             # everything
```
