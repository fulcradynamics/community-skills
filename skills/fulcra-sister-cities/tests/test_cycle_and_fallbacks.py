"""Spec #15-#20: exports, winner picks, profit, and the three fallback paths.

The three fallbacks are the heart of this milestone:

* #16 a player who submits nothing is silently skipped -- no penalty
* #17 *nobody* submits, so the importing city ramps up its own industry and the
      importing mayor still takes the rolled profit
* #19 the importer never picks, so every submission wins and the profit is split
      evenly among their cities
"""

import unittest
from fractions import Fraction

from harness import advance, everyone_exports, new_game, pick_first, play_out
from engine.errors import PickRejected, SubmissionRejected
from engine.state import EVEN_SPLIT, RAMP_UP, WINNER_PICK


def resolved(game, need_key):
    return game.needs[need_key].resolution


def awarded(resolution):
    """city -> exact Fraction awarded by this resolution."""
    out = {}
    for award in resolution["awards"]:
        numerator, denominator = award["profit"]["exact"].split("/")
        out[award["city"]] = Fraction(int(numerator), int(denominator))
    return out


class WinnerPickTest(unittest.TestCase):
    def test_a_picked_winner_takes_the_whole_roll(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        pick_first(game, "p1")
        advance(game)
        resolution = resolved(game, "in-001")
        self.assertEqual(resolution["mode"], WINNER_PICK)
        self.assertEqual(len(resolution["awards"]), 1)
        self.assertEqual(len(resolution["winning_ballot_refs"]), 1)
        (city, amount), = awarded(resolution).items()
        self.assertEqual(amount, resolution["roll"]["total"])
        self.assertEqual(game.player_for_city(city).cumulative_profit, amount)

    def test_exactly_one_submission_is_marked_a_winner(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        pick_first(game, "p1")
        advance(game)
        winners = [s for s in game.submissions_for("in-001") if s.is_winner]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(game.submissions_for("in-001")), 2)

    def test_only_the_importing_mayor_may_pick(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        with self.assertRaises(PickRejected):
            game.pick_winner("p3", "A", need_key="in-001")

    def test_a_ballot_ref_that_is_not_on_the_ballot_is_refused(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        with self.assertRaises(PickRejected):
            game.pick_winner("p1", "Z")

    def test_a_second_pick_is_refused(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        pick_first(game, "p1")
        with self.assertRaises(PickRejected):
            game.pick_winner("p1", "B")

    def test_the_roll_uses_the_dice_expression_from_config(self):
        # Proves 2d6 is parsed, not assumed: 3d1 can only ever total 3.
        game = new_game(economy__profit_roll="3d1")
        everyone_exports(game)
        advance(game)
        pick_first(game, "p1")
        advance(game)
        resolution = resolved(game, "in-001")
        self.assertEqual(resolution["roll"]["dice"], [1, 1, 1])
        self.assertEqual(resolution["roll"]["total"], 3)

    def test_a_2d6_roll_stays_within_2_and_12(self):
        game = play_out(new_game())
        for need in game.needs.values():
            roll = need.resolution["roll"]
            self.assertEqual(roll["expression"], "2d6")
            self.assertEqual(len(roll["dice"]), 2)
            self.assertGreaterEqual(roll["total"], 2)
            self.assertLessEqual(roll["total"], 12)


class SkipFallbackTest(unittest.TestCase):
    """Spec #16: no submission from a player is a silent skip."""

    def test_a_silent_player_is_neither_penalised_nor_substituted(self):
        game = new_game()
        everyone_exports(game, exclude=("p3",))
        advance(game)
        self.assertEqual(len(game.submissions_for("in-001")), 1)
        pick_first(game, "p1")
        advance(game)
        resolution = resolved(game, "in-001")
        self.assertEqual(resolution["submission_count"], 1)
        # Silence costs nothing and is replaced by nothing.
        self.assertEqual(game.players["p3"].cumulative_profit, Fraction(0))
        self.assertNotIn("p3", str(resolution))
        self.assertEqual(game.players["p3"].import_turns_served, 0)

    def test_skipping_one_round_does_not_forfeit_later_rounds(self):
        game = new_game()
        everyone_exports(game, exclude=("p3",))
        advance(game)
        everyone_exports(game)  # p3 turns up this time
        self.assertTrue(game.players["p3"].is_queued)
        play_out(game)
        self.assertEqual(game.players["p3"].import_turns_served, 2)


class RampUpFallbackTest(unittest.TestCase):
    """Spec #17: zero submissions at all."""

    def test_zero_submissions_ramps_up_the_import_citys_own_industry(self):
        game = new_game()
        advance(game, 2)  # nobody exports for in-001
        resolution = resolved(game, "in-001")
        self.assertEqual(resolution["mode"], RAMP_UP)
        self.assertEqual(resolution["submission_count"], 0)
        self.assertEqual(
            resolution["newspaper"]["framing_hint"],
            "import_city_ramped_up_its_own_industry",
        )

    def test_the_import_mayor_still_receives_the_rolled_profit(self):
        game = new_game()
        advance(game, 2)
        resolution = resolved(game, "in-001")
        awards = awarded(resolution)
        self.assertEqual(list(awards), ["Reykjavík"])
        self.assertEqual(awards["Reykjavík"], resolution["roll"]["total"])
        self.assertEqual(
            game.players["p1"].cumulative_profit, Fraction(resolution["roll"]["total"])
        )

    def test_there_is_nothing_to_pick_when_nobody_submitted(self):
        game = new_game()
        advance(game)
        with self.assertRaises(PickRejected) as caught:
            game.pick_winner("p1", "A", need_key="in-001")
        self.assertIn("#17", str(caught.exception))


class EvenSplitFallbackTest(unittest.TestCase):
    """Spec #19: the importer let the picking window lapse."""

    def test_no_pick_by_the_deadline_makes_every_submission_a_winner(self):
        game = new_game()
        everyone_exports(game)
        advance(game, 2)  # p1 never picks
        resolution = resolved(game, "in-001")
        self.assertEqual(resolution["mode"], EVEN_SPLIT)
        self.assertEqual(len(resolution["winning_ballot_refs"]), 2)
        self.assertTrue(all(s.is_winner for s in game.submissions_for("in-001")))

    def test_the_profit_is_split_evenly_among_the_submitting_cities(self):
        game = new_game()
        everyone_exports(game)
        advance(game, 2)
        resolution = resolved(game, "in-001")
        awards = awarded(resolution)
        self.assertEqual(set(awards), {"Valparaíso", "Hobart"})
        self.assertEqual(len(set(awards.values())), 1, "shares are not equal")
        self.assertEqual(sum(awards.values()), Fraction(resolution["roll"]["total"]))

    def test_an_odd_roll_split_three_ways_stays_exact(self):
        game = new_game(
            founders=[("p2", "@bo", "Valparaíso"), ("p3", "@cy", "Hobart"),
                      ("p4", "@di", "Tromsø")],
            economy__profit_roll="1d1",
        )
        everyone_exports(game)
        advance(game, 2)
        resolution = resolved(game, "in-001")
        awards = awarded(resolution)
        self.assertEqual(len(awards), 3)
        self.assertEqual(set(awards.values()), {Fraction(1, 3)})
        self.assertEqual(sum(awards.values()), Fraction(1))
        # And the display value never leaks binary float noise into the paper.
        self.assertEqual(resolution["awards"][0]["profit"]["display"], "0.33")

    def test_the_floor_split_mode_keeps_the_ledger_in_whole_numbers(self):
        game = new_game(
            economy__profit_roll="1d1", economy__even_split_mode="floor_discard_remainder"
        )
        everyone_exports(game)
        advance(game, 2)
        awards = awarded(resolved(game, "in-001"))
        self.assertEqual(set(awards.values()), {Fraction(0)})

    def test_the_importer_earns_nothing_when_they_fail_to_pick(self):
        game = new_game()
        everyone_exports(game)
        advance(game, 2)
        self.assertEqual(game.players["p1"].cumulative_profit, Fraction(0))

    def test_a_city_that_submitted_twice_does_not_take_a_double_share(self):
        """#19 splits among *cities*, so submitting twice cannot buy a bigger cut.

        Only reachable when config lifts the #15 cap above one submission, which
        is exactly when a per-submission split would make export spam pay.
        """
        game = new_game(
            exports__max_submissions_per_player_per_import_per_round=2,
            economy__profit_roll="1d1",
        )
        game.submit_export("p2", "first from Valparaíso")
        game.submit_export("p2", "second from Valparaíso")
        game.submit_export("p3", "the only one from Hobart")
        advance(game, 2)  # p1 never picks
        resolution = resolved(game, "in-001")
        self.assertEqual(resolution["mode"], EVEN_SPLIT)
        # All three exports won (#19), but there are two cities to pay.
        self.assertEqual(len(resolution["winning_ballot_refs"]), 3)
        awards = awarded(resolution)
        self.assertEqual(len(resolution["awards"]), 2, "a city was paid twice")
        self.assertEqual(awards, {"Valparaíso": Fraction(1, 2), "Hobart": Fraction(1, 2)})
        self.assertEqual(sum(awards.values()), Fraction(1))
        self.assertEqual(
            game.players["p2"].cumulative_profit, game.players["p3"].cumulative_profit
        )


class SubmissionRulesTest(unittest.TestCase):
    def test_one_export_per_player_per_need_per_round(self):
        game = new_game()
        game.submit_export("p2", "first")
        with self.assertRaises(SubmissionRejected):
            game.submit_export("p2", "second")

    def test_the_cap_comes_from_config(self):
        game = new_game(exports__max_submissions_per_player_per_import_per_round=2)
        game.submit_export("p2", "first")
        game.submit_export("p2", "second")
        self.assertEqual(len(game.submissions_for("in-001")), 2)
        with self.assertRaises(SubmissionRejected):
            game.submit_export("p2", "third")

    def test_exports_are_freeform_text_and_must_say_something(self):
        game = new_game()
        for empty in ("", "   ", None):
            with self.assertRaises(SubmissionRejected):
                game.submit_export("p2", empty)

    def test_the_importing_mayor_does_not_export_to_their_own_need(self):
        game = new_game()
        with self.assertRaises(SubmissionRejected):
            game.submit_export("p1", "conveniently, exactly what I asked for")

    def test_config_can_allow_the_importer_to_export_to_their_own_need(self):
        game = new_game(exports__importer_may_export_to_own_need=True)
        submission = game.submit_export("p1", "self-sufficiency, boxed")
        self.assertIsNotNone(submission)

    def test_an_export_to_a_closed_window_is_refused(self):
        game = new_game()
        advance(game)
        with self.assertRaises(SubmissionRejected):
            game.submit_export("p2", "too late", need_key="in-001")


class EconomyTest(unittest.TestCase):
    def test_profit_accumulates_across_the_whole_game(self):
        game = play_out(new_game())
        total_rolled = Fraction(0)
        for need in game.needs.values():
            total_rolled += sum(awarded(need.resolution).values())
        total_held = sum(p.cumulative_profit for p in game.players.values())
        self.assertEqual(total_held, total_rolled)

    def test_the_leaderboard_ranks_cities_by_cumulative_profit(self):
        game = play_out(new_game())
        board = game.leaderboard()
        self.assertEqual([row["rank"] for row in board], list(range(1, len(board) + 1)))
        values = [row["profit"]["approx"] for row in board]
        self.assertEqual(values, sorted(values, reverse=True))
        for row in board:
            self.assertEqual(row["mayor"], "the Mayor of %s" % row["city"])


class DeterminismTest(unittest.TestCase):
    def test_the_same_seed_replays_the_same_game(self):
        first = play_out(new_game(seed=7))
        second = play_out(new_game(seed=7))
        self.assertEqual(first.describe()["needs"], second.describe()["needs"])
        self.assertEqual(
            [n.resolution["roll"] for n in first.needs.values()],
            [n.resolution["roll"] for n in second.needs.values()],
        )

    def test_a_different_seed_gives_a_different_game(self):
        first = play_out(new_game(seed=7))
        second = play_out(new_game(seed=8))
        self.assertNotEqual(
            [n.content_need_id for n in first.needs.values()],
            [n.content_need_id for n in second.needs.values()],
        )


if __name__ == "__main__":
    unittest.main()
