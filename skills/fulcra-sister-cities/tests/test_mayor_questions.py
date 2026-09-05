"""Spec #23-#25: the two-slot check-in, the framing, and what the answers add up to.

Three groups, matching the three requirements:

* :class:`QuestionSelectionFollowsConfigTest` -- #23/#24's configurability. The
  cadence, the per-mayor cap and the gate are covered in
  ``test_checkin_slots.py`` and ``test_config_conformance.py``; here it is the
  scope, the framing and the ladder, i.e. the settings that say *which* question
  bank is legitimate at all.
* :class:`LadderArithmeticTest` and friends -- #25's data side. Every outcome the
  ladder in ``content/questions.json`` can select, selected from actual counts,
  plus the conditional wordings each outcome does and does not license.
* :class:`AggregateInTheGameTest` -- the same thing through the engine, with the
  identity and exposure rules that apply to it (#21, #25, #28).

The prose is not tested here because there is none: this milestone produces the
distribution and the set of wordings it licenses, and M5 writes the sentence.
"""

import copy
import json
import os
import unittest

from harness import (
    advance, everyone_exports, file_orders, make_config, new_game, play_out,
    question_doc,
)
from engine import Content, GameEngine, Ladder, aggregate, audit, views
from engine.aggregate import Predicate
from engine.clock import utc
from engine.errors import (
    ConfigError,
    ContentError,
    MissingConfigKey,
    RuleViolation,
)


def ladder(**overrides):
    config = make_config(**overrides)
    return Ladder.from_config(config, Content.load(config))


def a_question():
    config = make_config()
    return Content.load(config).question_by_id("q-coriander")


def distribution(*sizes):
    """Cities laid out in buckets of the given sizes.

    ``distribution(2, 1)`` is three mayors who answered, two of whom agreed.
    Returns ``(answers_by_city, buckets_by_city)``.
    """
    answers, buckets = {}, {}
    numbered = 0
    for index, size in enumerate(sizes):
        for _ in range(size):
            numbered += 1
            city = "City%02d" % numbered
            answers[city] = "answer number %d" % index
            buckets[city] = "bucket-%d" % index
    return answers, buckets


def report(*sizes, **kwargs):
    """The aggregate report for a distribution of the given bucket sizes."""
    answers, buckets = distribution(*sizes)
    if kwargs.pop("unclustered", False):
        buckets = None
    asked_of = kwargs.pop("asked_of", len(answers))
    assert not kwargs, "unexpected kwargs %r" % kwargs
    return aggregate.summarize(ladder(), 1, a_question(), answers, buckets, asked_of)


def phrase_licensed(outcome, phrase):
    for entry in outcome["conditional_phrases"]:
        if entry["phrase"] == phrase:
            return entry["licensed"]
    raise AssertionError(
        "outcome %r offers no conditional phrase %r" % (outcome["id"], phrase)
    )


# -- #23, #24: which questions are legitimate at all ------------------------

class QuestionSelectionFollowsConfigTest(unittest.TestCase):
    def test_the_configured_scope_must_match_the_bank(self):
        # Spec #24 keeps scope configurable for a later domain-specific run.
        # Pointing config at a bank of a different scope is a misconfiguration,
        # not a silent downgrade to whatever the file happens to contain.
        with self.assertRaises(ContentError) as caught:
            new_game(facilitator_questions__scope="coding_preferences")
        self.assertIn("scope", str(caught.exception))

    def test_the_scope_has_no_inline_default(self):
        config = _config_without("facilitator_questions.scope")
        with self.assertRaises(MissingConfigKey):
            Content.load(config)

    def test_an_unknown_framing_mode_is_refused_rather_than_waved_through(self):
        # A typo here would otherwise switch off the one requirement the key
        # exists to enforce, silently.
        with self.assertRaises(ConfigError):
            new_game(facilitator_questions__framing="questions_to_the_person")

    def test_the_framing_mode_is_enforced_over_the_whole_bank(self):
        doc = question_doc([{"id": "q1", "text": "Citizen, your name?",
                             "framing": "to_the_citizen"}])
        with self.assertRaises(ContentError) as caught:
            _game_with_questions(doc)
        self.assertIn("to_the_citizen", str(caught.exception))

    def test_a_question_with_no_framing_at_all_is_refused(self):
        doc = question_doc([{"id": "q1", "text": "And your name?"}])
        doc["questions"][0].pop("framing")
        with self.assertRaises(ContentError):
            _game_with_questions(doc)

    def test_every_shipped_question_is_framed_to_or_about_the_mayor(self):
        content = Content.load(make_config())
        self.assertTrue(content.questions)
        for question in content.questions:
            self.assertIn(question["framing"], ("to_the_mayor", "about_the_mayor"))

    def test_the_framing_mode_has_no_inline_default(self):
        config = _config_without("facilitator_questions.framing")
        with self.assertRaises(MissingConfigKey):
            Content.load(config)

    def test_the_ladder_is_the_one_config_names(self):
        game = new_game()
        self.assertEqual(game.phrasing_ladder.id, "default")

    def test_a_ladder_config_names_but_content_lacks_refuses_to_start_a_game(self):
        with self.assertRaises(ContentError) as caught:
            new_game(facilitator_questions__aggregate_phrasing_ladder="terse")
        self.assertIn("terse", str(caught.exception))

    def test_the_ladder_choice_has_no_inline_default(self):
        config = _config_without("facilitator_questions.aggregate_phrasing_ladder")
        with self.assertRaises(MissingConfigKey):
            new_game(config=config)

    def test_a_cadence_below_one_is_refused_rather_than_treated_as_off(self):
        # "Never ask" is `enabled: false`; 0 is a mistake, and reading it as
        # "off" would hide the mistake.
        with self.assertRaises(ConfigError):
            new_game(facilitator_questions__ask_every_n_rounds=0)

    def test_the_bank_running_dry_produces_silence_not_a_repeat(self):
        # A repeated question would pool two different rounds' answers into one
        # aggregate, which is the one thing #25's phrasing cannot survive.
        doc = question_doc(
            [{"id": "q1", "text": "Mayor, one question only?", "framing": "to_the_mayor"}]
        )
        game = _game_with_questions(doc)
        asked = []
        while game.phase == "running":
            asked.append(game.rounds[game.current_round].question_id)
            everyone_exports(game)
            advance(game)
        self.assertEqual(asked[0], "q1")
        self.assertEqual(set(asked[1:]), {None})

    def test_a_mayor_who_has_not_been_queued_yet_is_still_asked(self):
        # Spec #5 withholds an *import need* until a player's first export; it
        # does not withhold the getting-to-know-you question, and #23's check-in
        # belongs to every player.
        game = new_game()
        game.register_player("p4", "@di", "Tromsø")
        self.assertFalse(game.players["p4"].is_queued)
        kinds = [slot["kind"] for slot in game.checkin("p4")["slots"] if slot]
        self.assertIn("mayor_question", kinds)

    def test_a_suppressed_mayor_cannot_answer_even_though_the_round_asked(self):
        game = new_game(facilitator_questions__max_per_player_per_round=0)
        self.assertIsNotNone(game.rounds[1].question_id)
        with self.assertRaises(RuleViolation):
            game.answer_question("p2", "nobody offered me a slot")


def _config_without(dotted):
    from engine.config import repo_root

    with open(os.path.join(repo_root(), "config.json"), "r", encoding="utf-8") as fh:
        data = json.load(fh)
    path = dotted.split(".")
    node = data
    for part in path[:-1]:
        node = node[part]
    del node[path[-1]]
    from engine import Config

    return Config(data, source="config.json minus %s" % dotted)


def _game_with_questions(doc, **overrides):
    config = make_config(**overrides)
    real = Content.load(config)
    content = Content(
        real.needs, list(real.categories.values()), doc["questions"], real.gazetteer,
        root=real.root, question_doc=doc, trade_policy=real.trade.doc,
    )
    game = GameEngine.for_test(utc(2026, 9, 1, 12), rng_seed=1, config=config, content=content)
    game.register_player("p1", "@ada", "Reykjavík", is_facilitator=True)
    game.register_player("p2", "@bo", "Valparaíso")
    game.register_player("p3", "@cy", "Hobart")
    file_orders(game)
    game.start()
    return game


# -- #25 (data): the ladder's arithmetic -----------------------------------

class LadderArithmeticTest(unittest.TestCase):
    """One outcome per distribution, chosen by counting, per selection steps 1-5."""

    def test_everyone_agreeing_is_the_world(self):
        outcome = report(3)["outcome"]
        self.assertEqual((outcome["kind"], outcome["id"]), ("tier", "unanimous"))
        self.assertIn("the world", outcome["phrases"])

    def test_two_of_three_is_a_supermajority(self):
        outcome = report(2, 1)["outcome"]
        self.assertEqual(outcome["id"], "supermajority")
        self.assertIn("most nations", outcome["phrases"])

    def test_four_of_five_is_near_unanimous_and_may_name_the_one_hold_out(self):
        outcome = report(4, 1)["outcome"]
        self.assertEqual(outcome["id"], "near_unanimous")
        self.assertTrue(phrase_licensed(outcome, "the world, with one hold-out"))

    def test_eight_of_ten_is_near_unanimous_but_has_two_hold_outs(self):
        # Same tier, same share, and the sharper wording is now false. This is
        # the phrases / conditional_phrases split doing its job.
        outcome = report(8, 1, 1)["outcome"]
        self.assertEqual(outcome["id"], "near_unanimous")
        self.assertFalse(phrase_licensed(outcome, "the world, with one hold-out"))

    def test_a_leading_half_is_a_plurality_not_a_majority(self):
        outcome = report(2, 1, 1)["outcome"]
        self.assertEqual(outcome["id"], "plurality")

    def test_two_of_five_sits_exactly_on_the_plurality_floor(self):
        # 2/5 is 0.4 exactly. Measured in binary floats this is the kind of
        # comparison that falls the wrong way; shares are Fractions for exactly
        # this distribution.
        outcome = report(2, 1, 1, 1)["outcome"]
        self.assertEqual(outcome["id"], "plurality")
        self.assertEqual(report(2, 1, 1, 1)["measure"]["share"]["exact"], "2/5")

    def test_a_two_two_split_is_a_tie_not_a_plurality(self):
        outcome = report(2, 2)["outcome"]
        self.assertEqual((outcome["kind"], outcome["id"]), ("tie_case", "tie_case"))
        self.assertTrue(phrase_licensed(outcome, "the world is split down the middle"))

    def test_a_tie_with_a_bucket_underneath_it_is_not_split_down_the_middle(self):
        outcome = report(2, 2, 1)["outcome"]
        self.assertEqual(outcome["kind"], "tie_case")
        self.assertFalse(phrase_licensed(outcome, "the world is split down the middle"))

    def test_three_singletons_are_fragmented_and_no_two_nations_agree(self):
        outcome = report(1, 1, 1)["outcome"]
        self.assertEqual(outcome["kind"], "fragmented_case")
        self.assertTrue(phrase_licensed(outcome, "no two nations agree"))

    def test_pairs_all_the_way_down_are_fragmented_but_some_nations_do_agree(self):
        # 2/2/2: the largest share is a third, below the floor, so step 3 owns it
        # before step 4's tie can -- and "no two nations agree" is false.
        result = report(2, 2, 2)
        self.assertEqual(result["outcome"]["kind"], "fragmented_case")
        self.assertFalse(phrase_licensed(result["outcome"], "no two nations agree"))
        self.assertTrue(result["measure"]["largest_is_tied"])

    def test_two_answers_get_the_floor_rather_than_aggregate_framing(self):
        result = report(1, 1, asked_of=4)
        outcome = result["outcome"]
        self.assertEqual(outcome["kind"], "low_respondent_floor")
        self.assertTrue(phrase_licensed(outcome, "the only two delegations to reply"))
        self.assertFalse(phrase_licensed(outcome, "the single city hall that answered"))
        self.assertIsNone(result["measure"])

    def test_one_answer_gets_the_floor_and_says_it_is_one(self):
        outcome = report(1, asked_of=5)["outcome"]
        self.assertEqual(outcome["kind"], "low_respondent_floor")
        self.assertTrue(phrase_licensed(outcome, "the single city hall that answered"))

    def test_the_floor_needs_no_clustering(self):
        result = report(1, 1, unclustered=True, asked_of=4)
        self.assertEqual(result["bucketing"]["status"], "not_needed")
        self.assertEqual(result["outcome"]["kind"], "low_respondent_floor")
        self.assertTrue(result["reportable"])

    def test_every_distribution_up_to_ten_selects_exactly_one_outcome(self):
        # Steps 2-5 are claimed to be exhaustive and mutually exclusive. This
        # walks every bucket partition of every respondent count a legal game
        # can produce (3-10 mayors) and insists each one lands somewhere.
        built = ladder()
        question = a_question()
        for sizes in _partitions(10):
            answers, buckets = distribution(*sizes)
            result = aggregate.summarize(
                built, 1, question, answers, buckets, sum(sizes)
            )
            outcome = result["outcome"]
            self.assertIsNotNone(outcome, "no outcome for %r" % (sizes,))
            self.assertIn(
                outcome["kind"],
                ("tier", "tie_case", "fragmented_case", "low_respondent_floor"),
            )
            for entry in outcome["conditional_phrases"]:
                self.assertIsInstance(entry["licensed"], bool)


def _partitions(largest_total):
    """Every non-increasing bucket-size list totalling 1..largest_total."""
    out = []

    def walk(remaining, cap, acc):
        if remaining == 0:
            out.append(tuple(acc))
            return
        for size in range(min(cap, remaining), 0, -1):
            walk(remaining - size, size, acc + [size])

    for total in range(1, largest_total + 1):
        walk(total, total, [])
    return out


class MeasureAndGarnishTest(unittest.TestCase):
    def test_the_denominator_is_respondents_not_all_mayors(self):
        result = report(3, asked_of=9)
        self.assertEqual(result["answered"], 3)
        self.assertEqual(result["asked_of"], 9)
        self.assertEqual(result["silent"], 6)
        self.assertEqual(result["measure"]["share"]["exact"], "1/1")
        self.assertEqual(result["outcome"]["id"], "unanimous")

    def test_a_partial_response_must_be_disclosed_in_the_item(self):
        self.assertTrue(report(3, asked_of=9)["integrity"]["must_disclose_partial_response"])
        self.assertFalse(report(3, asked_of=3)["integrity"]["must_disclose_partial_response"])

    def test_the_integrity_rules_travel_with_the_report(self):
        rules = report(3)["integrity"]["rules"]
        self.assertTrue(rules)
        self.assertTrue(any("the world" in rule for rule in rules))

    def test_the_leading_bucket_is_the_headline_and_the_others_are_garnish(self):
        result = report(3, 2, 1)
        roles = {row["label"]: row["role"] for row in result["buckets"]}
        self.assertEqual(roles["bucket-0"], "headline")
        self.assertEqual(roles["bucket-1"], "subgroup")
        self.assertEqual(roles["bucket-2"], "outlier")
        self.assertIn("some countries", result["garnishes"]["subgroup"]["phrases"])
        self.assertIn("one lone municipality", result["garnishes"]["outlier"]["phrases"])

    def test_a_tie_makes_both_leading_buckets_the_headline(self):
        roles = [row["role"] for row in report(2, 2, 1)["buckets"]]
        self.assertEqual(roles, ["headline", "headline", "outlier"])

    def test_a_bucket_that_lost_never_becomes_the_aggregate(self):
        # The integrity rule in content/questions.json: garnishes are never
        # headlines. Structurally, no non-leading bucket may carry a tier's
        # phrases, and the garnish block says so in the payload.
        result = report(3, 2)
        self.assertNotIn(
            "most nations", result["garnishes"]["subgroup"]["phrases"]
        )
        self.assertIn("garnish", result["garnishes"]["note"])

    def test_buckets_are_ordered_biggest_first_and_deterministically(self):
        labels = [row["label"] for row in report(1, 3, 2)["buckets"]]
        self.assertEqual(labels, ["bucket-1", "bucket-2", "bucket-0"])


class UnclusteredAnswersTest(unittest.TestCase):
    """Freeform answers are not bucketed by arithmetic, and are not guessed."""

    def test_answers_nobody_has_clustered_yield_no_outcome(self):
        result = report(1, 1, 1, unclustered=True)
        self.assertIsNone(result["outcome"])
        self.assertFalse(result["reportable"])
        self.assertEqual(result["bucketing"]["status"], "pending")
        self.assertEqual(result["no_item_reason"], "pending")

    def test_an_unclustered_round_is_not_reported_as_a_fragmented_world(self):
        # The failure mode this guards: three mayors phrase the same answer three
        # ways, verbatim bucketing calls it 1/1/1, and the paper confidently
        # prints "no two nations agree" about a unanimous world.
        result = report(1, 1, 1, unclustered=True)
        self.assertIsNone(result["outcome"])
        self.assertIsNone(result["measure"])
        self.assertEqual(result["buckets"], [])
        self.assertNotIn("fragmented", result["written_by"])

    def test_nobody_answering_is_reported_as_such(self):
        result = aggregate.summarize(ladder(), 1, a_question(), {}, None, 4)
        self.assertIsNone(result["outcome"])
        self.assertEqual(result["no_item_reason"], "no_responses")
        self.assertEqual(result["answered"], 0)

    def test_the_report_says_what_to_cluster_on(self):
        result = report(1, 1, 1, unclustered=True)
        self.assertEqual(result["bucketing"]["clustering_hint"], a_question()["buckets"])
        self.assertIn("record_answer_buckets", result["bucketing"]["note"])

    def test_verbatim_bucketing_is_available_but_never_the_default(self):
        answers = {"A": "Yes", "B": " yes ", "C": "no"}
        buckets = aggregate.verbatim_buckets(answers)
        self.assertEqual(buckets, {"A": "yes", "B": "yes", "C": "no"})
        self.assertEqual(
            aggregate.summarize(ladder(), 1, a_question(), answers, None, 3)["bucketing"][
                "status"
            ],
            "pending",
        )


class BucketingValidationTest(unittest.TestCase):
    def test_a_clustering_that_drops_a_respondent_is_refused(self):
        answers, buckets = distribution(2, 1)
        buckets.pop(sorted(buckets)[0])
        with self.assertRaises(RuleViolation) as caught:
            aggregate.validate_bucketing(answers, buckets)
        self.assertIn("denominator", str(caught.exception))

    def test_a_clustering_that_invents_a_respondent_is_refused(self):
        answers, buckets = distribution(2, 1)
        buckets["Atlantis"] = "bucket-9"
        with self.assertRaises(RuleViolation):
            aggregate.validate_bucketing(answers, buckets)

    def test_an_empty_bucket_label_is_refused(self):
        answers, buckets = distribution(2)
        buckets[sorted(buckets)[0]] = "   "
        with self.assertRaises(RuleViolation):
            aggregate.validate_bucketing(answers, buckets)

    def test_labels_are_trimmed_so_two_spellings_are_not_two_buckets(self):
        answers, buckets = distribution(2)
        cities = sorted(buckets)
        buckets[cities[0]] = " water "
        buckets[cities[1]] = "water"
        self.assertEqual(set(aggregate.validate_bucketing(answers, buckets).values()), {"water"})


# -- the ladder document itself --------------------------------------------

class LadderValidationTest(unittest.TestCase):
    """A malformed ladder must fail at startup, not mid-edition."""

    def _ladder_data(self):
        config = make_config()
        return copy.deepcopy(Content.load(config).phrasing_ladder("default"))

    def test_the_shipped_ladder_validates(self):
        built = ladder()
        self.assertEqual(
            built.describe()["tiers"],
            ["unanimous", "near_unanimous", "supermajority", "plurality"],
        )
        self.assertEqual(built.describe()["plurality_floor"]["exact"], "2/5")

    def test_misordered_tiers_are_refused(self):
        data = self._ladder_data()
        data["tiers"][1]["min_share"] = 1.0
        with self.assertRaises(ContentError) as caught:
            Ladder("default", data)
        self.assertIn("descending", str(caught.exception))

    def test_a_tier_below_the_aggregate_floor_is_refused(self):
        data = self._ladder_data()
        data["tiers"][-1]["min_respondents"] = 2
        with self.assertRaises(ContentError) as caught:
            Ladder("default", data)
        self.assertIn("vestigial", str(caught.exception))

    def test_a_lowest_tier_that_could_leave_no_outcome_is_refused(self):
        # If plurality demanded 5 respondents, a 3-respondent 2-1 split would
        # pass step 2, fail step 3 and 4, and then match no tier at all.
        data = self._ladder_data()
        data["tiers"][-1]["min_respondents"] = 5
        data["selection"]["min_respondents_for_aggregate"] = 3
        with self.assertRaises(ContentError):
            Ladder("default", data)

    def test_a_conditional_phrase_without_a_machine_checkable_guard_is_refused(self):
        data = self._ladder_data()
        data["tie_case"]["conditional_phrases"][0].pop("only_if_test")
        with self.assertRaises(ContentError) as caught:
            Ladder("default", data)
        self.assertIn("only_if_test", str(caught.exception))

    def test_an_outcome_with_no_wordings_is_refused(self):
        data = self._ladder_data()
        data["fragmented_case"]["phrases"] = []
        with self.assertRaises(ContentError):
            Ladder("default", data)

    def test_a_missing_case_block_is_refused(self):
        for missing in ("tie_case", "fragmented_case", "subgroup_phrasing", "outlier_phrasing"):
            data = self._ladder_data()
            data.pop(missing)
            with self.assertRaises(ContentError, msg=missing):
                Ladder("default", data)

    def test_every_shipped_conditional_phrase_states_when_it_is_true(self):
        data = self._ladder_data()
        found = 0
        for node in [data["tie_case"], data["fragmented_case"],
                     data["selection"]["low_respondent_floor"]] + data["tiers"]:
            for entry in node.get("conditional_phrases", []):
                found += 1
                self.assertTrue(Predicate(entry["only_if_test"]))
        self.assertEqual(found, 5)


class PredicateGrammarTest(unittest.TestCase):
    def test_the_guards_evaluate_against_the_counts(self):
        counts = {"R": 5, "largest": 4, "buckets": 2, "tied": 1}
        self.assertTrue(Predicate("R - largest == 1").holds(**counts))
        self.assertFalse(Predicate("2 * largest == R").holds(**counts))
        self.assertTrue(Predicate("largest > 1 and buckets >= 2").holds(**counts))

    def test_anything_beyond_arithmetic_on_the_counts_is_refused(self):
        for source in (
            "__import__('os').system('true')",
            "R.__class__",
            "open('config.json')",
            "'the world'",
            "R / largest",
            "total > 2",
        ):
            with self.assertRaises(ContentError, msg=source):
                Predicate(source)

    def test_an_unparseable_guard_is_a_content_error(self):
        with self.assertRaises(ContentError):
            Predicate("R ==")


# -- #25 through the engine ------------------------------------------------

class AggregateInTheGameTest(unittest.TestCase):
    def _answered_game(self, **overrides):
        game = new_game(**overrides)
        game.answer_question("p1", "Yes, obviously")
        game.answer_question("p2", "yes")
        game.answer_question("p3", "Absolutely not")
        return game

    def test_a_round_with_no_question_has_no_report(self):
        game = new_game(facilitator_questions__enabled=False)
        self.assertIsNone(game.mayor_question_report(1))

    def test_the_report_reaches_the_outcome_once_the_answers_are_clustered(self):
        game = self._answered_game()
        pending = game.mayor_question_report(1)
        self.assertEqual(pending["bucketing"]["status"], "pending")
        game.record_answer_buckets(
            1, {"Reykjavík": "pro", "Valparaíso": "pro", "Hobart": "anti"}
        )
        clustered = game.mayor_question_report(1)
        self.assertEqual(clustered["outcome"]["id"], "supermajority")
        self.assertEqual(clustered["measure"]["share"]["exact"], "2/3")
        self.assertEqual(clustered["bucketing"]["source"], "facilitator")

    def test_answers_and_buckets_are_keyed_by_city_never_by_handle(self):
        game = self._answered_game()
        game.record_answer_buckets(
            1, {"Reykjavík": "pro", "Valparaíso": "pro", "Hobart": "anti"}
        )
        payload = game.mayor_question_report(1)
        self.assertEqual(sorted(payload["answers_by_city"]), ["Hobart", "Reykjavík", "Valparaíso"])
        self.assertEqual(audit.find_handle_leaks(game, payload), [])
        self.assertNotIn("p1", json.dumps(payload))

    def test_the_questions_channel_never_cross_references_the_export_channel(self):
        # Integrity rule, and spec #18/#21 behind it: an aggregate item that
        # quoted an export alongside an answer could identify who submitted what.
        game = new_game()
        exports = [s.text for s in everyone_exports(game)]
        game.answer_question("p1", "Yes, obviously")
        payload = json.dumps(game.mayor_question_report(1))
        self.assertTrue(exports)
        for text in exports:
            self.assertNotIn(text, payload)
        audit.assert_blind(game, game.mayor_question_report(1))

    def test_a_city_spelled_without_its_diacritics_is_still_that_city(self):
        game = self._answered_game()
        game.record_answer_buckets(
            1, {"Reykjavik": "pro", "Valparaiso": "pro", "hobart": "anti"}
        )
        self.assertEqual(game.mayor_question_report(1)["outcome"]["id"], "supermajority")
        self.assertEqual(
            sorted(game.rounds[1].answer_buckets), ["Hobart", "Reykjavík", "Valparaíso"]
        )

    def test_two_spellings_of_one_city_are_refused_not_collapsed(self):
        game = self._answered_game()
        with self.assertRaises(RuleViolation):
            game.record_answer_buckets(
                1,
                {"Reykjavik": "pro", "Reykjavík": "anti", "Valparaíso": "pro",
                 "Hobart": "anti"},
            )

    def test_clustering_a_round_nobody_answered_is_refused(self):
        game = new_game()
        with self.assertRaises(RuleViolation):
            game.record_answer_buckets(1, {})

    def test_clustering_a_round_that_asked_nothing_is_refused(self):
        game = new_game(facilitator_questions__enabled=False)
        with self.assertRaises(RuleViolation):
            game.record_answer_buckets(1, {"Reykjavík": "pro"})

    def test_clustering_a_round_that_has_not_happened_is_refused(self):
        game = new_game()
        with self.assertRaises(RuleViolation):
            game.record_answer_buckets(99, {"Reykjavík": "pro"})

    def test_a_clustering_may_be_revised_while_the_game_runs(self):
        game = self._answered_game()
        game.record_answer_buckets(1, {"Reykjavík": "a", "Valparaíso": "b", "Hobart": "c"})
        self.assertEqual(game.mayor_question_report(1)["outcome"]["kind"], "fragmented_case")
        game.record_answer_buckets(1, {"Reykjavík": "a", "Valparaíso": "a", "Hobart": "a"})
        self.assertEqual(game.mayor_question_report(1)["outcome"]["id"], "unanimous")

    def test_each_round_keeps_its_own_answers_and_buckets(self):
        game = self._answered_game()
        game.record_answer_buckets(1, {"Reykjavík": "a", "Valparaíso": "a", "Hobart": "b"})
        advance(game)
        self.assertEqual(game.rounds[2].answers, {})
        self.assertIsNone(game.rounds[2].answer_buckets)
        self.assertEqual(game.mayor_question_report(1)["outcome"]["id"], "supermajority")

    def test_the_silent_count_uses_the_mayors_the_round_had(self):
        game = new_game()
        game.answer_question("p2", "yes")
        report_ = game.mayor_question_report(1)
        self.assertEqual(report_["answered"], 1)
        self.assertEqual(report_["asked_of"], 3)
        self.assertEqual(report_["silent"], 2)


class ExposurePolicyTest(unittest.TestCase):
    """#25 shares answers in the newspaper *by default* -- so it is a knob."""

    #: Distinctive enough that finding it in a payload cannot be a coincidence.
    ANSWER = "genetically-doomed-and-proud"

    def test_the_newspaper_carries_the_item_when_sharing_is_on(self):
        game = new_game(facilitator_questions__answers_shared_in_newspaper=True)
        game.answer_question("p2", self.ANSWER)
        item = views.round_briefing(game, 1)["mayor_question"]
        self.assertEqual(item["answers_by_city"], {"Valparaíso": self.ANSWER})

    def test_the_newspaper_carries_nothing_when_sharing_is_off(self):
        game = new_game(facilitator_questions__answers_shared_in_newspaper=False)
        game.answer_question("p2", self.ANSWER)
        self.assertIsNone(views.round_briefing(game, 1)["mayor_question"])
        self.assertIsNone(views.newspaper_mayor_question(game, 1))
        self.assertNotIn(self.ANSWER, json.dumps(views.archive(game)))

    def test_the_facilitator_still_sees_the_answers_when_sharing_is_off(self):
        game = new_game(facilitator_questions__answers_shared_in_newspaper=False)
        game.answer_question("p2", self.ANSWER)
        report_ = views.facilitator_question_report(game, 1)
        self.assertEqual(report_["audience"], "facilitator")
        self.assertFalse(report_["newspaper_visible"])
        self.assertEqual(report_["answers_by_city"], {"Valparaíso": self.ANSWER})

    def test_the_audit_catches_a_payload_that_ignores_the_policy(self):
        game = new_game(facilitator_questions__answers_shared_in_newspaper=False)
        leaky = {"mayor_question": {"answers_by_city": {"Valparaíso": self.ANSWER}}}
        violations = audit.find_exposure_violations(game, leaky)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["spec"], "#25")

    def test_a_shared_archive_passes_its_own_audit(self):
        game = play_out(new_game())
        audit.assert_exposure_policy(game, views.archive(game))


if __name__ == "__main__":
    unittest.main()
