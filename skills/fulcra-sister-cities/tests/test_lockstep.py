"""Spec #9-#12: one round timer, three operations per round, in order."""

import unittest

from harness import advance, everyone_exports, new_game, play_out
from engine import LOCKSTEP_OPS
from engine import audit
from engine.errors import PhaseError, PickRejected
from engine.state import COLLECTING, PICKING, RESOLVED


class LockstepOrderingTest(unittest.TestCase):
    def test_every_round_runs_the_three_operations_in_spec_order(self):
        game = play_out(new_game())
        self.assertEqual(game.phase, "ended")
        self.assertGreater(len(game.rounds), 1)
        for index, record in sorted(game.rounds.items()):
            self.assertEqual(
                record.ops,
                list(LOCKSTEP_OPS),
                "round %d ran %s, expected OPEN/CLOSE/RESOLVE" % (index, record.ops),
            )

    def test_no_round_opens_closes_or_resolves_twice(self):
        game = play_out(new_game())
        for index, record in game.rounds.items():
            for op in LOCKSTEP_OPS:
                self.assertEqual(
                    len([e for e in record.events if e["op"] == op]),
                    1,
                    "round %d has more than one %s" % (index, op),
                )

    def test_each_need_opens_closes_and_resolves_one_round_apart(self):
        game = play_out(new_game())
        for need in game.needs.values():
            self.assertEqual(need.status, RESOLVED)
            self.assertEqual(
                need.closed_round,
                need.opened_round + 1,
                "%s closed in round %s, not the round after it opened"
                % (need.need_key, need.closed_round),
            )
            self.assertEqual(
                need.resolved_round,
                need.opened_round + 2,
                "%s resolved in round %s; spec #18 gives the importer the whole "
                "round after collection" % (need.need_key, need.resolved_round),
            )

    def test_one_need_collecting_and_one_picking_at_any_moment(self):
        game = new_game()
        while game.phase == "running":
            statuses = [need.status for need in game.needs.values()]
            self.assertLessEqual(
                statuses.count(COLLECTING), 1, "two export windows open at once"
            )
            self.assertLessEqual(
                statuses.count(PICKING), 1, "two needs awaiting a pick at once"
            )
            everyone_exports(game)
            advance(game)

    def test_a_three_mayor_game_is_six_needs_over_eight_rounds(self):
        # 3 cities x 2 rotations = 6 import needs, plus the two rounds needed to
        # close and resolve the last one.
        game = play_out(new_game())
        self.assertEqual(len(game.needs), 6)
        self.assertEqual(max(game.rounds), 8)
        self.assertEqual(game.ended_round, 8)

    def test_the_final_rounds_open_nothing_but_still_close_and_resolve(self):
        game = play_out(new_game())
        opened = {
            index: [e for e in record.events if e["op"] == "OPEN"][0]["need"]
            for index, record in game.rounds.items()
        }
        self.assertEqual([opened[i] for i in range(1, 7)].count(None), 0)
        self.assertIsNone(opened[7], "round 7 should open nothing; every city is served")
        self.assertIsNone(opened[8])
        # ...but the tail still drains, which is why those rounds exist at all.
        resolved = [
            e for e in game.rounds[8].events if e["op"] == "RESOLVE" and e["need"]
        ]
        self.assertEqual(len(resolved), 1)


class SingleTimerTest(unittest.TestCase):
    def test_the_game_holds_exactly_one_timer(self):
        game = new_game()
        self.assertEqual(list(game.timers()), ["round"])

    def test_no_state_object_carries_its_own_deadline(self):
        # Spec #9 forbids per-phase timers. Any deadline field on a need, a
        # submission or a player would be exactly that.
        self.assertEqual(audit.find_extra_timers(), [])

    def test_rounds_advance_only_when_the_round_window_elapses(self):
        game = new_game()
        self.assertEqual(game.current_round, 1)
        game.clock.advance(game.timer.window / 2)
        game.tick()
        self.assertEqual(game.current_round, 1, "a half window advanced the round")
        game.clock.advance(game.timer.window / 2)
        game.tick()
        self.assertEqual(game.current_round, 2)

    def test_a_long_silence_catches_up_every_missed_round(self):
        game = new_game()
        game.clock.advance(game.timer.window * 3)
        advanced = game.tick()
        self.assertEqual(len(advanced), 3)
        self.assertEqual(game.current_round, 4)
        for record in advanced:
            self.assertEqual(record.ops, list(LOCKSTEP_OPS))

    def test_round_boundaries_come_from_the_one_timer(self):
        game = new_game()
        timer = game.timer
        for index in range(1, 6):
            self.assertEqual(timer.round_end(index), timer.round_start(index + 1))
        self.assertEqual(timer.round_index_at(timer.round_start(4)), 4)
        self.assertEqual(
            timer.round_index_at(timer.round_end(4) - timer.window / 1000), 4
        )

    def test_an_ended_game_refuses_to_advance(self):
        game = play_out(new_game())
        with self.assertRaises(PhaseError):
            game.advance_round()
        self.assertEqual(game.tick(), [])


class PickingWindowTest(unittest.TestCase):
    def test_the_importer_cannot_pick_in_the_round_exports_are_collected(self):
        # Spec #18: the pick happens the round AFTER collection.
        game = new_game()
        everyone_exports(game)
        need = game.collecting_need()
        self.assertEqual(need.status, COLLECTING)
        with self.assertRaises(PickRejected):
            game.pick_winner(need.importing_player_id, "A")

    def test_the_importer_picks_in_the_round_after_collection(self):
        game = new_game()
        everyone_exports(game)
        need = game.collecting_need()
        advance(game)
        self.assertEqual(need.status, PICKING)
        self.assertEqual(need.closed_round, game.current_round)
        pick = game.pick_winner(need.importing_player_id, "A")
        self.assertEqual(pick["picked_round"], 2)

    def test_a_pick_that_arrives_too_late_is_refused(self):
        game = new_game()
        everyone_exports(game)
        need = game.collecting_need()
        advance(game, 2)
        self.assertEqual(need.status, RESOLVED)
        with self.assertRaises(PickRejected):
            game.pick_winner(need.importing_player_id, "A", need_key=need.need_key)


if __name__ == "__main__":
    unittest.main()
