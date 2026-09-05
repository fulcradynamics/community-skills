"""Spec #11a and #13: the trade in front of a mayor outranks the paperwork.

Two findings from the live harness run's third smoke test, both of them the
importer-choice mechanic (spec #13) getting between a mayor and the round they
were actually in:

* a check-in holding a winner pick, an eligible export **and** an import order
  offered the pick and the order. The two-slot budget (spec #11, #23) was being
  applied by truncating the lowest-priority action, so the mayor sat out a trade
  they were eligible for -- which the user decision of 2026-09-03 (spec #11a)
  forbids outright: "an eligible export to the currently open import need must
  never be displaced by a prompt to file a future import order".
* mayors were asked for an order two rounds before their turn came round, so in
  a three-city game a mayor was filing every other round rather than every
  third. Spec #13: ask "on the city's actual import turn, not prematurely".

The two are tested separately because they are separate rules. Deferral is a
rule of the engine and has to hold at *any* lookahead, so those tests widen the
lookahead deliberately to build the collision. Cadence is a property of the
shipped ``config.json``, so those tests run on the real file with no overrides
at all -- the value a real game plays with is the thing under test.

The games here file lazily: a mayor orders when the check-in asks and not
before. ``tests/harness.py``'s cooperative fixtures file everything up front,
which is the ordinary path (and why neither bug showed up there) -- but it also
means no check-in ever has to ask, so it cannot see either of these.
"""

import unittest

from harness import FACILITATOR, FOUNDERS, make_config
from engine import Content, GameEngine
from engine.clock import utc
from engine.errors import RuleViolation
from engine.game import (
    SLOT_EXPORT,
    SLOT_IMPORT_CHOICE,
    SLOT_IMPORT_PICK,
    SLOT_QUESTION,
)

ROTATION = len(FOUNDERS) + 1  # a three-city table: facilitator plus two founders


def lazy_table(**overrides):
    """Three cities, seated, with exactly one order filed: the game's first.

    The facilitator files that one because a game cannot start without it
    (spec #4 gives them round 1). Nobody files anything else until asked.
    """
    config = make_config(**overrides)
    game = GameEngine.for_test(
        utc(2026, 9, 1, 12), rng_seed=5, config=config, content=Content.load(config)
    )
    game.register_player(*FACILITATOR, is_facilitator=True)
    for founder in FOUNDERS:
        game.register_player(*founder)
    offer = game.import_choice_offer(FACILITATOR[0])
    game.choose_import(FACILITATOR[0], need_id=offer["suggestions"][0]["need_id"])
    game.start()
    return game


def offered(game, player_id):
    return [slot["kind"] for slot in game.checkin(player_id)["slots"] if slot]


def deferred(game, player_id):
    return [item["kind"] for item in game.checkin(player_id)["deferred"]]


def act(game, player_id):
    """Do everything this round's check-in asks of one mayor."""
    for slot in game.checkin(player_id)["slots"]:
        if slot is None:
            continue
        if slot["kind"] == SLOT_IMPORT_CHOICE:
            game.choose_import(player_id, need_id=slot["suggestions"][0]["need_id"])
        elif slot["kind"] == SLOT_IMPORT_PICK:
            game.pick_winner(player_id, slot["ballot"][0]["ballot_ref"])
        elif slot["kind"] == SLOT_EXPORT:
            game.submit_export(player_id, "a consignment from %s" % player_id)
        elif slot["kind"] == SLOT_QUESTION:
            game.answer_question(player_id, "an answer from %s" % player_id)


def trace(game, limit=20):
    """Play the table out lazily, recording what each round asked of whom."""
    log = []
    while game.phase == "running" and len(log) < limit:
        need = game.collecting_need()
        log.append({
            "round": game.current_round,
            "importing_city": need.importing_city if need else None,
            "importer": need.importing_player_id if need else None,
            "offered": {pid: offered(game, pid) for pid in sorted(game.players)},
            "deferred": {pid: deferred(game, pid) for pid in sorted(game.players)},
        })
        for player_id in sorted(game.players):
            act(game, player_id)
        game.clock.advance(game.timer.window)
        game.tick()
    return log


def order_is_due(game, player_id):
    """What the check-in would be asking for, read from the public offer."""
    if game.unfiled_import_turns(player_id) < 1:
        return False
    opens_in = game.import_choice_offer(player_id)["opens_in_rounds"]
    ahead = game.config.require_int("imports.choice_offered_rounds_ahead")
    return opens_in is not None and opens_in <= ahead


class CurrentTradeIsNeverDisplacedTest(unittest.TestCase):
    """Spec #11a: the order waits; the trade does not."""

    def collision(self, game):
        """Play until some mayor has a pick, an export and an order at once.

        Returns ``(round, player_id)`` without acting on that round, so the
        caller sees the check-in exactly as the collision made it.
        """
        while game.phase == "running":
            need = game.collecting_need()
            if need is not None:
                for player_id in sorted(game.players):
                    pick = game.picking_need_for(player_id)
                    if (
                        pick is not None
                        and game.submissions_for(pick.need_key)
                        and player_id != need.importing_player_id
                        and order_is_due(game, player_id)
                    ):
                        return game.current_round, player_id
            for player_id in sorted(game.players):
                act(game, player_id)
            game.clock.advance(game.timer.window)
            game.tick()
        return None, None

    def test_a_pick_an_export_and_an_order_offer_the_pick_and_the_export(self):
        # A two-round lookahead is what the game shipped with when the smoke
        # test found this; the rule under test is not the lookahead, though, so
        # it is set here rather than relied on.
        game = lazy_table(imports__choice_offered_rounds_ahead=2)
        round_index, player_id = self.collision(game)
        self.assertIsNotNone(
            player_id,
            "no round produced a pick, an export and an order at once, so this "
            "test proved nothing -- rebuild the collision before trusting it",
        )
        checkin = game.checkin(player_id)
        self.assertEqual(
            [slot["kind"] for slot in checkin["slots"]],
            [SLOT_IMPORT_PICK, SLOT_EXPORT],
            "round %d displaced %s's export" % (round_index, player_id),
        )
        self.assertEqual(checkin["pending_game_actions"], 2)
        self.assertEqual([item["kind"] for item in checkin["deferred"]],
                         [SLOT_IMPORT_CHOICE])

    def test_the_deferred_order_is_a_note_and_not_a_slate(self):
        """Deferring means not asking -- so it must not read as an ask."""
        game = lazy_table(imports__choice_offered_rounds_ahead=2)
        _, player_id = self.collision(game)
        notice = game.checkin(player_id)["deferred"][0]
        self.assertNotIn("suggestions", notice)
        self.assertIn("#11a", notice["spec"])
        self.assertIn("can wait", notice["reason"])

    def test_a_deferred_order_may_still_be_filed_and_costs_no_slot(self):
        """A mayor who volunteers has not taken a second turn at the round."""
        game = lazy_table(imports__choice_offered_rounds_ahead=2)
        _, player_id = self.collision(game)
        offer = game.import_choice_offer(player_id)
        game.choose_import(player_id, need_id=offer["suggestions"][0]["need_id"])
        self.assertNotIn(SLOT_IMPORT_CHOICE, game.checkin_used(player_id))
        # ... and the two slots they were actually offered are both still theirs.
        self.assertEqual(
            [slot["kind"] for slot in game.checkin(player_id)["slots"]],
            [SLOT_IMPORT_PICK, SLOT_EXPORT],
        )
        act(game, player_id)
        self.assertEqual(
            sorted(game.checkin_used(player_id)), [SLOT_EXPORT, SLOT_IMPORT_PICK]
        )

    def test_the_deferred_order_is_asked_for_again_and_the_turn_survives(self):
        """Deferring costs the mayor a round of notice, and nothing else."""
        game = lazy_table(imports__choice_offered_rounds_ahead=2)
        deferred_in, player_id = self.collision(game)
        outstanding = game.unfiled_import_turns(player_id)
        self.assertGreaterEqual(outstanding, 1)
        log = trace(game)
        asked = [entry["round"] for entry in log
                 if SLOT_IMPORT_CHOICE in entry["offered"][player_id]]
        self.assertTrue(asked, "the deferred order was never asked for again")
        self.assertGreater(asked[0], deferred_in)
        player = game.players[player_id]
        self.assertEqual(game.unfiled_import_turns(player_id), 0)
        self.assertEqual(player.import_turns_forfeited, 0)
        self.assertEqual(player.import_turns_served, player.import_turns_allotted)

    def test_every_eligible_city_is_offered_every_open_need(self):
        """Spec #11a's headline, over a whole game: nobody sits out a trade."""
        for ahead in (1, 2, 3):
            with self.subTest(ahead=ahead):
                game = lazy_table(imports__choice_offered_rounds_ahead=ahead)
                may_export_to_own = game.config.require_bool(
                    "exports.importer_may_export_to_own_need"
                )
                rounds_with_a_need = 0
                for entry in trace(game):
                    if entry["importer"] is None:
                        continue
                    rounds_with_a_need += 1
                    for player_id, kinds in entry["offered"].items():
                        if player_id == entry["importer"] and not may_export_to_own:
                            continue
                        self.assertIn(
                            SLOT_EXPORT, kinds,
                            "round %d left %s out of the %s trade"
                            % (entry["round"], player_id, entry["importing_city"]),
                        )
                self.assertTrue(rounds_with_a_need)

    def test_no_check_in_exceeds_the_two_action_budget(self):
        for ahead in (1, 2, 3):
            with self.subTest(ahead=ahead):
                game = lazy_table(imports__choice_offered_rounds_ahead=ahead)
                for entry in trace(game):
                    for player_id, kinds in entry["offered"].items():
                        self.assertLessEqual(
                            len(kinds), 2,
                            "round %d offered %s %d slots"
                            % (entry["round"], player_id, len(kinds)),
                        )
                        self.assertEqual(len(kinds), len(set(kinds)))
                        if entry["deferred"][player_id]:
                            # Spec #23: a deferred action still counts as
                            # pending, so deferring one never frees its slot up
                            # for a question.
                            self.assertNotIn(SLOT_QUESTION, kinds)
                            self.assertEqual(len(kinds), 2)


class TheSlotSetIsFixedForTheRoundTest(unittest.TestCase):
    """Spec #11, #23: two actions a round, and the round says which two.

    ``tests/test_checkin_slots.py`` already holds this for the actions a
    cooperative table takes. The two here are the ways an import order could
    move it mid-round, which is why they live with the rest of spec #13's
    fallout: an order falls due when a mayor's first export earns them a queue
    place (spec #5), and stops being due when they file it.
    """

    def test_earning_a_queue_place_does_not_retract_the_round_s_question(self):
        game = lazy_table()
        # Round 1: p2 is not in the queue yet, so no order is due of them and
        # the spare slot is the mayoral question.
        player_id = FOUNDERS[0][0]
        self.assertEqual(offered(game, player_id), [SLOT_EXPORT, SLOT_QUESTION])
        game.submit_export(player_id, "the export that earns a queue place")
        self.assertTrue(game.players[player_id].is_queued)
        # An order is due of them now -- but this round already asked, and it
        # asked for a question.
        self.assertEqual(offered(game, player_id), [SLOT_QUESTION])
        game.answer_question(player_id, "an answer, as invited")
        self.assertEqual(game.rounds[1].answers[player_id], "an answer, as invited")

    def test_filing_an_order_does_not_free_its_slot_for_a_question(self):
        """Otherwise a two-action round quietly becomes a three-action one."""
        game = lazy_table()
        found = None
        while game.phase == "running" and found is None:
            for player_id in sorted(game.players):
                if offered(game, player_id) == [SLOT_IMPORT_CHOICE, SLOT_EXPORT]:
                    found = player_id
                    break
            if found is not None:
                break
            for player_id in sorted(game.players):
                act(game, player_id)
            game.clock.advance(game.timer.window)
            game.tick()
        self.assertIsNotNone(found, "no round offered an order and an export together")
        offer = game.import_choice_offer(found)
        game.choose_import(found, need_id=offer["suggestions"][0]["need_id"])
        self.assertEqual(game.checkin_used(found), {SLOT_IMPORT_CHOICE: 1})
        self.assertEqual(offered(game, found), [SLOT_EXPORT])
        with self.assertRaises(RuleViolation):
            game.answer_question(found, "a third action, in a two-action round")


class ImportChoiceCadenceTest(unittest.TestCase):
    """Spec #13, on the shipped config: asked on the turn, not before it."""

    def test_a_three_city_game_asks_each_mayor_every_three_rounds(self):
        log = trace(lazy_table())
        for player_id in sorted(log[0]["offered"]):
            asked = [entry["round"] for entry in log
                     if SLOT_IMPORT_CHOICE in entry["offered"][player_id]]
            gaps = [b - a for a, b in zip(asked, asked[1:])]
            self.assertTrue(asked, "%s was never asked for an order" % player_id)
            self.assertTrue(
                all(gap >= ROTATION for gap in gaps),
                "%s was asked in rounds %s -- a three-city rotation is %d rounds "
                "long, so anything closer is asking twice for one turn"
                % (player_id, asked, ROTATION),
            )

    def test_a_mayor_is_asked_in_the_check_in_that_belongs_to_their_turn(self):
        """The strong form: the need that opens next round is the asked city's.

        A round's needs open before its check-ins do (spec #9's OPEN), so the
        last check-in before a city's need opens *is* that city's import turn's
        check-in. Asking there is asking on the turn; asking earlier is asking
        a mayor to plan a turn that has not come round.
        """
        game = lazy_table()
        log = trace(game)
        opened_by_round = {
            need.opened_round: need.importing_player_id for need in game.needs.values()
        }
        asks = 0
        for entry in log:
            for player_id, kinds in entry["offered"].items():
                if SLOT_IMPORT_CHOICE not in kinds:
                    continue
                asks += 1
                self.assertEqual(
                    opened_by_round.get(entry["round"] + 1), player_id,
                    "%s was asked in round %d for a turn that did not open in "
                    "round %d" % (player_id, entry["round"], entry["round"] + 1),
                )
        self.assertGreaterEqual(asks, len(game.players))

    def test_a_mayor_is_never_asked_twice_running_for_one_turn(self):
        for entry_a, entry_b in zip(trace(lazy_table()), trace(lazy_table())[1:]):
            for player_id, kinds in entry_a["offered"].items():
                if SLOT_IMPORT_CHOICE in kinds:
                    self.assertNotIn(SLOT_IMPORT_CHOICE, entry_b["offered"][player_id])

    def test_a_turn_the_queue_cannot_see_yet_is_quoted_and_not_asked(self):
        """Round 1: the facilitator's is the only city in the queue (spec #5).

        Their second turn is four rounds off, but the queue as it stands says
        one -- everyone else is registered and not yet appended. Quoting that
        floor is what asked a mayor in round 1 to order for round 5.
        """
        game = lazy_table()
        unqueued = [p for p in game.players.values() if not p.is_queued]
        self.assertEqual(len(unqueued), len(FOUNDERS))
        self.assertNotIn(SLOT_IMPORT_CHOICE, offered(game, FACILITATOR[0]))
        offer = game.import_choice_offer(FACILITATOR[0])
        self.assertEqual(offer["opens_in_rounds"], 1 + len(unqueued))
        self.assertTrue(offer["suggestions"], "the offer is still there to take")

    def test_the_estimate_tightens_as_the_queue_fills(self):
        game = lazy_table()
        for player_id, _, _ in FOUNDERS:
            game.submit_export(player_id, "the export that earns a queue place")
        self.assertEqual(
            game.import_choice_offer(FACILITATOR[0])["opens_in_rounds"], 3
        )

    def test_a_zero_lookahead_asks_only_once_the_turn_is_being_held(self):
        """The other legal setting, and why it is not the shipped one.

        At 0 nobody is asked ahead at all, so every turn after the first spends
        a round held open while its mayor is asked for it -- a real facilitator
        choice for a table that orders at the table, and a slower game for one
        that does not. The turns still all get filed and none is forfeited.
        """
        game = lazy_table(imports__choice_offered_rounds_ahead=0)
        held = 0
        for entry in trace(game, limit=30):
            if entry["importer"] is None:
                held += 1
            for player_id, kinds in entry["offered"].items():
                if SLOT_IMPORT_CHOICE not in kinds:
                    continue
                self.assertEqual(
                    entry["importer"], None,
                    "round %d asked %s for an order without holding a turn open"
                    % (entry["round"], player_id),
                )
        self.assertTrue(held)
        for player in game.players.values():
            self.assertEqual(player.import_turns_forfeited, 0)

    def test_a_turn_inside_this_rotation_is_never_padded(self):
        """Only later-rotation turns can be pushed back by a new entrant.

        A player enters at the *end* of the queue (spec #5), which is behind
        every turn this rotation still has to open -- so padding those would be
        pessimism with nothing behind it, and would ask their mayors late.
        """
        game = lazy_table()
        founder = FOUNDERS[0][0]
        game.submit_export(founder, "the export that earns a queue place")
        # The other founder is still unqueued, and cannot come between this one
        # and the rotation-1 turn now at the front of the queue.
        self.assertFalse(game.players[FOUNDERS[1][0]].is_queued)
        self.assertEqual(game.import_choice_offer(founder)["opens_in_rounds"], 1)
        self.assertIn(SLOT_IMPORT_CHOICE, offered(game, founder))


if __name__ == "__main__":
    unittest.main()
