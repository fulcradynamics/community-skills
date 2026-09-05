"""The newspaper: rendering, redaction, aggregate honesty, tone and the image.

Spec #25 (the written item), #26 (publish once per round), #28 (city and office
only), #29 (one image per edition, modality recorded) and #30 (tone). The judged
half of #30 -- funny, fun, colourful -- is the Evaluator's; what is testable here
is that the paper cannot print an unlicensed aggregate claim, cannot name a
losing exporter, cannot print a handle, and cannot leave a placeholder on the
page.
"""

import re
import unittest

from harness import make_config, new_game
from engine import views
from engine.errors import ContentError, RuleViolation
from newspaper import build_archive, build_edition, to_markdown
from newspaper import imagery, redact, voice, wire
from newspaper.copy import Chooser, NewspaperCopy, count_word, fill, sentence_case
from newspaper.edition import Paper
from newspaper.sample import ANSWERS, DELIBERATELY_UNSCRIPTED, sample_game

PLACEHOLDER_ESCAPE = "{"


def markdown_for(game, round_index):
    return to_markdown(build_edition(game, round_index))


class SampleGameShapeTest(unittest.TestCase):
    """The fixture has to keep containing the awkward cases, or the rest proves little."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()

    def test_the_sample_game_runs_to_completion(self):
        self.assertEqual(self.game.phase, "ended")
        self.assertEqual(len(self.game.rounds), 12)

    def test_it_exercises_all_three_resolution_paths(self):
        modes = {need.resolution["mode"] for need in self.game.needs.values()}
        self.assertEqual(modes, {"winner_pick", "ramp_up", "even_split"})

    def test_it_exercises_every_aggregate_outcome_the_ladder_can_select(self):
        outcomes = set()
        for index in sorted(self.game.rounds):
            report = self.game.mayor_question_report(index)
            if report and report["outcome"]:
                outcomes.add(report["outcome"]["id"])
        self.assertEqual(
            outcomes,
            {"unanimous", "near_unanimous", "supermajority", "plurality",
             "tie_case", "fragmented_case", "low_respondent_floor"},
        )

    def test_some_rounds_have_no_item_at_all(self):
        empty = [
            index for index in sorted(self.game.rounds)
            if (self.game.mayor_question_report(index) or {}).get("reportable") is False
        ]
        self.assertTrue(empty, "no round exercises the no-item path")

    def test_every_question_the_sample_draws_is_scripted(self):
        """A content edit that changes the draw must fail here, not go quiet.

        Otherwise the sample would keep rendering, with an empty postbag in place
        of whichever round lost its answers, and the aggregate coverage above
        would erode without anybody noticing.
        """
        drawn = [r.question_id for r in self.game.rounds.values() if r.question_id]
        self.assertTrue(drawn)
        unscripted = [
            q for q in drawn if q not in ANSWERS and q not in DELIBERATELY_UNSCRIPTED
        ]
        self.assertEqual(
            unscripted, [],
            "unscripted questions in newspaper/sample.py: %s" % unscripted,
        )
        # And the deliberate omission is still an omission of something drawn,
        # rather than a stale entry nobody has looked at.
        self.assertTrue(set(DELIBERATELY_UNSCRIPTED) <= set(drawn))

    def test_it_contains_an_export_that_names_its_own_city(self):
        cities = [p.city for p in self.game.players.values()]
        signed = [
            s.text for s in self.game.submissions.values()
            if redact.cities_named_in(s.text, cities)
        ]
        self.assertTrue(signed, "no self-identifying export, so #21's withholding is untested")


class EveryEditionTest(unittest.TestCase):
    """Whole-game checks: whatever the round contained, the paper holds up."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls.editions = [build_edition(cls.game, i) for i in sorted(cls.game.rounds)]
        cls.markdown = [to_markdown(edition) for edition in cls.editions]

    def test_one_edition_per_completed_round(self):
        # Spec #26: once per completed round, not batched.
        self.assertEqual(
            [edition["round"] for edition in self.editions], sorted(self.game.rounds)
        )
        self.assertEqual(
            [edition["edition_line"] for edition in self.editions[:3]],
            ["Vol. I, No. 1", "Vol. I, No. 2", "Vol. I, No. 3"],
        )

    def test_no_placeholder_ever_reaches_the_page(self):
        for text, edition in zip(self.markdown, self.editions):
            self.assertNotIn(
                PLACEHOLDER_ESCAPE, text,
                "edition %s printed an unfilled placeholder" % edition["round"],
            )

    def test_no_milestone_stub_reaches_the_page(self):
        for text, edition in zip(self.markdown, self.editions):
            self.assertNotIn("[[", text, "edition %s printed a stub" % edition["round"])

    def test_the_lockstep_departments_appear_in_a_fixed_order(self):
        for edition in self.editions:
            ids = [department["id"] for department in edition["departments"]]
            self.assertEqual(ids, sorted(ids, key=_department_rank), edition["round"])
            for required in ("wanted", "sealed_bids", "arrivals", "corrections"):
                self.assertIn(required, ids)

    def test_every_edition_carries_exactly_one_image(self):
        for edition in self.editions:
            image = edition["image"]
            self.assertFalse(image.get("omitted"), edition["round"])
            self.assertTrue(image["content"])
            self.assertEqual(self.markdown[edition["round"] - 1].count("!["), 1)

    def test_the_standing_printed_is_that_round_s_standing_not_the_final_one(self):
        """An edition is a historical document (spec #26, #27).

        This is the failure the per-round snapshot exists to prevent: rendering an
        archive from a finished game and printing the closing table in all twelve
        editions.
        """
        tables = []
        for edition in self.editions:
            ledger = _department(edition, "the_ledger")
            table = next(b for b in ledger["blocks"] if b["kind"] == "table")
            tables.append({row[1]: row[2] for row in table["rows"]})
        self.assertNotEqual(tables[0], tables[-1])
        self.assertEqual(set(tables[0].values()), {"0"})
        # Cumulative, so no city's total ever goes down between editions.
        for earlier, later in zip(tables, tables[1:]):
            for city, amount in earlier.items():
                self.assertLessEqual(float(amount), float(later[city]), city)

    def test_a_mayor_who_joins_mid_game_is_absent_until_they_join(self):
        first = _department(self.editions[0], "the_ledger")
        table = next(b for b in first["blocks"] if b["kind"] == "table")
        self.assertNotIn("Bergen", [row[1] for row in table["rows"]])
        self.assertIn("Bergen", self.markdown[2])


class IdentityRedactionTest(unittest.TestCase):
    """Spec #21 and #28: what the paper may never print."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls.editions = [build_edition(cls.game, i) for i in sorted(cls.game.rounds)]
        cls.markdown = [to_markdown(edition) for edition in cls.editions]

    def test_no_handle_appears_anywhere_in_any_edition(self):
        handles = [p.handle for p in self.game.players.values()]
        blob = "\n".join(self.markdown) + "\n".join(
            edition["image"]["content"] for edition in self.editions
        )
        for handle in handles:
            self.assertNotIn(handle, blob)

    def test_no_player_id_appears_anywhere_in_any_edition(self):
        blob = "\n".join(self.markdown)
        for player_id in self.game.players:
            self.assertNotIn(player_id, blob)

    def test_a_losing_export_is_never_printed_beside_a_city(self):
        cities = [p.city for p in self.game.players.values()]
        for edition in self.editions:
            for block in _blocks(edition):
                if block.get("role") != redact.DECLINED_ROLE:
                    continue
                for item in block["items"]:
                    self.assertEqual(redact.cities_named_in(item, cities), [], item)

    def test_a_self_identifying_export_is_withheld_rather_than_reprinted(self):
        cities = [p.city for p in self.game.players.values()]
        signed = [
            s.text for s in self.game.submissions.values()
            if not s.is_winner and redact.cities_named_in(s.text, cities)
        ]
        self.assertTrue(signed)
        blob = "\n".join(self.markdown)
        for text in signed:
            self.assertNotIn(text, blob)

    def test_the_audit_agrees_over_every_edition(self):
        for edition, text in zip(self.editions, self.markdown):
            redact.assert_edition_is_redacted(
                self.game, edition, rendered=[text, edition["image"]["content"]]
            )

    def test_a_leaked_handle_is_caught_rather_than_published(self):
        edition = build_edition(self.game, 3)
        handle = self.game.players["m-hbt"].handle
        edition["departments"][0]["blocks"].append(
            {"kind": "para", "text": "Our thanks to %s for the tip." % handle}
        )
        with self.assertRaises(RuleViolation):
            redact.assert_edition_is_redacted(self.game, edition)

    def test_a_declined_export_block_that_named_a_city_would_be_caught(self):
        edition = build_edition(self.game, 3)
        edition["departments"][0]["blocks"].append(
            {"kind": "list", "role": redact.DECLINED_ROLE,
             "items": ["Something, sent by Hobart."]}
        )
        with self.assertRaises(RuleViolation):
            redact.assert_edition_is_redacted(self.game, edition)

    def test_an_unknown_identity_style_is_refused(self):
        from engine.errors import ConfigError

        game = new_game(newspaper__player_identity_style="anything_goes")
        with self.assertRaises(ConfigError):
            build_edition(game, 1)


class SealedBidsBlindnessTest(unittest.TestCase):
    """Spec #18: the department that reports a closed window has nothing to leak."""

    def test_the_closed_window_report_carries_a_count_and_no_origins(self):
        game = sample_game()
        for index in sorted(game.rounds):
            edition = build_edition(game, index)
            bids = _department(edition, "sealed_bids")
            self.assertFalse(bids["provenance"].get(
                "origins_available_to_this_department", False
            ))

    def test_the_briefing_never_offers_submissions_before_a_need_resolves(self):
        game = sample_game()
        for need in game.needs.values():
            briefing = views.need_briefing(game, need)
            if need.status != "resolved":
                self.assertEqual(briefing["submissions"], [])


class AggregateItemTest(unittest.TestCase):
    """Spec #25: the sentence has to be true of the distribution."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()

    def _items(self):
        for index in sorted(self.game.rounds):
            edition = build_edition(self.game, index)
            item = _department(edition, "the_wire")
            if item:
                yield index, item, self.game.mayor_question_report(index)

    def test_every_printed_claim_uses_a_phrase_the_ladder_licensed(self):
        seen = 0
        for index, item, report in self._items():
            provenance = item["provenance"]
            if provenance["outcome"] is None:
                continue
            seen += 1
            outcome = report["outcome"]
            wire.assert_licensed(provenance["phrase_used"], outcome)
            printed = "\n".join(
                block["text"] for block in item["blocks"] if "text" in block
            )
            # Case-insensitively: a phrase that opens the claim is sentence-cased
            # on the page, which is a typographic change and not a different
            # claim.
            self.assertIn(provenance["phrase_used"].lower(), printed.lower(), index)
        self.assertGreater(seen, 5)

    def test_no_unlicensed_conditional_wording_is_ever_printed(self):
        """The specific failure spec #25 names: the sharper line, unearned.

        "the world, with one hold-out" is true at 4-of-5 and false at 8-of-10.
        Both select the same tier, so selecting the tier correctly is not enough.
        """
        for index, item, report in self._items():
            if not report["reportable"]:
                continue
            refused = [
                entry["phrase"]
                for entry in report["outcome"]["conditional_phrases"]
                if not entry["licensed"]
            ]
            printed = "\n".join(
                block["text"] for block in item["blocks"] if "text" in block
            )
            for phrase in refused:
                self.assertNotIn(phrase, printed, "round %s printed %r" % (index, phrase))

    def test_a_conditional_wording_is_used_when_it_is_earned(self):
        earned = [
            (index, item["provenance"])
            for index, item, report in self._items()
            if report["reportable"] and any(
                entry["licensed"] for entry in report["outcome"]["conditional_phrases"]
            )
        ]
        self.assertTrue(earned, "no round in the sample earns a conditional wording")
        self.assertTrue(
            any(p["phrase_source"] == wire.FROM_CONDITIONAL for _, p in earned),
            "the licensed, sharper wording was never reached for",
        )

    def test_the_counts_printed_match_the_report(self):
        for index, item, report in self._items():
            if not report["reportable"]:
                continue
            printed = "\n".join(
                block["text"] for block in item["blocks"] if "text" in block
            )
            self.assertIn(str(report["answered"]), printed, index)
            if report["integrity"]["must_disclose_partial_response"]:
                self.assertIn(str(report["asked_of"]), printed, index)

    def test_a_partial_response_is_always_disclosed(self):
        # The content file's own integrity rule: an aggregate over some of the
        # mayors has to say so.
        for index, item, report in self._items():
            if report["reportable"] and report["integrity"][
                "must_disclose_partial_response"
            ]:
                self.assertTrue(item["provenance"]["partial_response_disclosed"], index)

    def test_the_item_never_mentions_an_export_or_a_ballot_ref(self):
        # The questions channel and the blind-voting channel must not
        # cross-reference each other (#18, #21).
        texts = [s.text for s in self.game.submissions.values()]
        for index, item, _ in self._items():
            printed = "\n".join(
                block["text"] for block in item["blocks"] if "text" in block
            )
            for text in texts:
                self.assertNotIn(text, printed, index)

    def test_an_unclustered_round_prints_a_holding_note_not_a_distribution(self):
        game = new_game()
        game.answer_question("p2", "the water")
        game.answer_question("p3", "the market")
        game.answer_question("p1", "the harbour")
        edition = build_edition(game, 1)
        item = _department(edition, "the_wire")
        self.assertEqual(item["provenance"]["no_item_reason"], "pending")
        self.assertIsNone(item["provenance"]["outcome"])
        # No claim of any kind: no phrase was chosen, so none was printed.
        self.assertNotIn("phrase_used", item["provenance"])
        printed = "\n".join(b["text"] for b in item["blocks"] if "text" in b)
        for answer in ("the water", "the market", "the harbour"):
            self.assertNotIn(answer, printed)

    def test_the_item_disappears_when_config_withholds_the_answers(self):
        game = new_game(facilitator_questions__answers_shared_in_newspaper=False)
        game.answer_question("p2", "the water")
        edition = build_edition(game, 1)
        self.assertIsNone(_department(edition, "the_wire"))
        self.assertNotIn("the water", to_markdown(edition))

    def _ladder_phrases(self):
        """Every garnish phrase the ladder can hand the prose, from content."""
        ladder = self.game.content.phrasing_ladder("default")
        phrases = []
        for family in ("subgroup_phrasing", "outlier_phrasing"):
            phrases.extend(ladder[family]["phrases"])
        return phrases

    def test_a_phrase_dropped_mid_sentence_is_not_capitalised(self):
        """A fragment is cased by the frame it lands in, never by its selection.

        The frames offer both ``{phrase}`` and ``{Phrase}`` precisely so that one
        ladder wording can open a sentence or sit inside one. Selecting the
        fragment with a method that sentence-cases it took that choice away from
        the frame, and printed "And then One lone municipality, from the Mayor of
        Bergen" -- a capital in the middle of a sentence.
        """
        capitalised = [
            (phrase, phrase[:1].upper() + phrase[1:]) for phrase in self._ladder_phrases()
        ]
        for index, item, _ in self._items():
            for block in item["blocks"]:
                text = block.get("text")
                if not text:
                    continue
                for phrase, upper in capitalised:
                    for match in re.finditer(re.escape(upper), text):
                        before = text[:match.start()].rstrip(" \t“\"'(*_[")
                        self.assertTrue(
                            before == "" or before[-1] in ".?!",
                            "round %s printed %r mid-sentence: %r"
                            % (index, upper, text),
                        )

    def test_the_world_scale_hook_headlines_only_a_real_aggregate(self):
        """Spec #25's judged failure, in the one place it is a heading.

        Every question's ``newspaper_hook`` is written at world scale ("Contents
        of the world's desks"). Over an empty postbag, or over the floor's one or
        two replies, that heading is aggregate language above a body that then
        says the paper cannot speak for the world -- so on those rounds the
        column is named after the postbag instead.
        """
        gated, hooked = 0, 0
        for index, item, report in self._items():
            hook = report.get("newspaper_hook")
            heading = next(b["text"] for b in item["blocks"] if b["kind"] == "heading")
            licensed = wire.licenses_aggregate_heading(report)
            self.assertEqual(item["provenance"]["aggregate_heading_used"], licensed, index)
            if licensed:
                hooked += 1
                self.assertEqual(heading, hook, index)
            else:
                gated += 1
                self.assertNotEqual(heading, hook, index)
                self.assertNotIn("world", heading.lower(), index)
        self.assertTrue(gated, "no round in the sample exercises the gated heading")
        self.assertTrue(hooked, "no round in the sample earns its hook")

    def test_an_empty_postbag_is_not_headlined_as_the_world(self):
        game = new_game()
        game.advance_round()
        edition = build_edition(game, 1)
        item = _department(edition, "the_wire")
        report = game.mayor_question_report(1)
        self.assertEqual(report["answered"], 0)
        heading = next(b["text"] for b in item["blocks"] if b["kind"] == "heading")
        self.assertNotIn("world", heading.lower())
        self.assertFalse(item["provenance"]["aggregate_heading_used"])

    def test_the_floor_reports_its_replies_without_claiming_a_world(self):
        """One or two replies license no aggregate framing -- heading included."""
        game = new_game()
        game.answer_question("p2", "the fog")
        game.advance_round()
        report = game.mayor_question_report(1)
        self.assertEqual(report["outcome"]["kind"], "low_respondent_floor")
        self.assertFalse(wire.licenses_aggregate_heading(report))
        item = _department(build_edition(game, 1), "the_wire")
        heading = next(b["text"] for b in item["blocks"] if b["kind"] == "heading")
        self.assertNotIn("world", heading.lower())

    def test_writing_an_unlicensed_phrase_raises_rather_than_publishing(self):
        outcome = {
            "id": "near_unanimous",
            "phrases": ["nearly every nation"],
            "conditional_phrases": [
                {"phrase": "the world, with one hold-out", "licensed": False}
            ],
        }
        with self.assertRaises(RuleViolation):
            wire.assert_licensed("the world, with one hold-out", outcome)
        wire.assert_licensed("nearly every nation", outcome)


class LedgerExposureTest(unittest.TestCase):
    """Spec #22: what the paper shows is config's decision, in one place."""

    def test_the_ledger_is_printed_when_config_says_so(self):
        game = sample_game()
        edition = build_edition(game, 6)
        self.assertIsNotNone(_department(edition, "the_ledger"))

    def test_the_ledger_and_the_skyline_both_vanish_when_it_is_hidden(self):
        config = make_config(economy__leaderboard_visible_in_newspaper=False)
        game = sample_game(config=config)
        edition = build_edition(game, 6)
        self.assertIsNone(_department(edition, "the_ledger"))
        text = to_markdown(edition)
        self.assertNotIn("The Ledger", text)
        # The illustration cannot show a standing the paper is withholding
        # either, so the skyline becomes weather.
        self.assertIn("fog bank", edition["image"]["alt"])
        self.assertIn("figures withheld", edition["image"]["content"])


class TonePolicyTest(unittest.TestCase):
    """Spec #30's flags, each doing something."""

    def test_the_forbidden_register_is_absent_from_the_papers_own_voice(self):
        """Every edition, with the mayors' own wording taken out first (#30b).

        This test used to scan the whole edition, including the offers the paper
        reprints. Spec #30b moved that line: an offer is player voice, printed
        as typed, and the register is the desk's standard for its own copy. So
        the scan is over the edition minus its player-voice passages -- and that
        those passages really are exempt, really do publish and really are
        marked as somebody's own words is ``tests/test_player_voice.py``, over
        the same sample game, one of whose offers trips the register on purpose.
        """
        game = sample_game()
        paper = Paper(game)
        for index in sorted(game.rounds):
            edition = paper.edition(index)
            editorial = voice.editorial_only(
                to_markdown(edition), voice.spans_in(edition)
            )
            self.assertEqual(paper.tone.findings(editorial), [], "round %s" % index)

    def test_an_edition_that_tripped_the_register_would_not_publish(self):
        game = sample_game()
        paper = Paper(game)
        with self.assertRaises(RuleViolation):
            paper.tone.check("The Mayor of Hobart is, frankly, incompetent.")

    def test_the_register_matches_words_and_not_substrings(self):
        """An ordinary word that merely contains a forbidden one must not trip.

        This is not hypothetical: a mayor's export in the integration game said
        "plant them closer together", and "closer" contains "loser", which held
        up an entire edition of a paper whose whole job is to reprint exports
        exactly as they were written.
        """
        paper = Paper(sample_game())
        innocent = (
            "Plant them closer together than looks sensible. A familiar sight, "
            "and a glassy house less draughty than the last."
        )
        self.assertEqual(paper.tone.findings(innocent), [])

    def test_the_register_still_catches_the_words_themselves(self):
        paper = Paper(sample_game())
        for guilty in ("what a loser", "the losers of this round", "you are a liar"):
            self.assertTrue(paper.tone.findings(guilty), guilty)

    def test_a_stem_in_the_register_still_catches_its_inflections(self):
        """``humiliat`` is one entry on purpose; anchoring both ends would kill it."""
        paper = Paper(sample_game())
        for guilty in ("humiliated", "humiliating", "a humiliation"):
            self.assertTrue(paper.tone.findings(guilty), guilty)

    def test_the_register_is_ignored_when_config_switches_the_check_off(self):
        game = sample_game(config=make_config(
            newspaper__tone__disallow_snide_or_mean=False
        ))
        paper = Paper(game)
        self.assertEqual(paper.tone.check("a pathetic showing"), [])

    def test_unfunny_mode_drops_the_asides_rather_than_lowering_the_key(self):
        game = sample_game(config=make_config(newspaper__tone__funny=False))
        edition = build_edition(game, 5)
        kinds = [block["kind"] for department in edition["departments"]
                 for block in department["blocks"]]
        self.assertNotIn("aside", kinds)
        # A note is a factual footnote rather than a joke, so it survives.
        self.assertIn("note", kinds)
        self.assertIn("aside", [block["kind"] for department in
                                build_edition(sample_game(), 5)["departments"]
                                for block in department["blocks"]])

    def test_pointed_frames_are_dropped_when_config_forbids_them(self):
        pool = ["a plain line", {"line": "a pointed line", "pointed": True}]
        self.assertEqual(
            Chooser(allow_pointed=False).allowed(pool, "test"), ["a plain line"]
        )
        self.assertEqual(len(Chooser(allow_pointed=True).allowed(pool, "test")), 2)

    def test_a_family_of_only_pointed_frames_is_a_content_error(self):
        with self.assertRaises(ContentError):
            Chooser(allow_pointed=False).allowed(
                [{"line": "only pointed", "pointed": True}], "test"
            )

    def test_the_whole_paper_still_renders_with_every_tone_flag_off(self):
        game = sample_game(config=make_config(
            newspaper__tone__funny=False,
            newspaper__tone__colorful=False,
            newspaper__tone__allow_pointed_humor=False,
        ))
        for index in sorted(game.rounds):
            text = to_markdown(build_edition(game, index))
            self.assertNotIn(PLACEHOLDER_ESCAPE, text)


class ImageModalityTest(unittest.TestCase):
    """Spec #29: raster preferred, SVG permitted, and the record says which."""

    def tearDown(self):
        imagery.unregister_raster_provider("stub_raster")

    def test_this_deployment_falls_back_to_svg_and_says_so(self):
        game = sample_game()
        image = build_edition(game, 4)["image"]
        self.assertEqual(image["provenance"]["modality"], imagery.SVG_PROCEDURAL)
        self.assertEqual(image["provenance"]["provider"], imagery.BUILTIN_SVG_PROVIDER)
        considered = image["provenance"]["considered"]
        self.assertEqual(considered[0]["modality"], imagery.RASTER)
        self.assertFalse(considered[0]["available"])
        self.assertIn("no image-generation provider", considered[0]["reason"])

    def test_raster_wins_when_a_provider_is_actually_available(self):
        """Proves the preference order is real rather than documented."""

        class Stub:
            provider_id = "stub_raster"

            def available(self):
                return True

            def generate(self, scene, palette, size):
                return {"content": b"PNG", "extension": "png", "mime": "image/png"}

        imagery.register_raster_provider(Stub())
        game = sample_game(config=make_config(
            newspaper__image__raster_providers=["stub_raster"]
        ))
        image = build_edition(game, 4)["image"]
        self.assertEqual(image["provenance"]["modality"], imagery.RASTER)
        self.assertEqual(image["provenance"]["provider"], "stub_raster")
        self.assertEqual(image["extension"], "png")

    def test_an_unavailable_provider_falls_through_to_the_svg(self):
        class Stub:
            provider_id = "stub_raster"

            def available(self):
                return False

            def generate(self, scene, palette, size):  # pragma: no cover
                raise AssertionError("must not be called")

        imagery.register_raster_provider(Stub())
        game = sample_game(config=make_config(
            newspaper__image__raster_providers=["stub_raster"]
        ))
        image = build_edition(game, 4)["image"]
        self.assertEqual(image["provenance"]["modality"], imagery.SVG_PROCEDURAL)

    def test_an_unregistered_provider_is_a_config_error_not_a_silent_fallback(self):
        from engine.errors import ConfigError

        game = new_game(newspaper__image__raster_providers=["typo_provider"])
        with self.assertRaises(ConfigError):
            build_edition(game, 1)

    def test_the_preference_order_is_honoured_when_svg_is_put_first(self):
        class Stub:
            provider_id = "stub_raster"

            def available(self):
                return True

            def generate(self, scene, palette, size):  # pragma: no cover
                raise AssertionError("must not be called")

        imagery.register_raster_provider(Stub())
        game = sample_game(config=make_config(
            newspaper__image__raster_providers=["stub_raster"],
            newspaper__image__modality_preference=["svg_procedural", "raster"],
        ))
        image = build_edition(game, 4)["image"]
        self.assertEqual(image["provenance"]["modality"], imagery.SVG_PROCEDURAL)

    def test_the_image_can_be_switched_off_and_says_why(self):
        game = sample_game(config=make_config(newspaper__image_per_edition=False))
        image = build_edition(game, 4)["image"]
        self.assertTrue(image["omitted"])
        self.assertIn("image_per_edition", image["reason"])
        self.assertNotIn("![", to_markdown(build_edition(game, 4)))


class ImageContentTest(unittest.TestCase):
    """Spec #29's substantive half: the illustration is drawn from the edition."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()

    def _image(self, index):
        return build_edition(self.game, index)["image"]

    def test_the_svg_is_well_formed_enough_to_parse(self):
        import xml.etree.ElementTree as ET

        for index in sorted(self.game.rounds):
            ET.fromstring(self._image(index)["content"])

    def test_the_dice_drawn_are_the_dice_that_were_rolled(self):
        for index in sorted(self.game.rounds):
            briefing = views.round_briefing(self.game, index)
            resolved = briefing["resolved"]
            alt = self._image(index)["alt"]
            if resolved is None:
                self.assertNotIn("dice showing", alt)
                continue
            for die in resolved["resolution"]["roll"]["dice"]:
                self.assertIn(str(die), alt)

    def test_the_crates_drawn_are_the_offers_that_arrived(self):
        for index in sorted(self.game.rounds):
            briefing = views.round_briefing(self.game, index)
            resolved = briefing["resolved"]
            if not resolved:
                continue
            count = resolved["resolution"]["submission_count"]
            if count:
                self.assertIn("%d crate" % count, self._image(index)["alt"], index)

    def test_the_only_city_named_near_the_crates_is_a_winner(self):
        for index in sorted(self.game.rounds):
            briefing = views.round_briefing(self.game, index)
            resolved = briefing["resolved"]
            content = self._image(index)["content"]
            winners = (
                [award["city"] for award in resolved["profit_awarded"]] if resolved else []
            )
            for player in self.game.players.values():
                if player.city in winners:
                    continue
                # Losing cities may still appear in the skyline, which is the
                # leaderboard and names everybody; what they must never appear in
                # is a caption about a crate.
                self.assertNotIn("chosen: %s" % player.city, content)

    def test_the_palette_follows_the_category_and_collapses_when_told_to(self):
        colourful = self._image(4)
        mono = build_edition(
            sample_game(config=make_config(newspaper__tone__colorful=False)), 4
        )["image"]
        self.assertTrue(colourful["colorful"])
        self.assertFalse(mono["colorful"])
        self.assertNotEqual(colourful["palette"], mono["palette"])

    def test_the_alt_text_describes_what_is_actually_drawn(self):
        alt = self._image(7)["alt"]
        self.assertIn("harbour scene", alt)
        self.assertIn("ribboned", alt)


class ArchiveTest(unittest.TestCase):
    """Spec #27: prior editions remain, and config says whether they do."""

    def test_the_archive_holds_every_edition_oldest_first(self):
        game = sample_game()
        archive = build_archive(game)
        self.assertEqual(
            [edition["round"] for edition in archive["editions"]], sorted(game.rounds)
        )
        self.assertTrue(archive["archive_prior_editions"])

    def test_switching_the_archive_off_leaves_only_the_latest(self):
        game = sample_game(config=make_config(newspaper__archive_prior_editions=False))
        archive = build_archive(game)
        self.assertEqual([e["round"] for e in archive["editions"]], [max(game.rounds)])

    def test_an_unsupported_cadence_is_refused(self):
        from engine.errors import ConfigError

        game = new_game(newspaper__publish_cadence="weekly_batch")
        with self.assertRaises(ConfigError):
            build_edition(game, 1)


class DeterminismTest(unittest.TestCase):
    def test_the_same_game_renders_the_same_paper_twice(self):
        first = to_markdown(build_edition(sample_game(), 5))
        second = to_markdown(build_edition(sample_game(), 5))
        self.assertEqual(first, second)

    def test_different_rounds_do_not_all_read_the_same(self):
        game = sample_game()
        bodies = {to_markdown(build_edition(game, i)) for i in sorted(game.rounds)}
        self.assertEqual(len(bodies), len(game.rounds))


class CopyMachineryTest(unittest.TestCase):
    def test_a_frame_with_an_unavailable_placeholder_is_a_content_error(self):
        with self.assertRaises(ContentError):
            fill("Hello {nobody}", {"city": "Hobart"}, "test")

    def test_a_placeholder_with_no_value_this_round_is_a_content_error(self):
        with self.assertRaises(ContentError):
            fill("Hello {city}", {"city": None}, "test")

    def test_an_export_containing_a_brace_is_reproduced_exactly(self):
        # str.format would raise on this; the paper has to print what was sent.
        self.assertEqual(
            fill("{export}", {"export": "a set {like this}"}, "test"),
            "a set {like this}",
        )

    def test_sentences_are_capitalised_after_a_full_stop(self):
        self.assertEqual(sentence_case("three offers. the mayor has them."),
                         "Three offers. The mayor has them.")

    def test_a_closing_quote_ends_a_sentence_rather_than_opening_one(self):
        # The bug this guards: “...April.” — the mayor of Bergen, rendered with a
        # capital M in the middle of a sentence because the full stop inside the
        # quotation looked like the end of one.
        self.assertEqual(sentence_case("“it is fine.” — the mayor of Hobart."),
                         "“It is fine.” — the mayor of Hobart.")
        self.assertEqual(sentence_case("*a prompt.* and then more"),
                         "*A prompt.* And then more")

    def test_small_numbers_are_spelled_out_and_large_ones_are_not(self):
        self.assertEqual((count_word(0), count_word(1), count_word(4), count_word(99)),
                         ("no", "one", "four", "99"))

    def test_the_same_key_always_picks_the_same_frame(self):
        chooser = Chooser()
        frames = ["a", "b", "c", "d"]
        self.assertEqual(
            chooser.pick(frames, (3, "x"), "t"), chooser.pick(frames, (3, "x"), "t")
        )

    def test_a_rotation_does_not_repeat_within_the_family(self):
        chooser = Chooser()
        frames = ["a", "b", "c"]
        picked = [chooser.rotate(frames, (1,), "t", offset) for offset in range(3)]
        self.assertEqual(sorted(picked), ["A", "B", "C"])  # sentence-cased on the way out

    def test_an_unknown_masthead_or_wire_style_is_refused(self):
        from engine.errors import ConfigError

        copy = NewspaperCopy.load(make_config())
        with self.assertRaises(ConfigError):
            copy.masthead(make_config(newspaper__masthead_id="no_such_paper"))
        with self.assertRaises(ConfigError):
            copy.wire_style(make_config(
                facilitator_questions__aggregate_phrasing_style="no_such_style"
            ))

    def test_an_unknown_prose_renderer_is_refused(self):
        from engine.errors import ConfigError

        game = new_game(newspaper__prose__renderer="a_model_we_have_not_written")
        with self.assertRaises(ConfigError):
            build_edition(game, 1)


# -- helpers ---------------------------------------------------------------

_ORDER = ("wanted", "sealed_bids", "arrivals", "the_wire", "the_ledger", "corrections")


def _department_rank(department_id):
    return _ORDER.index(department_id)


def _department(edition, department_id):
    for department in edition["departments"]:
        if department["id"] == department_id:
            return department
    return None


def _blocks(edition):
    for department in edition["departments"]:
        for block in department["blocks"]:
            yield block


if __name__ == "__main__":
    unittest.main()
