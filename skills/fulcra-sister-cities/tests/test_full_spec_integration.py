"""One complete game, and every requirement in spec.md checked against it at once.

This is M8. The other test modules each prove one milestone's rules in
isolation, on games built for the purpose; this one plays the whole recorded
game (:mod:`playtest`), publishes its editions, builds its site at the paper's
private address, and then asks whether all thirty-five requirements hold *at the
same time, on the same game*.

They are different questions. A queue rule and an exposure rule can each be
perfectly correct on their own fixture and still disagree about a mayor who
joined in round 9 and never exported. Nothing but a full run finds that.

Like :class:`tests.test_publish.SampleEditionArtifactTest` and
:class:`tests.test_hosting.SiteArtifactTest`, this writes into the repository
on purpose: the run is deterministic, so a build that changes nothing leaves a
clean tree and a build that changes the paper shows up as a reviewable diff. It
also means the committed ``editions/playtest-game/`` and ``site/`` are always
the output of the checks below rather than a snapshot somebody took once.
"""

import json
import os
import unittest

import harness  # noqa: F401 -- puts the repo root on sys.path

from engine import audit
from engine.content import normalize_city
from engine.game import LOCKSTEP_OPS
from engine.state import EVEN_SPLIT, RAMP_UP, RESOLVED, WINNER_PICK
from playtest import conformance, run as playtest_run
from playtest.table import LONG_WEEKEND, SEATS


class FullGameTest(unittest.TestCase):
    """The recorded game, played once, then interrogated from every angle."""

    @classmethod
    def setUpClass(cls):
        cls.game, cls.journal, cls.report, cls.artifacts = playtest_run.play(write=True)
        with open(playtest_run.report_path(), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(cls.report.to_dict(), indent=2, ensure_ascii=False) + "\n")

    # -- the checklist ----------------------------------------------------

    def test_no_requirement_fails(self):
        """Every deterministic check in spec.md's Evaluation Criteria, at once."""
        failures = [
            "%s %s: %s" % (f.spec, f.title, f.detail) for f in self.report.failures
        ]
        self.assertEqual(failures, [], "\n".join(failures))

    def test_every_requirement_is_accounted_for(self):
        """#1 to #35, with none quietly missing from the checklist.

        A requirement that nobody checks and nobody reports is the failure mode
        spec's Evaluation Criteria singles out: an untestable criterion must be
        reported as its own finding, not passed by omission.
        """
        covered = {finding.spec for finding in self.report.findings}
        expected = {"#%d" % n for n in range(1, 36)}
        self.assertEqual(expected - covered, set())

    def test_the_untestable_ones_are_reported_rather_than_passed(self):
        process = {f.spec for f in self.report.findings if f.status == conformance.PROCESS}
        judged = {f.spec for f in self.report.findings if f.status == conformance.JUDGED}
        # #8, #34 and #35 are properties of how the harness is run, not of a
        # played game. #25, #30, #32 and #33 are the four the spec itself marks
        # as needing subjective judgement.
        self.assertEqual(process, {"#8", "#34", "#35"})
        self.assertEqual(judged, {"#25", "#30", "#32", "#33"})
        for finding in self.report.findings:
            if finding.status in (conformance.PROCESS, conformance.JUDGED):
                self.assertTrue(finding.detail.strip(), finding.spec)
                self.assertNotEqual(finding.status, conformance.PASS)

    # -- the game actually happened ---------------------------------------

    def test_the_game_ran_to_its_end(self):
        self.assertEqual(self.game.phase, "ended")
        self.assertTrue(self.game.queue.exhausted)
        self.assertTrue(
            all(need.status == RESOLVED for need in self.game.needs.values())
        )

    def test_the_table_was_bigger_than_a_fixture(self):
        """Enough mayors, rounds and offers that the interactions are real."""
        self.assertEqual(len(self.game.players), len(SEATS))
        self.assertGreaterEqual(len(self.game.rounds), 12)
        self.assertGreaterEqual(len(self.game.submissions), 50)
        self.assertEqual(
            len({s.text for s in self.game.submissions.values()}),
            len(self.game.submissions),
            "two mayors submitted identical text; the offers are not real writing",
        )

    def test_all_three_resolution_paths_occurred_in_one_game(self):
        """#17, #18 and #19 in a single run, not three fixtures.

        The three fallbacks are usually tested apart, where each gets a game
        shaped to produce it. Here one seating plan produces all three, which is
        the only way to find out that they do not interfere.
        """
        modes = [
            need.resolution["mode"] for need in self.game.needs.values() if need.resolution
        ]
        for mode in (WINNER_PICK, RAMP_UP, EVEN_SPLIT):
            self.assertIn(mode, modes)

    def test_the_long_weekend_did_all_three_things_at_once(self):
        """One empty round drives a ramp-up, an even split and an empty postbag."""
        record = self.game.rounds[LONG_WEEKEND]
        self.assertEqual(record.answers, {})
        opened = next(
            n for n in self.game.needs.values() if n.opened_round == LONG_WEEKEND
        )
        closed = next(
            n for n in self.game.needs.values() if n.closed_round == LONG_WEEKEND
        )
        self.assertEqual(opened.resolution["mode"], RAMP_UP)
        self.assertEqual(closed.resolution["mode"], EVEN_SPLIT)
        # And the ramped-up city was still paid (spec #17).
        self.assertEqual(
            opened.resolution["awards"][0]["city"], opened.importing_city
        )

    def test_both_rotation_allotments_were_exercised(self):
        allotted = sorted({p.import_turns_allotted for p in self.game.players.values()})
        self.assertEqual(allotted, [1, 2])

    def test_a_duplicate_city_pick_was_reassigned_and_announced(self):
        moved = [entry for entry in self.journal.joins if entry["reassigned"]]
        self.assertTrue(moved, "the seating plan is supposed to contain a collision")
        for entry in moved:
            self.assertNotEqual(
                normalize_city(entry["city"]), normalize_city(entry["requested"])
            )
            self.assertIn(entry["requested"], entry["announcement"])
            self.assertIn(entry["city"], entry["announcement"])
        keys = [normalize_city(p.city) for p in self.game.players.values()]
        self.assertEqual(len(set(keys)), len(keys))

    def test_a_mid_game_arrival_was_queued_only_by_exporting(self):
        for player in self.game.players.values():
            if player.is_facilitator:
                continue
            first_export = min(
                (
                    s.submitted_round for s in self.game.submissions.values()
                    if self.game.ledger.player_for(s.submission_id, "audit") == player.player_id
                ),
                default=None,
            )
            self.assertEqual(player.queued_round, first_export, player.city)

    # -- the invariants, over everything this run produced ------------------

    def test_nothing_this_run_published_ties_a_losing_offer_to_a_city(self):
        """Spec #21 over everything this run published, at once.

        Deliberately wider than any single milestone's check: the payload the
        paper was built from, the rendered editions, and the bytes actually
        served, in one audit over one game.

        Deliberately *not* the replay journal or the recorded transcript. Those
        are the game's input -- which mayor sent which text -- and every game,
        played live or replayed, has that at the moment of submission; the engine
        keeps the same mapping itself, in a ledger that answers only for an
        audited reason and that the paper is never handed (see
        :mod:`engine.audit` and ``test_the_ledger_refuses_to_de_anonymise...``).
        #21 forbids *exposure*: to the importing mayor while they vote, and to
        every reader afterwards. Auditing the input record would report the
        game's own memory as a leak while saying nothing about the paper --
        which is the only artifact a player ever sees.

        What must be true of those two records instead is checked directly:
        :meth:`test_the_committed_transcript_carries_no_city_on_a_pick` and
        :meth:`test_no_input_record_reaches_the_published_site`.
        """
        audit.assert_blind(
            self.game,
            {
                "archive": self.artifacts["archive"],
                "editions": self.artifacts["editions"],
                "published": list(self.artifacts["public_files"].values()),
            },
        )

    def test_no_input_record_reaches_the_published_site(self):
        """The input records exist; none of what only they know is served.

        The journal and the transcript know who wrote every losing offer. The
        published site must not, and the way that could quietly stop being true
        is a debugging aid finding its way into a page -- a player id in an
        attribute, a journal action in a comment.
        """
        published = "\n".join(self.artifacts["public_files"].values())
        for player in self.game.players.values():
            self.assertNotIn(player.player_id, published, player.city)
            self.assertNotIn(player.handle, published, player.city)
        actions = self.journal.to_dict().get("actions", [])
        self.assertTrue(actions, "the journal recorded nothing; this proves little")
        for action in actions:
            if isinstance(action, str) and len(action) > 24:
                self.assertNotIn(action, published)

    def test_a_signed_offer_reached_the_ballot_and_not_the_paper(self):
        """The one case the engine may not fix, and the paper must (spec #21).

        A mayor who names their own city in an export has identified themselves
        to the importer, and the engine does not rewrite what a player wrote --
        see ``engine.audit.find_ballot_leaks``. What must not happen is the
        *paper* reprinting that text for an offer that lost, which would publish
        a losing city's identity to everybody. One mayor signs exactly one offer
        in this game precisely so that path is exercised.
        """
        cities = {p.city for p in self.game.players.values()}
        signed = [
            s for s in self.game.submissions.values()
            if any(city in s.text for city in cities)
        ]
        self.assertTrue(signed, "no offer named a city; this path went untested")
        published = "\n".join(self.artifacts["public_files"].values())
        for submission in signed:
            if not submission.is_winner:
                self.assertNotIn(submission.text, published, submission.submission_id)

    def test_no_published_byte_carries_the_address_or_a_handle(self):
        needle = self.artifacts["site_id"]
        handles = [p.handle for p in self.game.players.values()]
        for name, text in self.artifacts["public_files"].items():
            self.assertNotIn(needle, text, name)
            for handle in handles:
                self.assertNotIn(handle, text, name)

    def test_the_committed_transcript_carries_no_city_on_a_pick(self):
        data = self.artifacts["transcript_data"]
        cities = {p.city for p in self.game.players.values()}
        for need, pick in data["picks"].items():
            blob = json.dumps(pick, ensure_ascii=False)
            for city in cities:
                if city == self.game.needs[need].importing_city:
                    continue  # the importer's own city is not a secret from them
                self.assertNotIn(city, blob, "%s names %s" % (need, city))

    def test_every_round_logged_the_lockstep_and_nothing_else(self):
        for index, record in self.game.rounds.items():
            self.assertEqual(tuple(record.ops), LOCKSTEP_OPS, index)
        self.assertEqual(len(self.game.timers()), 1)
        self.assertEqual(audit.find_extra_timers(), [])

    # -- M9: who ordered, what they ordered, and who published it -----------

    def test_every_need_in_the_whole_game_was_ordered_by_its_own_mayor(self):
        """Spec #13, over a seventeen-round game rather than a fixture."""
        for need in self.game.needs.values():
            mayor = self.game.players[need.importing_player_id].mayor
            self.assertEqual(need.order["filed_by"], mayor, need.need_key)
            self.assertIn(need.order["request_source"], ("seed", "freeform"))
            self.assertIn(need.order["trade_family"], self.game.content.trade.families)

    def test_no_prompt_this_game_asked_a_mayor_for_advice(self):
        """Spec #13a, over everything the game actually put in front of anybody."""
        policy = self.game.content.trade
        for need in self.game.needs.values():
            for field in ("title", "need_brief", "exporter_prompt"):
                self.assertIsNone(
                    policy.advice_marker_in(need.rendered[field]),
                    "%s: %s" % (need.need_key, need.rendered[field]),
                )

    def test_the_paper_came_out_because_rounds_ended_not_because_a_script_ran(self):
        """Spec #26: publication is a consequence of the game, not of the harness."""
        desk = self.artifacts["desk"]
        completed = self.game.completed_rounds()
        self.assertEqual([t.round for t in desk.transactions], completed)
        self.assertEqual([n.round for n in desk.notices], completed)
        self.assertEqual(completed, sorted(self.game.rounds))
        for transaction in desk.transactions:
            self.assertEqual(transaction.edition["round"], transaction.round)
            self.assertEqual(transaction.published["edition"]["round"], transaction.round)
        self.assertTrue(desk.transactions[-1].ended)
        self.assertTrue(desk.transactions[-1].published["final"])

    def test_the_notices_carry_the_address_and_the_receipts_never_do(self):
        desk = self.artifacts["desk"]
        site_id = self.artifacts["site_id"]
        for notice in desk.notices:
            self.assertIn(site_id, notice.text)
        self.assertNotIn(site_id, json.dumps(desk.describe(), ensure_ascii=False))

    # -- the artifacts ------------------------------------------------------

    def test_the_editions_and_the_site_agree_about_the_game(self):
        editions = self.artifacts["editions"]
        site = self.artifacts["site"]
        self.assertEqual(
            [entry["round"] for entry in editions["editions"]], sorted(self.game.rounds)
        )
        self.assertEqual(site["rounds"], sorted(self.game.rounds))
        self.assertIsNotNone(editions["final"])
        self.assertIn("final.html", self.artifacts["public_files"])

    def test_every_edition_has_an_image_and_says_where_it_came_from(self):
        for entry in self.artifacts["editions"]["editions"]:
            self.assertTrue(entry["image_modality"], entry["round"])
        final = self.artifacts["editions"]["final"]
        self.assertTrue(final["image_modality"])
        self.assertEqual(
            sorted(final["cities"]), sorted(p.city for p in self.game.players.values())
        )

    def test_rebuilding_produces_the_same_bytes(self):
        """The whole point of storing the transcript."""
        before = dict(self.artifacts["public_files"])
        _, _, _, again = playtest_run.play(write=True)
        self.assertEqual(again["public_files"], before)

    def test_the_committed_public_tree_is_exactly_the_manifest(self):
        site = self.artifacts["site"]
        with open(site["manifest_path"], encoding="utf-8") as fh:
            book = json.load(fh)
        self.assertEqual(
            sorted(os.listdir(site["public_root"])),
            sorted(entry["path"] for entry in book["files"]),
        )
        self.assertTrue(book["address"]["address_withheld"])


class ConformanceReportTest(unittest.TestCase):
    """The report itself has to be honest about what it did and did not decide."""

    @classmethod
    def setUpClass(cls):
        cls.game, cls.journal, cls.report, cls.artifacts = playtest_run.play(write=False)

    def test_a_judged_finding_carries_the_evidence_it_refuses_to_grade(self):
        for finding in self.report.judged:
            self.assertIsNotNone(finding.evidence, finding.spec)

    def test_the_report_never_publishes_the_address(self):
        blob = json.dumps(self.report.to_dict(), ensure_ascii=False)
        self.assertNotIn(self.artifacts["site_id"], blob)

    def test_the_report_never_publishes_a_handle_or_a_losing_origin(self):
        blob = json.dumps(self.report.to_dict(), ensure_ascii=False)
        for player in self.game.players.values():
            self.assertNotIn(player.handle, blob)
        audit.assert_blind(self.game, self.report.to_dict())

    def test_a_check_run_writes_nothing(self):
        """``--check`` has to be safe to run against a dirty working tree."""
        self.assertTrue(self.report.findings)
        self.assertFalse(
            os.path.exists(os.path.join(
                self.artifacts["editions"]["directory"], "index.md"
            )),
            "a check run left its temporary editions behind",
        )


if __name__ == "__main__":
    unittest.main()
