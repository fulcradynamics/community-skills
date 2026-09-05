# M9 — the mayor orders, the order is trade, the paper comes out by itself

Three changes, from one smoke test on 2026-08-31 and the two user decisions it
produced. They are separate changes and this document keeps them separate,
because each one is a different kind of thing: the first is about *who decides*,
the second about *what may be decided*, and the third about *what happens
without anybody deciding anything*.

| # | Requirement | Where it lives |
| --- | --- | --- |
| #13 | the importing mayor chooses their city's next import | `engine/game.py`, `engine/rotation.py` |
| #13a | an import need is an order for actual tradable things | `engine/trade.py`, `content/import_needs.json` |
| #26 | a completed round publishes itself and tells the group | `facilitator/`, `newspaper/publish.py` |

---

## 1. The draw is gone (#13)

Before this milestone, a city's import need was drawn for it:

```python
need_doc = self.content.draw_need(self._rng("need", ...), player.city, **rules)
```

The mayor found out what their city wanted by reading the newspaper. The
smoke test's verdict was that this is the wrong game — a mayor who cannot say
what their city needs is not playing a city.

So `draw_need` does not exist any more, and that absence is the design. The
strongest available statement of "a city cannot receive an import nobody chose"
is not a test that no such need appeared in one run; it is that the engine owns
no function that could produce one. What replaced it:

* **`GameEngine.import_choice_offer(player_id)`** — a slate of eligible seeds
  (`imports.suggestions_offered_to_importer`, spread across categories before it
  doubles up on one), plus the standing permission to write an order instead,
  plus how many rounds away the turn is.
* **`GameEngine.choose_import(player_id, need_id=... | request=...)`** — the
  order is appended to that city's *programme*, and `OPEN` opens the front of
  the programme. The slate is a suggestion and not a menu: any eligible seed
  may be named, shown or not, which is strictly more agency than a menu.
* **`CityQueue.next_importer(..., ready=...)`** — if the mayor whose turn it is
  has filed nothing, the queue **holds its place**. The round opens no need at
  all rather than opening one nobody asked for. After
  `imports.unchosen_turn_grace_rounds` rounds it gives the turn up
  (`CityQueue.pass_over`) and moves on.

### Why holding, and then forfeiting

Holding is the only behaviour that respects #13 literally: there is no third
option between "open what they ordered" and "open something they didn't". But
holding forever means one absent mayor stalls a game that can never end, so the
hold has a configured grace and then the turn is simply lost. That is spec #16's
rule — "no penalty, no substitution" — applied to the other side of the trade:
a mayor who does not act misses the thing they did not act on, and nothing else
happens to them. `Player.import_turns_forfeited` records it; the round's `OPEN`
event says which city was held and for how long, so the paper and the
conformance pass can both see it.

### Where the order is filed, and what it costs

Filing is a game action, so when the game is *asking* for it, it takes one of
the check-in's two slots (spec #11, #23). The priority is:

```python
GAME_ACTION_PRIORITY = (SLOT_IMPORT_PICK, SLOT_IMPORT_CHOICE, SLOT_EXPORT)
```

A lapsed pick costs the whole table a winner (#19's even split fires), an
unfiled order costs its city an import turn, a missed export costs one offer.
That is the order of harm, so it is the order of the slots.

Priority is not the same question as *what leaves the room when three actions
apply and only two fit* — M12 and spec #11a settle that one, and the answer is
never the export. See [`docs/m12-current-trade-priority.md`](m12-current-trade-priority.md).

The check-in only asks within `imports.choice_offered_rounds_ahead` rounds of
the turn. Two reasons, and the second is the load-bearing one:

1. asking earlier would be asking about something a mayor cannot usefully think
   about yet — spec #13 says to ask "on the city's actual import turn, not
   prematurely", which is why the shipped lookahead is 1 (M12 lowered it from 2);
2. a game action that is pending *every* round from the moment a mayor joins
   would crowd the getting-to-know-you question out of every check-in, and #23's
   question is not a nice-to-have — it is the input to #25's aggregate.

Filing **before** being asked costs no slot, and that asymmetry is deliberate.
A mayor who says what their city needs at the table before the game starts has
not taken a second turn at a round; there is no round. This is also the ordinary
path: the facilitator's agent asks a joining mayor which city they are and what
it needs in the same breath, and the check-in slot is the reminder for anybody
who did not answer.

The facilitator is the special case at both ends: their city holds queue
position 1 so that round 1 has something to open (#4), so `start()` refuses to
begin a game until their first order is filed. A dead round 1 and an unordered
round 1 are both worse than a clear error at the table.

### Repetition (#14) still binds, and now binds earlier

An order that has been *filed* counts exactly as a need that has been *opened*:
`_eligibility_rules` folds every city's programme into `used_need_ids` and the
category sets. Without that, two mayors could file the same seed on the same
evening and #14 would hold by luck rather than by construction. The visible
effect is that impossibility surfaces where the mayor is being offered a slate
rather than three rounds later where a draw would have happened, which is a
much better place for it: `NoEligibleImportNeed` now means "there is nothing
left this city may order", said to somebody who can do something about it.

---

## 2. Every need is an order (#13a)

The seeded list used to be written as civic *problems*:

> `{city}` has a magnificent bridge… **What does {city} put on the other side
> of that bridge?**

which reliably produced good writing and the wrong game: mayors answered with
advice, and "import/export" became "suggestion box". The user decision of
2026-08-31 says an import need "describes actual tradable imports — e.g. food or
candy, materials, equipment, living things, cultural works, or specialist
services" and "may not reduce to a request for generic advice or civic problem
solving".

All 48 seeds were rewritten as purchase orders, **keeping their ids, their
categories and their subjects**:

> `{city}` has a magnificent bridge… `{city}` is buying what goes on the end of
> it: a building's worth of fittings, market stalls, plant, stock, a whole going
> concern if one will fit on a lorry. **Ship {city} something worth crossing a
> bridge for, and say what comes off the lorry.**

Keeping the ids is not tidiness. `playtest/transcript.json` records a whole
played game by need id, and the offers in it — pontoon decking, blast freezers,
rooted sea-buckthorn whips, a cast-iron trophy — were already consignments,
because that is what mayors send when asked for help. Rewriting the *framing* of
each seed while keeping its *subject* means the recorded game still means what
it meant: a city that asked what to do with four hundred tonnes of seaweed now
asks for the plant to bale and dry it, and the mayors who sent balers and buyers
are still sending balers and buyers. Nobody's prose was rewritten to fit, which
matters for #34 — those words were written by eight separate agent sessions and
are not mine to revise.

### The policy is content, and it is checked at three doors

`content/import_needs.json` grew a `trade_policy` block: the six families from
#13a, the supply verbs an exporter prompt must use, and the phrases that mark a
request for advice. `engine/trade.py` applies it at every door a need can come
through — the seeded list at load, a player-suggested addition (#33), and an
importing mayor's freeform order (#13) — because a rule enforced at two of three
doors is enforced at none.

Two things it deliberately does **not** do. It does not judge whether "a
rivalry, in kind" is really a tradable good; that is a judgement, it belongs to
the mayors and to the Evaluator's #33 review, and a machine pretending to make
it would only be wrong more confidently. And it does not rewrite anything: a
marker in a seed is a content bug and a marker in a mayor's request is a request
the facilitator's agent should hand back, with the phrase that failed
(`TradeRefused.phrase`) so the conversation can be about words rather than about
the machine.

The word-boundary matching earned itself twice while this was being written.
"the crew who **fix** it in place" and "the minute that **explains** the pipes"
are both sentences about consignments, and both were refused by a first pass
that matched substrings. The rule is now: whole words, and a `{city}` in a
marker stands for the placeholder or a capitalised word, never for "any word at
all".

---

## 3. The paper comes out because a round ended (#26)

Spec #26 has a clause that M5 and M6 between them did not satisfy:

> Automatically renders and publishes exactly one redacted edition after every
> completed round (not batched), then notifies the group it is available. … **A
> manually callable renderer alone does not satisfy this requirement.**

Everything existed except the trigger. `newspaper.publish_game` and
`hosting.build_site` were both things somebody ran. So:

* `engine.GameEngine.on_round_completed(hook)` — the engine raises one event,
  at the one honest moment: the instant a round's standing freezes, which is the
  same instant an edition printed from it stops being able to change.
* `facilitator/` — the desk that hangs on it. `Facilitator.attach(game)` is the
  whole of "automatically"; after that line, rounds ending is what publishes
  editions.

The transaction is four steps, declared in
`config.facilitator.completed_round_transaction` and run in canonical order:
**render** the edition (which is also the gate — `Paper.edition` refuses to
return one that leaks an exporter or trips the tone register), **publish** it
beside every earlier edition, **build** the site at the paper's own address, and
**notify** the group. `render_edition`, `publish_editions` and `notify_group`
cannot be dropped from that list: they are the requirement, not a preference,
and a config that drops one is refused with #26 quoted at it. This is the same
carve-out `hosting.guard.assert_no_config_can_disable` makes — config.json holds
the parameters of the rules, not switches for them.

A hook that raises stops the game. That is the right way round: an edition that
cannot be published is an emergency, not something to note and carry on past.
`tests/test_round_publication.py` plays a game with an offer that signs itself
and asserts exactly that — the tick raises, and no final edition is written.

### The notice, and the one place the address nearly leaked

The group notice is written from `content/newspaper.json`'s new `bulletin`
block, in the paper's own voice, and it is *returned* rather than sent: the desk
knows what to say and deliberately does not know what the group's inbox is.

`Notice` is an object and not a string for the same reason
`hosting.identity.SiteIdentity` is: `text` contains the address and
`describe()` is what may be written down. Writing this found a live bug worth
recording. `Chooser.line` sentence-cases what it fills, an address is full of
full stops, and the first version of the notice came out as

> It is at https://oikwuudg5dk6yfc2yg42mreh64.**S**ister-cities.**N**ews/

— a broken link, and worse, a string that no longer matched the address
`Notice.describe()` redacts, so the credential would have gone into every
receipt. The address is now pasted in after the copy machinery has finished with
the sentence, and `tests/test_round_publication.py` checks both halves: the
notice carries the address, nothing written down does.

### What the recorded game proves now

`playtest/run.py` no longer publishes anything. It attaches the desk before the
timer starts and then reads what the desk did, which is why
`playtest/conformance.json`'s #26 finding can now say *"each one written by the
round ending, in the facilitator's completed-round transaction"* rather than
"here are seventeen editions somebody produced". The per-round site build also
means `hosting.guard.assert_archive_is_append_only` is exercised sixteen times
per run instead of never — an archive that is only ever built once cannot
regress, and one built after every round can.

One consequence worth naming: replaying the recorded game re-publishes it from
round 1, so `playtest.run` clears the previous run's editions and public tree
first. Spec #27's append-only promise is about a live address — an edition a
mayor has a link to stays where it was put — and this is the same game being
played again from its first round, not a continuation of it. Git shows whether
the bytes changed, which is the drift check that promise is really protecting.

---

## What this milestone did not do

The recorded playtest's mayors did not choose their imports, because the game
was played in August, before they could. `playtest/transcript.json`'s
`import_orders` block records the notices the archive says each city actually
opened, replayed through the choice API so a recording made under the old rule
still plays under the new one — labelled, in the file, as exactly that and not
as decisions those agents made. Re-recording the game with mayors who choose
would need eight fresh agent sessions (#34), which is a run of its own and not
a thing to fake in this one.
