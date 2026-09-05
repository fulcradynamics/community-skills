"""Spec #14: a category may repeat across cities, never for the same city."""

import unittest

from harness import (
    file_orders, make_config, new_game, play_out, question_doc, trade_policy,
)
from engine import Content, GameEngine
from engine.clock import utc
from engine.errors import NoEligibleImportNeed


def tiny_content(category_count, needs_per_category, questions=6):
    """A deliberately small pool, so the repetition rule can be forced to bite."""
    categories = [
        {"id": "c%d" % index, "label": "C%d" % index, "blurb": "-"}
        for index in range(category_count)
    ]
    needs = []
    for category in categories:
        for slot in range(needs_per_category):
            needs.append(
                {
                    "id": "%s-%02d" % (category["id"], slot),
                    "category": category["id"],
                    # Orders, not questions: every need in every pool obeys spec
                    # #13a, fixtures included (engine.trade checks them at load).
                    "trade_family": "wear_and_comfort",
                    "title": "need %s %d" % (category["id"], slot),
                    "need_brief": "{city} is buying six crates of %s." % category["id"],
                    "exporter_prompt": "Ship {city} six crates of something.",
                    "source": "seed",
                }
            )
    doc = question_doc(
        [
            {"id": "q%d" % index, "text": "Mayor, question %d?" % index}
            for index in range(questions)
        ]
    )
    return Content(
        needs, categories, doc["questions"], {"cities": []}, root=".", question_doc=doc,
        trade_policy=trade_policy(),
    )


def game_with(content, config=None, **overrides):
    config = config if config is not None else make_config(**overrides)
    game = GameEngine.for_test(utc(2026, 9, 1, 12), rng_seed=3, config=config, content=content)
    game.register_player("p1", "@ada", "Reykjavík", is_facilitator=True)
    game.register_player("p2", "@bo", "Valparaíso")
    game.register_player("p3", "@cy", "Hobart")
    file_orders(game)
    game.start()
    return game


class SeededPoolTest(unittest.TestCase):
    def test_no_city_receives_the_same_category_twice(self):
        game = play_out(new_game())
        by_city = {}
        for need in game.needs.values():
            by_city.setdefault(need.importing_city, []).append(need.category)
        self.assertTrue(by_city)
        for city, categories in by_city.items():
            self.assertEqual(
                len(categories), len(set(categories)), "%s got a repeat category" % city
            )

    def test_no_individual_need_is_replayed_within_a_game(self):
        game = play_out(new_game())
        used = [need.content_need_id for need in game.needs.values()]
        self.assertEqual(len(used), len(set(used)))

    def test_needs_are_drawn_from_the_seeded_content_file(self):
        game = play_out(new_game())
        seeded = {need["id"] for need in game.content.needs}
        for need in game.needs.values():
            self.assertIn(need.content_need_id, seeded)

    def test_the_brief_is_rendered_for_the_importing_city(self):
        game = new_game()
        need = game.collecting_need()
        self.assertNotIn("{city}", need.rendered["need_brief"])
        self.assertNotIn("{city}", need.rendered["exporter_prompt"])
        self.assertIn(need.importing_city, need.rendered["need_brief"])


class CrossCityRepetitionTest(unittest.TestCase):
    def test_a_category_may_repeat_across_different_cities(self):
        # Two categories, three cities, two rotations: every city must draw both
        # categories, so cross-city repetition is not merely permitted but forced.
        game = game_with(tiny_content(category_count=2, needs_per_category=6))
        play_out(game)
        self.assertEqual(len(game.needs), 6)
        counts = {}
        for need in game.needs.values():
            counts[need.category] = counts.get(need.category, 0) + 1
        self.assertEqual(sorted(counts.values()), [3, 3])

    def test_config_can_forbid_cross_city_repetition_too(self):
        game = game_with(
            tiny_content(category_count=8, needs_per_category=2),
            imports__allow_repeat_category_across_cities=False,
        )
        play_out(game)
        categories = [need.category for need in game.needs.values()]
        self.assertEqual(len(categories), len(set(categories)))

    def test_config_can_allow_a_city_to_repeat_a_category(self):
        content = tiny_content(category_count=1, needs_per_category=6)
        game = game_with(content, imports__allow_repeat_category_for_same_city=True)
        play_out(game)
        self.assertEqual(len(game.needs), 6)
        self.assertEqual({need.category for need in game.needs.values()}, {"c0"})

    def test_an_impossible_order_raises_instead_of_repeating_silently(self):
        # One category, three needs, three cities, two rotations. Every city can
        # order once; nobody can order twice without breaking the rule, and
        # since spec #13 that impossibility surfaces where the mayor is being
        # offered a slate rather than three rounds later where a draw would have
        # happened -- which is the better place for it to surface.
        content = tiny_content(category_count=1, needs_per_category=3)
        config = make_config()
        game = GameEngine.for_test(
            utc(2026, 9, 1, 12), rng_seed=3, config=config, content=content
        )
        for player_id, handle, city in (
            ("p1", "@ada", "Reykjavík"), ("p2", "@bo", "Valparaíso"), ("p3", "@cy", "Hobart"),
        ):
            game.register_player(player_id, handle, city, is_facilitator=player_id == "p1")
        for player_id in ("p1", "p2", "p3"):
            offer = game.import_choice_offer(player_id)
            game.choose_import(player_id, need_id=offer["suggestions"][0]["need_id"])
        for player_id in ("p1", "p2", "p3"):
            self.assertEqual(game.unfiled_import_turns(player_id), 1)
            with self.assertRaises(NoEligibleImportNeed):
                game.import_choice_offer(player_id)

    def test_need_reuse_can_be_enabled_by_config(self):
        content = tiny_content(category_count=1, needs_per_category=1)
        game = game_with(
            content,
            imports__allow_repeat_category_for_same_city=True,
            imports__reuse_same_need_within_game=True,
        )
        play_out(game)
        self.assertEqual(
            {need.content_need_id for need in game.needs.values()}, {"c0-00"}
        )


class EligibilityUnitTest(unittest.TestCase):
    """The draw rule on its own, without a game around it."""

    def setUp(self):
        self.content = tiny_content(category_count=3, needs_per_category=2)

    def _eligible(self, **overrides):
        rules = {
            "used_need_ids": set(),
            "categories_used_by_city": set(),
            "categories_used_anywhere": set(),
            "allow_repeat_for_same_city": False,
            "allow_repeat_across_cities": True,
            "allow_need_reuse": False,
        }
        rules.update(overrides)
        return {need["id"] for need in self.content.eligible_needs(**rules)}

    def test_everything_is_eligible_for_a_city_with_no_history(self):
        self.assertEqual(len(self._eligible()), 6)

    def test_a_category_the_city_already_imported_is_excluded(self):
        eligible = self._eligible(categories_used_by_city={"c0"})
        self.assertEqual(eligible, {"c1-00", "c1-01", "c2-00", "c2-01"})

    def test_a_category_another_city_imported_is_still_eligible(self):
        self.assertEqual(len(self._eligible(categories_used_anywhere={"c0"})), 6)

    def test_forbidding_cross_city_repeats_excludes_it_everywhere(self):
        eligible = self._eligible(
            categories_used_anywhere={"c0"}, allow_repeat_across_cities=False
        )
        self.assertEqual(len(eligible), 4)

    def test_an_already_used_need_is_excluded_unless_reuse_is_allowed(self):
        self.assertNotIn("c0-00", self._eligible(used_need_ids={"c0-00"}))
        self.assertIn(
            "c0-00", self._eligible(used_need_ids={"c0-00"}, allow_need_reuse=True)
        )


class PlayerSuggestedNeedTest(unittest.TestCase):
    def test_a_player_can_add_a_need_to_the_pool(self):
        game = new_game()
        before = len(game.content.needs)
        added = game.suggest_import_need(
            "p2",
            {
                "id": "need-player-01",
                "category": "small_comforts",
                "trade_family": "wear_and_comfort",
                "title": "Four hundred metres of ribbon",
                "need_brief": "{city} wraps a great many presents and has run out of "
                              "ribbon in every colour but brown.",
                "exporter_prompt": "Ship {city} the ribbon, the scissors or both.",
            },
        )
        self.assertEqual(added["source"], "player")
        self.assertEqual(len(game.content.needs), before + 1)

    def test_a_player_suggestion_that_asks_for_advice_is_refused(self):
        """Spec #13a holds at every door into the pool, this one included."""
        from engine.errors import TradeRefused

        game = new_game()
        with self.assertRaises(TradeRefused):
            game.suggest_import_need(
                "p2",
                {
                    "id": "need-player-02",
                    "category": "small_comforts",
                    "trade_family": "reading_and_listening",
                    "title": "A better way to wrap a present",
                    "need_brief": "{city} has a ribbon problem.",
                    "exporter_prompt": "What should {city} do about the ribbon?",
                },
            )

    def test_player_suggestions_can_be_switched_off(self):
        from engine.errors import RuleViolation

        game = new_game(content__allow_player_suggested_import_needs=False)
        with self.assertRaises(RuleViolation):
            game.suggest_import_need("p2", {"id": "x", "category": "small_comforts",
                                            "trade_family": "wear_and_comfort",
                                            "need_brief": "{city} is buying blankets.",
                                            "exporter_prompt": "Ship {city} blankets."})


if __name__ == "__main__":
    unittest.main()
