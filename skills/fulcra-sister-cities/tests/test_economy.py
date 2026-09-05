"""Spec #20-#22: the profit roll, the cumulative leaderboard, and exposure.

Three questions, and the third one is why this module exists separately from
``test_cycle_and_fallbacks`` (which checks that each *fallback* awards profit at
all):

* #20 -- does a roll land in the range the configured dice can produce, and does
  it accumulate *per city*, exactly, across a whole game?
* #22 -- does the newspaper's leaderboard follow
  ``economy.leaderboard_visible_in_newspaper``, both ways, everywhere?
* #21 -- and is a losing export's origin city *un*-configurable: off with no knob
  to turn it on, rather than off by default?

The last one is a test about the absence of something, which is the kind of
requirement that quietly stops being true. So it is checked four ways: the
constant, the config document, a detector proven to detect, and a game played
out with a fabricated knob switched on to show it changes nothing.
"""

import copy
import json
import os
import re
import unittest
from fractions import Fraction

from harness import (
    FOUNDERS,
    advance,
    everyone_exports,
    make_config,
    new_game,
    pick_first,
    play_out,
)
from engine import Config, Content, GameEngine, audit, views
from engine.config import repo_root
from engine.economy import (
    CONFIGURABLE_EXPOSURE_KEYS,
    NON_WINNER_ORIGIN_EXPOSURE,
    Economy,
    exposure_knob_match,
)
from engine.errors import (
    ConfigError,
    ExposurePolicyViolation,
    MissingConfigKey,
    RuleViolation,
)
from engine.views import ORIGIN_WITHHELD

FOUR_FOUNDERS = FOUNDERS + [("p4", "@di", "Tromsø")]


def exact(profit_json):
    """The authoritative value out of a rendered profit."""
    numerator, denominator = profit_json["exact"].split("/")
    return Fraction(int(numerator), int(denominator))


def awards_by_city(game):
    """city -> exact total credited to it by every resolution in the game."""
    totals = {}
    for need in game.needs.values():
        if not need.resolution:
            continue
        for award in need.resolution["awards"]:
            totals[award["city"]] = totals.get(award["city"], Fraction(0)) + exact(
                award["profit"]
            )
    return totals


def raw_config():
    with open(os.path.join(repo_root(), "config.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def config_with(**dotted):
    """config.json plus keys that do not exist in it -- for #21's knob test."""
    data = copy.deepcopy(raw_config())
    for path, value in dotted.items():
        node = data
        parts = path.split("__")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return Config(data, source="config.json plus fabricated %s" % sorted(dotted))


def abandoned_game(**overrides):
    """A game where nobody ever picks: every need resolves by even split (#19)."""
    game = new_game(**overrides)
    while game.phase == "running":
        everyone_exports(game)
        advance(game)
    return game


def silent_game(**overrides):
    """A game where nobody ever exports: every need ramps up (#17)."""
    game = new_game(**overrides)
    while game.phase == "running":
        advance(game)
    return game


class ProfitRollRangeTest(unittest.TestCase):
    """#20: the roll is the configured dice, and it cannot leave their range."""

    def _assert_rolls_are_sane(self, game):
        economy = game.economy
        resolved = 0
        for need in game.needs.values():
            roll = need.resolution["roll"]
            self.assertEqual(roll["expression"], economy.expression)
            self.assertEqual(len(roll["dice"]), economy.dice_count)
            for die in roll["dice"]:
                self.assertGreaterEqual(die, 1)
                self.assertLessEqual(die, economy.dice_sides)
            self.assertEqual(roll["total"], sum(roll["dice"]))
            self.assertTrue(
                economy.in_range(roll["total"]),
                "%s is outside %s's range %s"
                % (roll["total"], economy.expression, [economy.min_roll, economy.max_roll]),
            )
            resolved += 1
        self.assertGreater(resolved, 0, "the game resolved nothing to check")

    def test_every_roll_of_a_played_out_game_is_in_range(self):
        self._assert_rolls_are_sane(play_out(new_game()))

    def test_every_roll_is_in_range_on_the_even_split_path_too(self):
        self._assert_rolls_are_sane(abandoned_game())

    def test_every_roll_is_in_range_on_the_ramp_up_path_too(self):
        self._assert_rolls_are_sane(silent_game())

    def test_the_range_is_the_configured_dice_not_two_sixes(self):
        game = play_out(new_game(economy__profit_roll="3d4"))
        self.assertEqual([game.economy.min_roll, game.economy.max_roll], [3, 12])
        self._assert_rolls_are_sane(game)
        for need in game.needs.values():
            self.assertEqual(len(need.resolution["roll"]["dice"]), 3)
            self.assertLessEqual(max(need.resolution["roll"]["dice"]), 4)

    def test_2d6_actually_reaches_both_ends_of_its_range(self):
        """In range is necessary but not sufficient -- a clamped roll would pass
        the range check while never producing a 2 or a 12."""
        seen = set()
        for seed in range(1, 60):
            for need in play_out(new_game(seed=seed)).needs.values():
                seen.add(need.resolution["roll"]["total"])
        self.assertEqual(seen, set(range(2, 13)), "2d6 did not cover 2..12")

    def test_the_roll_has_the_shape_of_two_dice_and_not_a_flat_range(self):
        """In-range is necessary but weak: ``randint(2, 12)`` would pass every
        check above while being a different economy -- a 2 as likely as a 7.

        Deterministic, not a gamble: the engine's per-need profit stream is
        seeded by ``(seed, "profit", need_key)``, so drawing one roll from 8000
        distinct need keys samples exactly what a very long game would, and the
        numbers are the same on every run.
        """
        game = new_game()
        counts = {}
        draws = 8000
        for index in range(draws):
            total = game.economy.roll(game._rng("profit", "in-%05d" % index)).total
            counts[total] = counts.get(total, 0) + 1

        ways = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}
        self.assertEqual(set(counts), set(ways), "not every 2d6 total came up")
        self.assertEqual(max(counts, key=lambda total: counts[total]), 7)
        for total, combinations in ways.items():
            observed = counts[total] / draws
            expected = combinations / 36
            self.assertLess(
                abs(observed - expected),
                0.02,
                "P(%d) was %.3f, a 2d6 gives %.3f" % (total, observed, expected),
            )
        # The specific thing being ruled out.
        self.assertGreater(counts[7], 3 * counts[2])

    def test_two_needs_in_one_game_do_not_share_a_profit_stream(self):
        game = new_game()
        first = [game.economy.roll(game._rng("profit", "in-001")).dice for _ in range(3)]
        second = [game.economy.roll(game._rng("profit", "in-002")).dice for _ in range(3)]
        # Each call re-derives the stream, so a repeat call repeats itself...
        self.assertEqual(len(set(map(tuple, first))), 1)
        # ...but a different need is a different stream. (Same-value collisions
        # are legal; what matters is that the keys are not the same stream.)
        self.assertNotEqual(
            game._rng("profit", "in-001").random(), game._rng("profit", "in-002").random()
        )
        self.assertNotEqual(first, second)

    def test_a_die_is_never_zero_or_negative(self):
        economy = Economy(make_config(economy__profit_roll="2d6"))
        self.assertFalse(economy.in_range(1))
        self.assertFalse(economy.in_range(0))
        self.assertFalse(economy.in_range(13))
        self.assertTrue(economy.in_range(2))
        self.assertTrue(economy.in_range(12))

    def test_a_malformed_dice_expression_is_a_startup_error_not_a_round_3_crash(self):
        for broken in ("2dd6", "d6", "two d six", "", "0d6", "2d0"):
            with self.assertRaises(ConfigError, msg="%r was accepted" % broken):
                new_game(economy__profit_roll=broken)

    def test_a_malformed_split_mode_is_refused_at_startup(self):
        with self.assertRaises(ConfigError):
            new_game(economy__even_split_mode="split_it_somehow")

    def test_negative_display_decimals_are_refused_at_startup(self):
        with self.assertRaises(ConfigError):
            new_game(economy__profit_display_decimals=-1)

    def test_the_dice_expression_has_no_inline_default(self):
        data = copy.deepcopy(raw_config())
        del data["economy"]["profit_roll"]
        with self.assertRaises(MissingConfigKey):
            Economy(Config(data, source="config.json minus economy.profit_roll"))


class AccumulationTest(unittest.TestCase):
    """#20: "add it to that city's running cumulative total" -- per city, exactly."""

    def test_each_city_holds_exactly_what_it_was_awarded(self):
        game = play_out(new_game(founders=FOUR_FOUNDERS))
        expected = awards_by_city(game)
        for player in game.players.values():
            self.assertEqual(
                player.cumulative_profit,
                expected.get(player.city, Fraction(0)),
                "%s holds %s but was awarded %s"
                % (player.city, player.cumulative_profit, expected.get(player.city)),
            )
        self.assertGreater(len(expected), 1, "only one city ever earned anything")

    def test_nothing_is_created_or_lost_between_the_roll_and_the_ledger(self):
        for game in (
            play_out(new_game(founders=FOUR_FOUNDERS)),
            abandoned_game(founders=FOUR_FOUNDERS),
            silent_game(founders=FOUR_FOUNDERS),
        ):
            held = sum(p.cumulative_profit for p in game.players.values())
            awarded = sum(awards_by_city(game).values())
            self.assertEqual(held, awarded)

    def test_an_even_split_pays_out_the_whole_roll_and_no_more(self):
        game = abandoned_game(founders=FOUR_FOUNDERS)
        for need in game.needs.values():
            resolution = need.resolution
            paid = sum(exact(a["profit"]) for a in resolution["awards"])
            self.assertEqual(
                paid,
                Fraction(resolution["roll"]["total"]),
                "%s paid %s of a roll of %s" % (need.need_key, paid, resolution["roll"]),
            )

    def test_a_city_that_never_wins_holds_nothing(self):
        # p3 stays silent all game, so it can only ever be paid for its own
        # import needs -- and every one of those is picked by p3 for someone else.
        game = new_game()
        rounds = 0
        while game.phase == "running" and rounds < 40:
            for player_id in ("p1", "p2"):
                pick_first(game, player_id)
            everyone_exports(game, exclude=("p3",))
            advance(game)
            rounds += 1
        awarded = awards_by_city(game)
        self.assertNotIn("Hobart", awarded, "a silent city was paid for a win")
        # It still earns its own ramp-ups (#17), which is a different rule; what
        # matters here is that its total is exactly what it was awarded.
        self.assertEqual(
            game.player_for_city("Hobart").cumulative_profit,
            awarded.get("Hobart", Fraction(0)),
        )

    def test_repeated_wins_accumulate_rather_than_replace(self):
        game = new_game()
        economy = game.economy
        winner = game.players["p2"]
        before = winner.cumulative_profit
        economy.credit(winner, Fraction(7))
        economy.credit(winner, Fraction(5))
        self.assertEqual(winner.cumulative_profit, before + Fraction(12))

    def test_a_third_of_a_roll_three_times_is_exactly_the_roll(self):
        """Fractions, not floats: 0.1+0.2 arithmetic in a leaderboard is a bug
        the newspaper would faithfully print."""
        game = abandoned_game(founders=FOUR_FOUNDERS, economy__profit_roll="1d1")
        for need in game.needs.values():
            shares = [exact(a["profit"]) for a in need.resolution["awards"]]
            self.assertEqual(sum(shares), Fraction(1))
        held = sum(p.cumulative_profit for p in game.players.values())
        self.assertEqual(held.denominator, 1, "the ledger did not come out whole")

    def test_profit_is_never_credited_negative(self):
        game = new_game()
        with self.assertRaises(RuleViolation):
            game.economy.credit(game.players["p2"], Fraction(-1))

    def test_only_the_economy_moves_a_citys_total(self):
        """Structural, in the style of ``audit.find_extra_timers``.

        A second place that writes ``cumulative_profit`` is a second economy,
        and the per-city assertions above would keep passing while it drifted.
        """
        allowed = {"economy.py", "state.py"}
        writes = {}
        engine_dir = os.path.join(repo_root(), "engine")
        for filename in sorted(os.listdir(engine_dir)):
            if not filename.endswith(".py"):
                continue
            with open(os.path.join(engine_dir, filename), "r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if re.search(r"cumulative_profit\s*[-+*/]?=[^=]", line):
                        writes.setdefault(filename, []).append(lineno)
        self.assertEqual(
            set(writes) - allowed,
            set(),
            "cumulative_profit is written outside the economy: %r" % writes,
        )


class LeaderboardTest(unittest.TestCase):
    """#20/#22: the cumulative per-city board itself."""

    def test_it_ranks_every_city_richest_first(self):
        game = play_out(new_game(founders=FOUR_FOUNDERS))
        board = game.leaderboard()
        self.assertEqual({row["city"] for row in board}, {p.city for p in game.players.values()})
        self.assertEqual([row["rank"] for row in board], list(range(1, len(board) + 1)))
        values = [exact(row["profit"]) for row in board]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_a_row_reports_the_same_total_the_city_holds(self):
        game = play_out(new_game(founders=FOUR_FOUNDERS))
        for row in game.leaderboard():
            self.assertEqual(
                exact(row["profit"]), game.player_for_city(row["city"]).cumulative_profit
            )

    def test_a_city_that_scored_nothing_still_appears(self):
        game = new_game(founders=FOUR_FOUNDERS)
        board = game.leaderboard()
        self.assertEqual(len(board), 4)
        self.assertEqual({exact(row["profit"]) for row in board}, {Fraction(0)})

    def test_a_late_joiner_appears_from_the_round_they_join(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        game.register_player("p4", "@di", "Tromsø")
        self.assertIn("Tromsø", {row["city"] for row in game.leaderboard()})

    def test_ties_break_alphabetically_and_are_flagged(self):
        game = new_game(founders=FOUR_FOUNDERS)
        game.economy.credit(game.player_for_city("Hobart"), Fraction(9))
        game.economy.credit(game.player_for_city("Valparaíso"), Fraction(9))
        game.economy.credit(game.player_for_city("Tromsø"), Fraction(4))
        board = game.leaderboard()
        self.assertEqual([row["city"] for row in board[:2]], ["Hobart", "Valparaíso"])
        self.assertEqual([row["tied"] for row in board[:2]], [True, True])
        self.assertFalse(board[2]["tied"])

    def test_identity_is_city_and_mayor_only(self):
        game = play_out(new_game(founders=FOUR_FOUNDERS))
        handles = {p.handle for p in game.players.values()}
        for row in game.leaderboard():
            self.assertEqual(row["mayor"], "the Mayor of %s" % row["city"])
            self.assertEqual(set(row) & {"handle", "player_id", "name"}, set())
            self.assertEqual(handles & set(str(v) for v in row.values()), set())

    def test_display_never_carries_binary_float_noise(self):
        game = abandoned_game(founders=FOUR_FOUNDERS, economy__profit_roll="1d1")
        for row in game.leaderboard():
            self.assertNotIn("999", row["profit"]["display"])
            self.assertLessEqual(
                len(row["profit"]["display"].partition(".")[2]),
                game.economy.decimals,
            )

    def test_the_display_precision_comes_from_config(self):
        for decimals, expected in ((2, "0.33"), (4, "0.3333"), (0, "0")):
            game = new_game(economy__profit_display_decimals=decimals)
            game.economy.credit(game.player_for_city("Hobart"), Fraction(1, 3))
            row, = [r for r in game.leaderboard() if r["city"] == "Hobart"]
            self.assertEqual(row["profit"]["display"], expected)
            # However it is displayed, the stored value is still exact.
            self.assertEqual(exact(row["profit"]), Fraction(1, 3))


class LeaderboardVisibilityTest(unittest.TestCase):
    """#22: what the newspaper shows is config's decision, in one place."""

    def test_the_newspaper_prints_the_board_when_config_says_so(self):
        game = play_out(new_game(economy__leaderboard_visible_in_newspaper=True))
        archive = views.archive(game)
        self.assertTrue(archive["editions"])
        for edition in archive["editions"]:
            self.assertIn("leaderboard", edition)
        self.assertIsNotNone(views.newspaper_leaderboard(game))

    def test_no_edition_carries_the_board_when_config_says_not_to(self):
        game = play_out(new_game(economy__leaderboard_visible_in_newspaper=False))
        archive = views.archive(game)
        self.assertTrue(archive["editions"])
        for edition in archive["editions"]:
            self.assertNotIn("leaderboard", edition)
        self.assertIsNone(views.newspaper_leaderboard(game))
        audit.assert_exposure_policy(game, archive)

    def test_a_hidden_board_that_slips_into_a_payload_is_caught(self):
        game = play_out(new_game(economy__leaderboard_visible_in_newspaper=False))
        leaky = views.archive(game)
        leaky["editions"][0]["leaderboard"] = game.leaderboard()
        self.assertTrue(audit.find_exposure_violations(game, leaky))
        with self.assertRaises(ExposurePolicyViolation):
            audit.assert_exposure_policy(game, leaky)

    def test_a_visible_board_is_not_flagged(self):
        game = play_out(new_game(economy__leaderboard_visible_in_newspaper=True))
        self.assertEqual(audit.find_exposure_violations(game, views.archive(game)), [])
        audit.assert_exposure_policy(game, views.archive(game))

    def test_the_facilitators_own_view_is_complete_either_way_and_says_so(self):
        for visible in (True, False):
            game = play_out(new_game(economy__leaderboard_visible_in_newspaper=visible))
            standings = views.standings(game)
            self.assertEqual(standings["audience"], "facilitator")
            self.assertEqual(standings["newspaper_visible"], visible)
            self.assertEqual(len(standings["leaderboard"]), len(game.players))
            self.assertEqual(
                exact(standings["total_profit_awarded"]),
                sum(p.cumulative_profit for p in game.players.values()),
            )

    def test_the_visibility_flag_has_no_inline_default(self):
        data = copy.deepcopy(raw_config())
        del data["economy"]["leaderboard_visible_in_newspaper"]
        config = Config(data, source="config.json minus the visibility flag")
        with self.assertRaises(MissingConfigKey):
            Economy(config)

    def test_the_engine_reads_the_flag_from_config_rather_than_assuming_it(self):
        config = make_config()
        GameEngine(config=config, content=Content.load(config))
        self.assertIn("economy.leaderboard_visible_in_newspaper", config.keys_read())

    def test_hiding_the_board_does_not_also_hide_the_round_from_the_paper(self):
        """A withheld leaderboard is an exposure decision, not a mute button."""
        game = play_out(new_game(economy__leaderboard_visible_in_newspaper=False))
        edition = views.round_briefing(game, 3)
        self.assertIsNotNone(edition["resolved"])
        self.assertIn("profit_awarded", edition["resolved"])


class NonWinnerOriginIsNotAKnobTest(unittest.TestCase):
    """#21: a losing export's origin is off, and there is nothing to turn on.

    Spec #22 makes exposure policy configurable in general; #21 is the carve-out.
    "Off by default" would satisfy neither -- a default is a thing that can be
    changed in config.json by someone who never reads spec #21.
    """

    def test_the_constant_is_off_and_is_a_constant(self):
        self.assertIs(NON_WINNER_ORIGIN_EXPOSURE, False)
        self.assertNotIn(
            "economy.non_winner_origin_exposure", CONFIGURABLE_EXPOSURE_KEYS
        )
        self.assertEqual(
            CONFIGURABLE_EXPOSURE_KEYS, ("economy.leaderboard_visible_in_newspaper",)
        )

    def test_config_json_contains_no_knob_over_exporter_anonymity(self):
        self.assertEqual(audit.find_origin_exposure_knobs(raw_config()), [])

    def test_the_knob_detector_actually_detects_one(self):
        for knob in (
            {"economy": {"reveal_origin_of_losing_exports": True}},
            {"newspaper": {"show_exporter_for_all_submissions": False}},
            {"privacy": {"blind_voting_enabled": True}},
            {"nested": {"deeper": {"non_winner_origin_policy": "expose"}}},
        ):
            self.assertTrue(
                audit.find_origin_exposure_knobs(knob),
                "%r was not flagged as an exposure knob" % knob,
            )

    def test_the_detector_does_not_flag_the_legitimate_privacy_settings(self):
        """#28's ``player_identity_style`` is a real, configurable exposure
        setting. A detector that flagged it would be turned off within a week."""
        for legitimate in (
            "player_identity_style",
            "leaderboard_visible_in_newspaper",
            "answers_shared_in_newspaper",
            "allow_pointed_humor",
            "importer_may_export_to_own_need",
            "crown_cumulative_profit_winner",
        ):
            self.assertEqual(
                exposure_knob_match(legitimate), [], "%r was flagged" % legitimate
            )

    def test_a_knob_at_any_nesting_depth_is_found(self):
        deep = {"a": {"b": {"c": [{"reveal_exporter_city": True}]}}}
        offenders = audit.find_origin_exposure_knobs(deep)
        self.assertEqual(len(offenders), 1)
        self.assertIn("reveal_exporter_city", offenders[0]["path"])

    def test_the_economy_exposes_no_attribute_that_would_unblind_a_loser(self):
        economy = Economy(make_config())
        for name in dir(economy):
            self.assertEqual(
                exposure_knob_match(name), [], "Economy.%s looks like a knob" % name
            )

    def test_inventing_the_knob_in_config_changes_nothing(self):
        """The real test: fabricate the key config.json does not have, set it to
        the most permissive value, play a whole game, and read the paper."""
        config = config_with(
            economy__reveal_non_winning_origins=True,
            economy__expose_exporter_identity=True,
            newspaper__show_origin_for_all_submissions=True,
        )
        game = play_out(new_game(config=config))
        archive = views.archive(game)
        audit.assert_blind(game, archive)

        losers = 0
        for edition in archive["editions"]:
            for section in ("opened", "resolved"):
                need = edition.get(section)
                if not need:
                    continue
                for line in need.get("submissions", []):
                    if line["won"]:
                        continue
                    losers += 1
                    self.assertNotIn("origin_city", line)
                    self.assertEqual(line["origin"], ORIGIN_WITHHELD)
        self.assertGreater(losers, 0, "this game had no losing exports to withhold")

    def test_the_fabricated_knob_is_still_reported_as_a_knob(self):
        """Changing nothing is only half of it -- the audit must object to the
        key existing at all, so it never survives a review by looking harmless."""
        offenders = audit.find_origin_exposure_knobs(
            config_with(economy__reveal_non_winning_origins=True)._data
        )
        self.assertTrue(offenders)
        self.assertEqual(offenders[0]["spec"], "#21")

    def test_a_visible_leaderboard_does_not_unblind_anyone(self):
        """The two exposure decisions are independent: #22's knob being on must
        not be a back door to #21's origins via a city named in a board row."""
        game = play_out(new_game(economy__leaderboard_visible_in_newspaper=True))
        archive = views.archive(game)
        self.assertIn("leaderboard", archive["editions"][0])
        audit.assert_blind(game, archive)
        audit.assert_exposure_policy(game, archive)

    def test_no_losing_origin_leaks_under_any_economy_configuration(self):
        permutations = [
            {"economy__leaderboard_visible_in_newspaper": True},
            {"economy__leaderboard_visible_in_newspaper": False},
            {"economy__even_split_mode": "floor_discard_remainder"},
            {"economy__profit_roll": "5d10"},
            {"economy__profit_display_decimals": 0},
            {"exports__max_submissions_per_player_per_import_per_round": 2},
        ]
        for overrides in permutations:
            for build in (
                lambda **kw: play_out(new_game(**kw)),
                abandoned_game,
                silent_game,
            ):
                game = build(founders=FOUR_FOUNDERS, **overrides)
                audit.assert_blind(game, views.archive(game))
                self.assertEqual(audit.find_ledger_misuse(game), [], repr(overrides))

    def test_the_ledger_never_reveals_a_loser_even_on_the_even_split_path(self):
        # Every submission wins an even split (#19), so this path legitimately
        # names every submitting city -- and must name no others.
        game = abandoned_game(founders=FOUR_FOUNDERS)
        for need in game.needs.values():
            named = {a["city"] for a in need.resolution["awards"]}
            losers = [s for s in game.submissions_for(need.need_key) if not s.is_winner]
            self.assertEqual(losers, [])
            self.assertLessEqual(len(named), len(game.players))
        audit.assert_blind(game, views.archive(game))


if __name__ == "__main__":
    unittest.main()
