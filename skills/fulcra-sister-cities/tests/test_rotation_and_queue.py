"""Spec #4, #5, #12: the city order queue, and who gets how many import turns."""

import unittest

from harness import (
    FACILITATOR, FOUNDERS, LATECOMER, advance, everyone_exports, file_orders,
    make_config, new_game, play_out,
)
from engine import Content, GameEngine
from engine.clock import utc
from engine.errors import RosterError


class FacilitatorFirstTest(unittest.TestCase):
    def test_the_facilitator_holds_queue_position_one(self):
        game = new_game(start=False)
        self.assertEqual(game.queue.order, ["p1"])
        self.assertEqual(game.queue.position("p1"), 1)

    def test_the_facilitator_is_queued_without_exporting_first(self):
        # Spec #5's first-export rule is exactly what spec #4 exempts them from;
        # otherwise round 1 would have no import need to open.
        game = new_game(start=False)
        facilitator = game.players["p1"]
        self.assertTrue(facilitator.is_queued)
        self.assertEqual(facilitator.queued_round, 0)
        self.assertEqual(game.submissions, {})

    def test_round_one_opens_the_facilitators_import_need(self):
        game = new_game()
        need = game.collecting_need()
        self.assertEqual(need.opened_round, 1)
        self.assertEqual(need.importing_city, FACILITATOR[2])
        self.assertEqual(need.importing_player_id, "p1")

    def test_a_second_facilitator_is_refused(self):
        game = new_game(start=False)
        with self.assertRaises(RosterError):
            game.register_player("p9", "@ze", "Osaka", is_facilitator=True)

    def test_a_facilitator_cannot_be_appointed_after_the_game_starts(self):
        game = new_game()
        with self.assertRaises(RosterError):
            game.register_player("p9", "@ze", "Osaka", is_facilitator=True)

    def test_a_game_cannot_start_without_a_facilitator(self):
        config = make_config()
        game = GameEngine.for_test(utc(2026, 9, 1, 12), rng_seed=1, config=config,
                                   content=Content.load(config))
        for player in [("pa", "@a", "Lisbon"), ("pb", "@b", "Cork"), ("pc", "@c", "Dakar")]:
            game.register_player(*player)
        with self.assertRaises(RosterError):
            game.start()


class QueueOnFirstExportTest(unittest.TestCase):
    def test_a_player_is_not_queued_until_their_first_export(self):
        game = new_game()
        for player_id in ("p2", "p3"):
            player = game.players[player_id]
            self.assertFalse(player.is_queued)
            self.assertIsNone(player.import_turns_allotted)
            self.assertIsNone(game.queue.position(player_id))

    def test_the_first_export_is_what_queues_a_player(self):
        game = new_game()
        game.submit_export("p3", "a far side, flat-packed")
        self.assertEqual(game.queue.position("p3"), 2)
        self.assertEqual(game.players["p3"].queued_round, 1)
        self.assertTrue(game.players["p3"].is_queued)
        self.assertIsNone(game.queue.position("p2"))

    def test_queue_order_follows_first_export_order_not_registration_order(self):
        game = new_game()
        game.submit_export("p3", "third-registered, first to answer")
        game.submit_export("p2", "second-registered, second to answer")
        self.assertEqual(game.queue.order, ["p1", "p3", "p2"])
        advance(game)
        self.assertEqual(game.collecting_need().importing_player_id, "p3")

    def test_a_player_who_never_exports_never_receives_an_import_need(self):
        # Spec #5 read together with #16: silence is a skip, and an unqueued
        # mayor is simply never assigned a need. No penalty, no substitution.
        game = new_game()
        while game.phase == "running":
            everyone_exports(game, exclude=("p3",))
            advance(game)
        silent = game.players["p3"]
        self.assertFalse(silent.is_queued)
        self.assertEqual(silent.import_turns_served, 0)
        self.assertNotIn("p3", game.queue.order)
        self.assertFalse(
            any(need.importing_player_id == "p3" for need in game.needs.values())
        )

    def test_an_export_is_allowed_before_being_queued(self):
        game = new_game()
        self.assertFalse(game.players["p2"].is_queued)
        submission = game.submit_export("p2", "allowed, and the way in")
        self.assertIsNotNone(submission)


class RotationCountTest(unittest.TestCase):
    def test_founders_present_through_rotation_one_get_two_import_turns(self):
        game = play_out(new_game())
        for player_id in ("p1", "p2", "p3"):
            player = game.players[player_id]
            self.assertEqual(player.import_turns_allotted, 2)
            self.assertEqual(player.import_turns_served, 2)

    def test_every_city_gets_one_need_per_rotation(self):
        game = play_out(new_game())
        for player_id in ("p1", "p2", "p3"):
            city = game.players[player_id].city
            rotations = sorted(
                need.rotation for need in game.needs.values() if need.importing_city == city
            )
            self.assertEqual(rotations, [1, 2])

    def test_joining_before_rotation_one_closes_earns_two_import_turns(self):
        game = new_game()
        everyone_exports(game)
        advance(game)          # round 2, rotation 1 still walking
        everyone_exports(game)
        advance(game)          # round 3
        game.register_player(*LATECOMER)
        game.submit_export("p4", "late but inside rotation one")
        self.assertFalse(game.queue.rotation_1_closed)
        self.assertEqual(game.players["p4"].import_turns_allotted, 2)
        play_out(game)
        self.assertEqual(game.players["p4"].import_turns_served, 2)

    def test_joining_after_rotation_one_closes_earns_one_import_turn(self):
        game = new_game()
        for _ in range(4):
            everyone_exports(game)
            advance(game)
        # Rotation 1 closed when the queue cursor ran off the end of the queue.
        self.assertTrue(game.queue.rotation_1_closed)
        self.assertEqual(game.queue.rotation, 2)
        game.register_player(*LATECOMER)
        game.submit_export("p4", "arrived in rotation two")
        self.assertEqual(game.players["p4"].import_turns_allotted, 1)
        play_out(game)
        self.assertEqual(game.players["p4"].import_turns_served, 1)
        self.assertEqual(
            len([n for n in game.needs.values() if n.importing_player_id == "p4"]), 1
        )

    def test_rotation_one_closes_exactly_once_and_is_recorded(self):
        game = play_out(new_game())
        self.assertIn(1, game.queue.rotation_closed_rounds)
        self.assertEqual(game.queue.rotation_closed_rounds[1], 4)
        self.assertTrue(game.queue.exhausted)

    def test_rotations_target_comes_from_config(self):
        game = play_out(new_game(rounds__rotations_target=1))
        for player_id in ("p1", "p2", "p3"):
            self.assertEqual(game.players[player_id].import_turns_allotted, 1)
            self.assertEqual(game.players[player_id].import_turns_served, 1)
        self.assertEqual(len(game.needs), 3)

    def test_three_rotations_if_config_says_so(self):
        game = play_out(new_game(rounds__rotations_target=3))
        self.assertEqual(len(game.needs), 9)
        for need in game.needs.values():
            self.assertIn(need.rotation, (1, 2, 3))


class CityCollisionTest(unittest.TestCase):
    """Spec #2 belongs to the join milestone; the engine's part is to refuse.

    Resolving a collision (reassigning to a geographically close alternative) is
    not this milestone's scope. What *is* required here is that a collision is
    never silently allowed, because every piece of state in this engine is keyed
    by city -- so the engine refuses and hands over the candidate list.
    """

    def test_a_duplicate_city_is_refused_not_silently_shared(self):
        from engine.errors import DuplicateCity

        game = new_game(start=False)
        with self.assertRaises(DuplicateCity) as caught:
            game.register_player("p9", "@ze", "Reykjavík")
        self.assertEqual(caught.exception.held_by, "p1")
        self.assertNotIn("p9", game.players)

    def test_a_differently_typed_duplicate_is_still_a_duplicate(self):
        from engine.errors import DuplicateCity

        game = new_game(start=False)
        for spelling in ("reykjavik", "  REYKJAVÍK  ", "Reykjavik"):
            with self.assertRaises(DuplicateCity):
                game.register_player("p9", "@ze", spelling)

    def test_the_refusal_carries_the_alternatives_the_join_step_will_need(self):
        from engine.errors import DuplicateCity

        game = new_game(start=False)
        try:
            game.register_player("p9", "@ze", "Reykjavík")
            self.fail("expected DuplicateCity")
        except DuplicateCity as error:
            self.assertTrue(error.alternatives)
            self.assertNotIn("Reykjavík", error.alternatives)


class RosterLimitsTest(unittest.TestCase):
    def test_min_players_is_enforced_at_start(self):
        config = make_config()
        game = GameEngine.for_test(utc(2026, 9, 1, 12), rng_seed=1, config=config,
                                   content=Content.load(config))
        game.register_player(*FACILITATOR, is_facilitator=True)
        game.register_player(*FOUNDERS[0])
        file_orders(game)
        with self.assertRaises(RosterError):
            game.start()
        game.register_player(*FOUNDERS[1])
        file_orders(game)
        game.start()
        self.assertEqual(game.phase, "running")

    def test_max_players_is_enforced(self):
        config = make_config(players__max_players=3)
        game = new_game(config=config, start=False)
        with self.assertRaises(RosterError):
            game.register_player("p4", "@di", "Tromsø")


if __name__ == "__main__":
    unittest.main()
