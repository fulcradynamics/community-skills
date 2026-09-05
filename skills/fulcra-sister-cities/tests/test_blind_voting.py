"""Spec #18 and #21: the importer votes blind, and losers stay anonymous forever.

The interesting half of this file is the negative controls. An audit that always
returns "no leaks" proves nothing, so each leak check is also run against a
payload built to leak, and must catch it.
"""

import unittest

from harness import advance, everyone_exports, new_game, pick_first, play_out
from engine import audit, views
from engine.ballot import assign_refs
from engine.errors import BlindVotingViolation, PickRejected
from engine.state import READ_WINNER_REVEAL, Submission


class SubmissionShapeTest(unittest.TestCase):
    def test_a_submission_object_has_nowhere_to_put_an_exporter(self):
        # The structural guarantee behind #21: there is no field to leak, so no
        # forgotten serialisation can leak it.
        for slot in Submission.__slots__:
            self.assertNotIn("city", slot.lower())
            self.assertNotIn("player", slot.lower())
            self.assertNotIn("exporter", slot.lower())
            self.assertNotIn("handle", slot.lower())

    def test_the_ledger_refuses_to_de_anonymise_for_an_unlisted_reason(self):
        game = new_game()
        submission = game.submit_export("p2", "a far side")
        with self.assertRaises(BlindVotingViolation):
            game.ledger.city_for(submission.submission_id, "just curious")


class BallotBlindnessTest(unittest.TestCase):
    def test_a_ballot_entry_carries_only_a_ref_and_the_export(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        ballot = views.importer_ballot(game, "p1")
        self.assertTrue(ballot["entries"])
        for entry in ballot["entries"]:
            self.assertEqual(set(entry), {"ballot_ref", "export"})

    def test_no_city_is_named_anywhere_on_a_ballot(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        ballot = views.importer_ballot(game, "p1")
        self.assertEqual(audit.find_ballot_leaks(game, ballot), [])
        self.assertEqual(audit.find_handle_leaks(game, ballot), [])

    def test_the_check_in_slot_shows_the_same_blind_ballot(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        slot = [s for s in game.checkin("p1")["slots"] if s and s["kind"] == "import_pick"][0]
        self.assertEqual(audit.find_ballot_leaks(game, slot), [])
        for entry in slot["ballot"]:
            self.assertEqual(set(entry), {"ballot_ref", "export"})

    def test_only_the_importing_mayor_can_open_the_ballot(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        with self.assertRaises(PickRejected):
            views.importer_ballot(game, "p3", need_key="in-001")

    def test_ballot_order_is_shuffled_not_submission_order(self):
        # If refs tracked submission order, "ref A" would mean "whoever answered
        # first" -- an identity leak that looks like a coincidence.
        class Fake(object):
            def __init__(self, sid):
                self.submission_id = sid
                self.ballot_ref = None

        import random

        identity_permutations = 0
        trials = 60
        for trial in range(trials):
            fakes = [Fake("ex-%04d" % index) for index in range(5)]
            assign_refs(random.Random("seed|%d" % trial), fakes)
            refs = [f.ballot_ref for f in sorted(fakes, key=lambda f: f.submission_id)]
            self.assertEqual(sorted(refs), ["A", "B", "C", "D", "E"])
            if refs == ["A", "B", "C", "D", "E"]:
                identity_permutations += 1
        self.assertLess(identity_permutations, trials, "refs always follow submission order")


class PostRoundAnonymityTest(unittest.TestCase):
    def test_a_resolved_need_names_the_winner_and_withholds_the_rest(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        pick_first(game, "p1")
        advance(game)
        briefing = views.need_briefing(game, game.needs["in-001"])
        winners = [line for line in briefing["submissions"] if line["won"]]
        losers = [line for line in briefing["submissions"] if not line["won"]]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        self.assertIn("origin_city", winners[0])
        self.assertNotIn("origin_city", losers[0])
        self.assertEqual(losers[0]["origin"], "withheld")

    def test_nothing_is_published_while_a_need_is_still_collecting_or_picking(self):
        game = new_game()
        everyone_exports(game)
        self.assertEqual(views.need_briefing(game, game.needs["in-001"])["submissions"], [])
        advance(game)
        self.assertEqual(views.need_briefing(game, game.needs["in-001"])["submissions"], [])

    def test_the_whole_archive_of_a_full_game_leaks_nothing(self):
        game = play_out(new_game(founders=[("p2", "@bo", "Valparaíso"),
                                           ("p3", "@cy", "Hobart"),
                                           ("p4", "@di", "Tromsø")]))
        archive = views.archive(game)
        self.assertEqual(audit.find_identity_leaks(game, archive), [])
        self.assertEqual(audit.find_handle_leaks(game, archive), [])
        self.assertEqual(audit.find_ledger_misuse(game), [])
        self.assertTrue(audit.assert_blind(game, archive))

    def test_an_abandoned_game_leaks_nothing_either(self):
        # Every fallback path at once: nobody picks anything, some mayors are
        # silent, and one need gets no submissions at all.
        game = new_game()
        everyone_exports(game, exclude=("p3",))
        advance(game)
        advance(game)
        everyone_exports(game)
        while game.phase == "running":
            advance(game)
        self.assertTrue(audit.assert_blind(game, views.archive(game)))

    def test_an_even_split_may_name_every_city_because_they_all_won(self):
        game = new_game()
        everyone_exports(game)
        advance(game, 2)
        briefing = views.need_briefing(game, game.needs["in-001"])
        self.assertTrue(all(line["won"] for line in briefing["submissions"]))
        self.assertEqual(audit.find_identity_leaks(game, briefing), [])
        self.assertEqual(len(briefing["resolution"]["awards"]), 2)

    def test_winner_reveal_is_never_used_on_a_losing_submission(self):
        game = play_out(new_game())
        views.archive(game)
        for access in game.ledger.accesses:
            if access["reason"] == READ_WINNER_REVEAL:
                self.assertTrue(game.submissions[access["submission_id"]].is_winner)


class AuditNegativeControlTest(unittest.TestCase):
    """The audit must actually catch a leak, or it is decoration."""

    def _resolved_game(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        pick_first(game, "p1")
        advance(game)
        return game

    def _a_loser(self, game):
        return [s for s in game.submissions_for("in-001") if not s.is_winner][0]

    def test_a_city_next_to_a_losing_export_is_caught(self):
        game = self._resolved_game()
        loser = self._a_loser(game)
        city = game.ledger.city_for(loser.submission_id, "audit")
        leaky = {"submissions": [{"ballot_ref": loser.ballot_ref, "export": loser.text,
                                  "origin_city": city}]}
        leaks = audit.find_identity_leaks(game, leaky)
        self.assertEqual(len(leaks), 1)
        self.assertIn(city, leaks[0]["exposed"])

    def test_a_city_nested_under_a_losing_export_is_caught(self):
        game = self._resolved_game()
        loser = self._a_loser(game)
        city = game.ledger.city_for(loser.submission_id, "audit")
        leaky = {"entries": [{"ref": loser.ballot_ref, "export": loser.text,
                              "sender": {"about": {"city": city}}}]}
        self.assertEqual(len(audit.find_identity_leaks(game, leaky)), 1)

    def test_a_leaderboard_beside_a_losing_export_is_not_a_false_positive(self):
        # The leaderboard legitimately names every city, including losers'. Only
        # a city tied *to a specific submission* is a leak.
        game = self._resolved_game()
        briefing = views.round_briefing(game, 3)
        self.assertTrue(briefing["leaderboard"])
        self.assertEqual(audit.find_identity_leaks(game, briefing), [])

    def test_a_real_handle_in_a_payload_is_caught(self):
        game = self._resolved_game()
        self.assertEqual(audit.find_handle_leaks(game, {"byline": "@ada"}), ["@ada"])

    def test_a_city_on_a_ballot_is_caught(self):
        game = self._resolved_game()
        leaky = {"entries": [{"ballot_ref": "A", "export": "x", "from": "Hobart"}]}
        self.assertEqual(len(audit.find_ballot_leaks(game, leaky)), 1)

    def test_a_city_a_mayor_wrote_into_their_own_export_is_not_flagged(self):
        # A mayor who signs their own export has chosen to; the engine will not
        # rewrite what they wrote, and must not report its own view as broken.
        game = self._resolved_game()
        payload = {"entries": [{"ballot_ref": "A", "export": "greetings from Hobart"}]}
        self.assertEqual(audit.find_ballot_leaks(game, payload), [])

    def test_assert_blind_raises_on_a_leaky_payload(self):
        game = self._resolved_game()
        loser = self._a_loser(game)
        city = game.ledger.city_for(loser.submission_id, "audit")
        with self.assertRaises(BlindVotingViolation):
            audit.assert_blind(game, {"x": {"export": loser.text, "origin_city": city}})


if __name__ == "__main__":
    unittest.main()
