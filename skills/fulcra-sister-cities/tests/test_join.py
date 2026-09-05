"""Seating a mayor, and what happens when two of them want the same city (#2).

Spec #2's deterministic criterion is that a duplicate pick is "reassigned to a
geographically close alternative, never silently allowed to collide". Both
halves are checked here: that the collision resolves, and that the resolution is
announced. The whole-game version of this lives in
``tests/test_full_spec_integration.py``; this is the unit-level one, where the
awkward branches -- an exhausted neighbour list, an off-gazetteer pick, a
region with nothing left in it -- can be set up on purpose rather than waited
for.

The split between :meth:`GameEngine.register_player` and :func:`engine.join
.join_player` is deliberate and is tested as such: the low-level seat refuses a
collision and must never quietly move a mayor, and the joining door resolves it
and must never simply tell a player "no".
"""

import unittest

import harness  # noqa: F401  (path setup)
from engine.content import normalize_city
from engine.errors import ContentError, DuplicateCity
from engine.join import VIA_NEARBY_LIST, VIA_NEAREST_IN_REGION, CityRepickRequired
from harness import make_config, new_game

#: A city whose four listed neighbours can all be claimed in one small game,
#: which is what makes the "every neighbour is taken" branch reachable.
CROWDED = "Philadelphia"
CROWDED_NEARBY = ["Camden", "Wilmington", "Trenton", "Allentown"]


def game_with(cities, config=None):
    """A game seated on ``cities`` (the facilitator takes the first)."""
    founders = [
        ("p%d" % (index + 2), "@m%d" % index, city)
        for index, city in enumerate(cities)
    ]
    return new_game(founders=founders, config=config, start=False)


class DuplicatePickTest(unittest.TestCase):
    def test_the_first_claimant_keeps_the_city_and_the_later_pick_moves(self):
        game = game_with(["Valparaíso"])
        result = game.join("p9", "@zed", "Valparaíso")
        self.assertTrue(result["reassigned"])
        self.assertEqual(result["requested"], "Valparaíso")
        self.assertNotEqual(result["city"], "Valparaíso")
        # The mayor who was already there is undisturbed.
        self.assertEqual(game.players["p2"].city, "Valparaíso")

    def test_the_replacement_is_the_first_unclaimed_neighbour(self):
        game = game_with([CROWDED])
        result = game.join("p9", "@zed", CROWDED)
        self.assertEqual(result["city"], CROWDED_NEARBY[0])
        self.assertEqual(result["reassignment"]["via"], VIA_NEARBY_LIST)

    def test_a_taken_neighbour_is_skipped_rather_than_collided_with(self):
        game = game_with([CROWDED, CROWDED_NEARBY[0], CROWDED_NEARBY[1]])
        result = game.join("p9", "@zed", CROWDED)
        self.assertEqual(result["city"], CROWDED_NEARBY[2])

    def test_an_exhausted_neighbour_list_falls_back_to_the_nearest_in_region(self):
        game = game_with([CROWDED] + CROWDED_NEARBY)
        result = game.join("p9", "@zed", CROWDED)
        self.assertEqual(result["reassignment"]["via"], VIA_NEAREST_IN_REGION)
        self.assertNotIn(result["city"], CROWDED_NEARBY + [CROWDED])
        # It is a real distance, and it is inside the configured radius.
        radius = game.config.require_number("cities.max_reassignment_search_radius_km")
        self.assertIsNotNone(result["reassignment"]["distance_km"])
        self.assertLessEqual(result["reassignment"]["distance_km"], radius)

    def test_a_radius_of_zero_asks_for_a_re_pick_rather_than_reaching_further(self):
        """The radius is honoured, not treated as advice."""
        config = make_config(cities__max_reassignment_search_radius_km=0)
        game = game_with([CROWDED] + CROWDED_NEARBY, config=config)
        with self.assertRaises(CityRepickRequired) as caught:
            game.join("p9", "@zed", CROWDED)
        self.assertTrue(caught.exception.suggestions)

    def test_no_city_is_ever_held_twice_however_the_join_went(self):
        game = game_with([CROWDED, "Valparaíso"])
        for index, requested in enumerate([CROWDED, CROWDED, "Valparaíso"]):
            game.join("q%d" % index, "@q%d" % index, requested)
        keys = [normalize_city(player.city) for player in game.players.values()]
        self.assertEqual(len(keys), len(set(keys)))


class AnnouncementTest(unittest.TestCase):
    """"Reassignment is announced, never silent" -- the gazetteer's own rule."""

    def test_a_reassignment_says_what_happened_and_why(self):
        game = game_with([CROWDED])
        result = game.join("p9", "@zed", CROWDED)
        announcement = result["announcement"]
        self.assertIn(CROWDED, announcement)
        self.assertIn(result["city"], announcement)
        self.assertIn("already claimed", announcement)

    def test_an_ordinary_join_is_announced_too(self):
        game = game_with(["Valparaíso"])
        result = game.join("p9", "@zed", "Hobart")
        self.assertFalse(result["reassigned"])
        self.assertIn("Hobart", result["announcement"])

    def test_a_re_pick_request_carries_what_was_tried(self):
        config = make_config(cities__max_reassignment_search_radius_km=0)
        game = game_with([CROWDED] + CROWDED_NEARBY, config=config)
        with self.assertRaises(CityRepickRequired) as caught:
            game.join("p9", "@zed", CROWDED)
        self.assertEqual(caught.exception.tried, CROWDED_NEARBY)
        self.assertIn("re-pick", str(caught.exception.reason))


class OffGazetteerTest(unittest.TestCase):
    def test_a_city_the_gazetteer_has_never_heard_of_is_allowed(self):
        """Spec #2: the suggestions are suggestions; players pick freely."""
        game = game_with(["Valparaíso"])
        result = game.join("p9", "@zed", "Ankh-Morpork")
        self.assertEqual(result["city"], "Ankh-Morpork")
        self.assertFalse(result["reassigned"])

    def test_a_collision_on_an_unknown_city_asks_the_agent_rather_than_guessing(self):
        game = game_with(["Ankh-Morpork"])
        with self.assertRaises(CityRepickRequired) as caught:
            game.join("p9", "@zed", "Ankh-Morpork")
        self.assertIn("not in the gazetteer", caught.exception.reason)
        self.assertTrue(caught.exception.suggestions)

    def test_config_can_confine_a_game_to_the_gazetteer(self):
        config = make_config(cities__allow_off_gazetteer_picks=False)
        game = game_with(["Valparaíso"], config=config)
        with self.assertRaises(ContentError):
            game.join("p9", "@zed", "Ankh-Morpork")


class SuggestionsTest(unittest.TestCase):
    def test_it_offers_as_many_as_config_asks_for(self):
        game = game_with(["Valparaíso"])
        offer = game.city_suggestions()
        self.assertEqual(
            len(offer["cities"]),
            game.config.require_int("cities.suggestions_offered_on_join"),
        )

    def test_it_never_offers_a_city_somebody_already_holds(self):
        game = game_with(["Valparaíso", "Hobart", CROWDED])
        held = {normalize_city(p.city) for p in game.players.values()}
        offered = {normalize_city(name) for name in game.city_suggestions()["cities"]}
        self.assertEqual(held & offered, set())

    def test_the_offer_is_spread_across_regions_rather_than_taken_in_file_order(self):
        game = game_with([])
        names = game.city_suggestions()["cities"]
        regions = {game.content.gazetteer_entry(name)["region"] for name in names}
        self.assertGreater(len(regions), 1)

    def test_the_offer_says_it_is_not_a_menu(self):
        game = game_with([])
        self.assertIn("not a menu", game.city_suggestions()["note"])


class LowLevelSeatTest(unittest.TestCase):
    """``register_player`` must keep refusing; that is what makes join safe."""

    def test_it_raises_rather_than_moving_a_mayor_itself(self):
        game = game_with(["Valparaíso"])
        with self.assertRaises(DuplicateCity):
            game.register_player("p9", "@zed", "Valparaíso")
        self.assertNotIn("p9", game.players)

    def test_the_refusal_carries_the_candidates_the_joining_door_walks(self):
        game = game_with([CROWDED])
        with self.assertRaises(DuplicateCity) as caught:
            game.register_player("p9", "@zed", CROWDED)
        self.assertEqual(list(caught.exception.alternatives), CROWDED_NEARBY)
        self.assertEqual(caught.exception.held_by, "p2")


if __name__ == "__main__":
    unittest.main()
