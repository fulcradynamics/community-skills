# M12 — the trade in front of you comes first

Spec #11a, #13; requirements #9–#11, #14–#16, #23.

The live harness run's third smoke test found the importer-choice mechanic
(spec #13, built in M9) getting between mayors and the round they were in. Two
distinct faults, one theme: the *paperwork for a turn that has not come round*
was being treated as if it were as urgent as the trade currently on the table.

## 1. An order must never cost a mayor the open trade (#11a)

A check-in has two slots (#11, #23) and three things can want them: a winner
pick, an import order, an export to the need that is open right now. When all
three applied, the check-in took the first two in priority order and the export
fell off the end — so a mayor who was eligible for that round's trade sat it
out, having been asked instead to plan an import two rounds away.

The user decision of 2026-09-03 settles it: *"an eligible export to the
currently open import need must never be displaced by a prompt to file a future
import order."*

The fix separates two questions the old code answered with one list.

**Which comes first** is still `GAME_ACTION_PRIORITY`, unchanged, and still the
order of harm — a lapsed pick costs the table a winner (#19's even split), an
unfiled order costs a city its import turn, a missed export costs one offer.

**Which one leaves when three apply** is a different question, because the three
have different deadlines:

```python
DEFERRABLE_GAME_ACTIONS = (SLOT_IMPORT_CHOICE,)
```

An export answers a need that closes at the end of *this* round; there is no
later round in which to submit it. An import order is for a turn that has not
opened yet, is asked for again next round, and is held open by the queue for
`imports.unchosen_turn_grace_rounds` besides. So the order defers and the export
stands. `GameEngine._pending_game_actions` returns `(offered, deferred)`, and a
deferred order comes back in the check-in payload under `deferred` — as a note
with its reason and how far off the turn is, deliberately *not* as the slate
`import_choice_offer` builds, because the whole point is that this round is not
asking. A mayor who wants to file anyway still may: it costs no slot, exactly as
filing before being asked never has.

Deferring is not a free slot. A deferred action is still pending, so the
question does not slip into the space it vacated (#23) and the round stays a
two-action round.

## 2. Ask on the turn, not two rounds early (#13)

Spec #13: ask "on the city's actual import turn, not prematurely: in a
three-city game, each mayor therefore chooses every three rounds."
`imports.choice_offered_rounds_ahead` was 2, so a three-city table was asking
each mayor twice per rotation, the first time about a turn two rounds out.

It is now **1**, and 1 is the largest value that can mean "on the turn". A
round's needs open before its check-ins do (#9's `OPEN` runs at the top of the
round), so the check-in that belongs to a city's import turn is the last one
before that turn opens — one round ahead. 0 is a legal setting and asks only
once the queue is already holding the turn open, which costs a round of the game
per turn; that is why it is not the default.

`tests/test_current_trade_priority.py` proves the resulting cadence on the
shipped `config.json` rather than on an override, in the strong form: every
single time a mayor is asked for an order, the need that opens in the very next
round is that mayor's city's.

### The queue cannot see a turn it has not been told about

Reducing the lookahead was not sufficient on its own. A mayor's distance from
their next turn was read off the city order queue — and under #5 a player is
only *in* that queue once their first export lands. In round 1 the facilitator's
city is the only entry, so the queue said their second turn was one round away
when it was four, and the check-in asked them to order for round 5 in round 1.

`_rounds_until_unfiled_turn` now quotes a turn beyond the end of the rotation
now running pessimistically — one round for each registered mayor still to take
their place in the queue, since an entrant is appended to the end of `order` and
therefore lands ahead of every later-rotation turn. `CityQueue.turns_left_in_
rotation` is what tells one case from the other: a turn *inside* the running
rotation cannot be pushed back by an entrant, and padding it would ask its mayor
late for no reason.

The asymmetry is deliberate. A turn asked for a round late is held and then
asked for again (#13's grace); a turn asked for four rounds early has already
cost the mayor a slot.

## 3. The slot set really is fixed for the round

Both of the above are about *which* actions a round asks for. Working on them
turned up a third fault about *when* it decides.

The check-in has always documented that the set of actions a round asks of a
mayor is fixed when the round opens, and `used` merely hides the ones already
done — that is what stops a mayor who exported first from being offered a
question that eats their outstanding pick's slot. But the set was recomputed on
every call, and one input to it moves mid-round: an import order falls due the
instant a mayor's first export puts them in the queue (#5), and stops being due
the instant they file it. Two consequences, both reachable:

* a mayor offered an export and a question in round 1 exports, earns their queue
  place, and is then told no question was ever pending;
* a mayor offered a pick and an order files the order, finds a question in the
  freed slot, answers it, and still has their pick to make — three actions in a
  two-action round.

`_pending_game_actions` now works the set out once per mayor per round and
remembers it (`GameEngine._checkin_asks`). Nothing else about the check-in
changed; the budget simply stopped leaking through a recomputation.

One consequence is worth stating plainly, because it is a behaviour change and
not only a bug fix. A mayor who has filed the order a round *asked* them for
cannot file a second one in the same round: the order slot is spent, and
`_guard_checkin` says so (spec #11, "acts at most once per round"). That rule
was always in the engine — `tests/test_import_choice.py` has asserted it since
M9 — but whether it actually bit used to depend on whether the mayor's *next*
turn happened to fall inside the lookahead, so with the shipped config it never
did. It now behaves the same way at every setting. Filing when the round has not
asked is untouched and still free, which is the ordinary path: mayors order at
the table, and the check-in slot is the reminder for anyone who did not.
`tests/harness.py`'s `file_orders` fixture files a mayor's whole programme in
one go at the table and one order per round once the game is running, which is
what a real table can do.

## What proves it

* `tests/test_current_trade_priority.py` — 14 tests. The deferral is built by
  playing a lazily-filing table until some mayor genuinely holds a pick, an
  export and an order at once, and the test refuses to pass if that collision
  cannot be constructed. Coverage of the open trade and the two-action budget is
  asserted over whole games at three different lookaheads, so the rule is the
  engine's and not the shipped config's.
* `playtest/conformance.py` — a new `#11a` finding over the recorded eight-mayor
  game: every mayor-round eligible for an open need was offered it, and no
  deferral ever coincided with a missing export slot.
* The fixtures in `tests/harness.py` file every order up front, which is the
  ordinary path and the reason none of this showed up there. The tests here file
  lazily on purpose — a mayor orders when asked and not before.
