"""config.json is the single source for every configurable parameter.

Read-tracking shows the engine *consults* config; the override tests show it
*obeys* it; the deletion tests show there is no inline default hiding behind it.
All three are needed -- an engine that reads a key and then ignores the value
would pass the first alone.
"""

import copy
import json
import os
import unittest

from harness import (
    FOUNDERS, advance, everyone_exports, make_config, new_game, play_out,
)
from engine import Config, Content
from engine.config import repo_root
from engine.errors import MissingConfigKey

#: Parameters this milestone's engine must take from config.json rather than
#: from a literal in the code. Every one is asserted read during a full game.
EXPECTED_READS = {
    "players.min_players",
    "players.max_players",
    "cities.enforce_unique_city_names",
    # The join path (spec #2): suggesting cities, and resolving a duplicate pick
    # to a geographically close alternative. Exercised below by a join that
    # collides, because a key only read on the collision path is exactly the kind
    # that drifts back into a literal without anybody noticing.
    "cities.duplicate_pick_resolution",
    "cities.suggestions_offered_on_join",
    "cities.max_reassignment_search_radius_km",
    "cities.allow_off_gazetteer_picks",
    "content.import_needs_file",
    "content.gazetteer_file",
    "content.questions_file",
    "content.question_set_id",
    "rounds.round_window_hours",
    "rounds.rotations_target",
    "imports.allow_repeat_category_across_cities",
    "imports.allow_repeat_category_for_same_city",
    "imports.reuse_same_need_within_game",
    # Spec #13's parameters: how big a slate a mayor is offered, how early the
    # check-in starts asking for the order, and how long a turn nobody has
    # ordered for is held before it is given up.
    "imports.suggestions_offered_to_importer",
    "imports.choice_offered_rounds_ahead",
    "imports.unchosen_turn_grace_rounds",
    "exports.max_submissions_per_player_per_import_per_round",
    "exports.importer_may_export_to_own_need",
    "economy.profit_roll",
    "economy.profit_display_decimals",
    "economy.even_split_mode",
    "economy.leaderboard_visible_in_newspaper",
    "facilitator_questions.enabled",
    "facilitator_questions.ask_every_n_rounds",
    "facilitator_questions.max_per_player_per_round",
    "facilitator_questions.fill_second_slot_only_if_no_second_game_action_pending",
    "facilitator_questions.scope",
    "facilitator_questions.framing",
    "facilitator_questions.answers_shared_in_newspaper",
    "facilitator_questions.aggregate_phrasing_ladder",
}

#: Parameters the *newspaper* takes from config.json rather than from a literal.
#: A separate set from :data:`EXPECTED_READS` because it is a separate consumer:
#: the engine never reads these, and the paper reads them all in the course of
#: publishing one game.
NEWSPAPER_READS = {
    "content.newspaper_file",
    "newspaper.masthead_id",
    "newspaper.publish_cadence",
    "newspaper.archive_prior_editions",
    "newspaper.player_identity_style",
    "newspaper.image_per_edition",
    "newspaper.prose.renderer",
    "newspaper.prose.asides_per_edition",
    "newspaper.prose.max_quoted_answers_per_item",
    "newspaper.prose.max_declined_exports_printed",
    "newspaper.image.modality_preference",
    "newspaper.image.raster_providers",
    "newspaper.image.width",
    "newspaper.image.height",
    "newspaper.output.editions_dir",
    "newspaper.output.formats",
    "newspaper.tone.funny",
    "newspaper.tone.colorful",
    "newspaper.tone.allow_pointed_humor",
    "newspaper.tone.disallow_snide_or_mean",
    # Whose prose that register grades (spec #30b). The paper implements one
    # value and refuses any other, which is a read either way.
    "newspaper.tone.forbidden_register_scope",
    "facilitator_questions.aggregate_phrasing_style",
    # The last edition's own switches (spec #31, #32). They belong in this set
    # rather than a fourth one because the endgame is written by the same
    # newspaper package and resolved on the same Paper: publishing one finished
    # game reads every one of them.
    "endgame.crown_cumulative_profit_winner",
    "endgame.publish_twist_article",
    "endgame.generate_per_city_description_and_image",
    "endgame.per_city_excess_uses_non_chosen_exports",
    "endgame.twist_article_items",
    "endgame.max_excess_offers_printed_per_city",
    "endgame.quote_mayor_answers_per_city",
    "endgame.city_image.width",
    "endgame.city_image.height",
    "endgame.write_private_excess_dossiers",
}

#: Parameters *hosting* takes from config.json. A third consumer and a third set,
#: for the same reason the newspaper has its own: the paper does not read these
#: and the site reads nothing else.
HOSTING_READS = {
    "hosting.enabled",
    "hosting.scheme",
    "hosting.base_domain",
    "hosting.site_id_file",
    "hosting.site_id_env_var",
    "hosting.site_id_bytes",
    "hosting.site_dir",
    "hosting.public_subdir",
    "hosting.archive_order",
    "hosting.publish",
    "hosting.publishers",
    "hosting.local_bind_host",
    "hosting.local_bind_port",
    "hosting.privacy.robots_txt",
    "hosting.privacy.meta_robots",
    "hosting.privacy.x_robots_tag",
    "hosting.privacy.referrer_policy",
    "hosting.privacy.cache_control",
    "hosting.privacy.content_security_policy",
}

#: Parameters the *facilitator's desk* takes from config.json -- the fourth
#: consumer, and a fourth set for the same reason the paper and the site have
#: their own: nothing else reads these, and running one completed-round
#: transaction reads all of them (spec #26).
FACILITATOR_READS = {
    "facilitator.completed_round_transaction",
    "facilitator.editions_label",
    "facilitator.notice.channel",
    "facilitator.notice.include_url",
}

#: Parameters that belong to a later milestone's surface, listed so their absence
#: from :data:`EXPECTED_READS` and :data:`NEWSPAPER_READS` reads as a milestone
#: boundary rather than as an oversight.
#:
#: Empty as of M7: the four endgame flags that used to live here are read now
#: and have moved to :data:`NEWSPAPER_READS`, which is exactly the transition
#: :meth:`ReadTrackingTest.test_the_deferred_parameters_really_are_still_deferred`
#: exists to force. The set stays, rather than being deleted with its test, so
#: that a parameter added ahead of the milestone that uses it has somewhere
#: honest to sit.
NOT_YET_READ = set()


def raw_config():
    with open(os.path.join(repo_root(), "config.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def config_without(dotted):
    data = copy.deepcopy(raw_config())
    path = dotted.split(".")
    node = data
    for part in path[:-1]:
        node = node[part]
    del node[path[-1]]
    return Config(data, source="config.json minus %s" % dotted)


class ReadTrackingTest(unittest.TestCase):
    def test_the_engine_reads_every_parameter_it_should_from_config(self):
        from engine import views

        config = make_config()
        # One cooperative game, for the winner-pick path and the check-in slots.
        game = new_game(config=config, start=False)
        game.city_suggestions()
        # ...including a mayor who asks for a city somebody already holds, so the
        # reassignment rules are read rather than merely present.
        game.join("p9", "@zed", FOUNDERS[0][2])
        game.start()
        for player_id in sorted(game.players):
            game.checkin(player_id)
        play_out(game)
        views.archive(game)
        # One join whose every listed neighbour is also taken, which is the only
        # path that consults the search radius.
        crowded = new_game(
            founders=[
                ("p2", "@b", "Philadelphia"), ("p3", "@c", "Camden"),
                ("p4", "@d", "Wilmington"), ("p5", "@e", "Trenton"),
                ("p6", "@f", "Allentown"),
            ],
            config=config, start=False,
        )
        crowded.join("p7", "@g", "Philadelphia")
        # One abandoned game, so the even-split fallback's config is read too.
        lapsed = new_game(config=config)
        while lapsed.phase == "running":
            everyone_exports(lapsed)
            advance(lapsed)

        missing = EXPECTED_READS - set(config.keys_read())
        self.assertEqual(missing, set(), "not read from config.json: %s" % sorted(missing))

    def test_the_deferred_parameters_really_are_still_deferred(self):
        """A key in NOT_YET_READ that the engine now reads belongs in EXPECTED_READS.

        Without this, the deferred list would quietly become a list of things
        nobody rechecks -- which is how a parameter ends up half-wired.
        """
        from engine import views

        config = make_config()
        game = new_game(config=config)
        for player_id in sorted(game.players):
            game.checkin(player_id)
        play_out(game)
        views.archive(game)
        overlap = NOT_YET_READ & set(config.keys_read())
        self.assertEqual(
            overlap, set(), "now read; move to EXPECTED_READS: %s" % sorted(overlap)
        )

    def test_the_newspaper_reads_every_parameter_it_should_from_config(self):
        import tempfile

        from newspaper.publish import publish_game
        from newspaper.sample import sample_game

        config = make_config()
        game = sample_game(config=config)
        with tempfile.TemporaryDirectory() as out:
            publish_game(game, label="conformance", out_dir=out)
        missing = NEWSPAPER_READS - set(config.keys_read())
        self.assertEqual(missing, set(), "not read from config.json: %s" % sorted(missing))

    def test_hosting_reads_every_parameter_it_should_from_config(self):
        import tempfile

        import hosting
        from hosting import identity as identity_module
        from newspaper.sample import sample_game

        config = make_config()
        game = sample_game(config=config)
        with tempfile.TemporaryDirectory() as out:
            # An empty environment and a temporary root, so the id is minted here
            # rather than read from the repository's -- which is what makes
            # hosting.site_id_bytes a key this run actually consults.
            address = identity_module.load_or_create(config, root=out, env={})
            hosting.build_site(game, out_dir=out, identity=address)
            httpd, _ = hosting.make_server(config, address, site_dir=out)
            httpd.server_close()
        missing = HOSTING_READS - set(config.keys_read())
        self.assertEqual(missing, set(), "not read from config.json: %s" % sorted(missing))

    def test_the_facilitators_desk_reads_every_parameter_it_should_from_config(self):
        import shutil
        import tempfile

        from facilitator import Facilitator

        config = make_config()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        game = new_game(config=config)
        Facilitator.attach(
            game,
            editions_dir=os.path.join(tmp, "editions"),
            site_dir=os.path.join(tmp, "site"),
            root=tmp,
        )
        # One round window is one completed round, which is one whole
        # transaction: render, publish, build, notify.
        everyone_exports(game)
        advance(game)
        missing = FACILITATOR_READS - set(config.keys_read())
        self.assertEqual(missing, set(), "not read from config.json: %s" % sorted(missing))

    def test_every_key_the_engine_reads_actually_exists_in_config_json(self):
        config = make_config()
        play_out(new_game(config=config))
        data = raw_config()
        for dotted in config.keys_read():
            node = data
            for part in dotted.split("."):
                self.assertIn(part, node, "engine read %r, absent from config.json" % dotted)
                node = node[part]

    def test_config_offers_no_way_to_supply_an_inline_default(self):
        # A `get(key, default)` API is how config values start drifting back
        # into code, so the class deliberately does not have one.
        self.assertFalse(hasattr(Config, "get"))
        self.assertFalse(hasattr(Config, "get_or_default"))


class NoInlineDefaultsTest(unittest.TestCase):
    """Deleting a key must break the engine, not fall back to a literal."""

    def _assert_needs(self, dotted, action):
        config = config_without(dotted)
        with self.assertRaises(MissingConfigKey, msg="%s has an inline default" % dotted):
            action(config)

    def test_round_window_has_no_inline_default(self):
        self._assert_needs("rounds.round_window_hours", lambda c: new_game(config=c))

    def test_rotations_target_has_no_inline_default(self):
        self._assert_needs("rounds.rotations_target", lambda c: new_game(config=c))

    def test_profit_roll_has_no_inline_default(self):
        self._assert_needs(
            "economy.profit_roll", lambda c: play_out(new_game(config=c))
        )

    def test_submission_cap_has_no_inline_default(self):
        def act(config):
            game = new_game(config=config)
            game.submit_export("p2", "something")

        self._assert_needs("exports.max_submissions_per_player_per_import_per_round", act)

    def test_repetition_rule_has_no_inline_default(self):
        self._assert_needs(
            "imports.allow_repeat_category_for_same_city", lambda c: new_game(config=c)
        )

    def test_player_limits_have_no_inline_default(self):
        self._assert_needs("players.max_players", lambda c: new_game(config=c))
        self._assert_needs("players.min_players", lambda c: new_game(config=c))

    def test_question_cadence_has_no_inline_default(self):
        self._assert_needs(
            "facilitator_questions.ask_every_n_rounds", lambda c: new_game(config=c)
        )

    def test_the_answer_exposure_policy_has_no_inline_default(self):
        from engine import views

        def act(config):
            views.round_briefing(new_game(config=config), 1)

        self._assert_needs("facilitator_questions.answers_shared_in_newspaper", act)

    def test_the_phrasing_ladder_choice_has_no_inline_default(self):
        self._assert_needs(
            "facilitator_questions.aggregate_phrasing_ladder", lambda c: new_game(config=c)
        )

    def test_content_paths_have_no_inline_default(self):
        self._assert_needs("content.import_needs_file", lambda c: Content.load(c))

    def test_the_address_policy_has_no_inline_default(self):
        from hosting import identity as identity_module

        for dotted in ("hosting.scheme", "hosting.base_domain", "hosting.site_id_file",
                       "hosting.site_id_env_var"):
            self._assert_needs(dotted, lambda c: identity_module.load_or_create(c, env={}))

    def test_the_endgame_policy_has_no_inline_default(self):
        """Deleting an endgame switch must refuse the game, not pick a default.

        Whether the last edition crowns anybody, and whether a portrait may
        describe unchosen offers at all, are decisions somebody takes (spec #31,
        #32). A missing key silently resolving to "yes, publish it" would be the
        paper making the more exposing choice on a facilitator's behalf.
        """
        from newspaper.endgame import EndgamePolicy

        for dotted in (
            "endgame.crown_cumulative_profit_winner",
            "endgame.publish_twist_article",
            "endgame.generate_per_city_description_and_image",
            "endgame.per_city_excess_uses_non_chosen_exports",
            "endgame.twist_article_items",
            "endgame.max_excess_offers_printed_per_city",
            "endgame.quote_mayor_answers_per_city",
            "endgame.city_image.width",
            "endgame.city_image.height",
            "endgame.write_private_excess_dossiers",
        ):
            self._assert_needs(dotted, EndgamePolicy)

    def test_the_privacy_policy_has_no_inline_default(self):
        """The delivery headers especially: a missing one must not quietly revert."""
        from hosting.build import resolve_privacy

        for field in ("robots_txt", "meta_robots", "x_robots_tag", "referrer_policy",
                      "cache_control", "content_security_policy"):
            self._assert_needs("hosting.privacy.%s" % field, resolve_privacy)

    def test_the_published_allowlist_has_no_inline_default(self):
        from hosting.manifest import resolve_categories

        self._assert_needs("hosting.publish", resolve_categories)

    def test_the_import_choice_parameters_have_no_inline_default(self):
        """Spec #13's knobs: a missing one must not resolve to a quiet guess.

        ``unchosen_turn_grace_rounds`` especially -- a default of zero would
        silently start giving away import turns, and a large default would stall
        a game on one absent mayor. Both are facilitator decisions.
        """
        def play(config):
            game = new_game(config=config)
            play_out(game)

        for dotted in ("imports.suggestions_offered_to_importer",
                       "imports.choice_offered_rounds_ahead",
                       "imports.unchosen_turn_grace_rounds"):
            self._assert_needs(dotted, play)

    def test_the_completed_round_transaction_has_no_inline_default(self):
        """Spec #26: what happens when a round ends is not guessed at."""
        from facilitator.transaction import resolve_steps

        self._assert_needs("facilitator.completed_round_transaction", resolve_steps)


class BehaviourFollowsConfigTest(unittest.TestCase):
    def test_the_round_window_sets_the_length_of_a_round(self):
        for hours in (1, 6, 24, 72):
            game = new_game(rounds__round_window_hours=hours)
            self.assertEqual(game.timer.window.total_seconds(), hours * 3600)
            game.clock.advance(game.timer.window)
            game.tick()
            self.assertEqual(game.current_round, 2)

    def test_a_fractional_round_window_is_honoured(self):
        game = new_game(rounds__round_window_hours=0.5)
        self.assertEqual(game.timer.window.total_seconds(), 1800)

    def test_questions_can_be_switched_off_entirely(self):
        game = new_game(facilitator_questions__enabled=False)
        self.assertIsNone(game.rounds[1].question_id)
        self.assertEqual(
            [s for s in game.checkin("p1")["slots"] if s], []
        )

    def test_question_cadence_is_configurable(self):
        game = new_game(facilitator_questions__ask_every_n_rounds=2)
        asked = {}
        while game.phase == "running":
            asked[game.current_round] = game.rounds[game.current_round].question_id
            everyone_exports(game)
            advance(game)
        self.assertIsNotNone(asked[1])
        self.assertIsNone(asked[2])
        self.assertIsNotNone(asked[3])
        self.assertIsNone(asked[4])

    def test_a_question_is_never_repeated_within_a_game(self):
        game = play_out(new_game())
        asked = [r.question_id for r in game.rounds.values() if r.question_id]
        self.assertEqual(len(asked), len(set(asked)))

    def test_suppressing_questions_for_a_mayor_leaves_the_round_question_asked(self):
        game = new_game(facilitator_questions__max_per_player_per_round=0)
        self.assertIsNotNone(game.rounds[1].question_id)
        self.assertEqual([s for s in game.checkin("p1")["slots"] if s], [])

    def test_more_than_one_question_per_mayor_per_round_is_refused_not_capped(self):
        from engine.errors import ConfigError

        game = new_game(facilitator_questions__max_per_player_per_round=2)
        with self.assertRaises(ConfigError):
            game.checkin("p1")

    def test_the_leaderboard_exposure_policy_comes_from_config(self):
        from engine import views

        shown = new_game(economy__leaderboard_visible_in_newspaper=True)
        hidden = new_game(economy__leaderboard_visible_in_newspaper=False)
        self.assertIn("leaderboard", views.round_briefing(shown, 1))
        self.assertNotIn("leaderboard", views.round_briefing(hidden, 1))

    def test_the_rng_seed_comes_from_config_when_not_overridden(self):
        from engine import GameEngine

        config = make_config(engine__rng_seed=99)
        game = GameEngine(config=config, content=Content.load(config))
        self.assertIn("engine.rng_seed", config.keys_read())
        self.assertEqual(game._seed, 99)

    def test_a_null_seed_means_a_genuinely_random_game(self):
        from engine import GameEngine

        config = make_config(engine__rng_seed=None)
        game = GameEngine(config=config, content=Content.load(config))
        self.assertIsNone(game._seed)


if __name__ == "__main__":
    unittest.main()
