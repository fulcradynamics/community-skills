"""Spec #11 and #23: one check-in per round, two slots, question in the spare one.

Question *phrasing* and the aggregate newspaper framing are M6/M5's work; this
milestone only has to allocate the slot correctly and store what comes back.
"""

import unittest

from harness import advance, everyone_exports, new_game, pick_first
from engine.errors import CheckInExhausted, PhaseError, RuleViolation


def kinds(checkin):
    return [slot["kind"] if slot else None for slot in checkin["slots"]]


class SlotAllocationTest(unittest.TestCase):
    def test_a_mayor_with_one_pending_action_also_gets_a_question(self):
        game = new_game()
        self.assertEqual(kinds(game.checkin("p2")), ["export", "mayor_question"])
        self.assertEqual(game.checkin("p2")["pending_game_actions"], 1)

    def test_the_importing_mayor_of_the_open_need_has_only_a_question(self):
        # They opened the need, so they neither export to it nor pick yet.
        game = new_game()
        self.assertEqual(kinds(game.checkin("p1")), [None, "mayor_question"])

    def test_two_pending_game_actions_crowd_the_question_out(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        # p1 must pick a winner for round 1's need and may export to round 2's.
        self.assertEqual(kinds(game.checkin("p1")), ["import_pick", "export"])
        self.assertEqual(game.checkin("p1")["pending_game_actions"], 2)

    def test_a_mayor_with_no_pending_action_still_gets_the_question(self):
        game = new_game()
        everyone_exports(game)
        advance(game)
        # p2 opened round 2's need and has nothing to pick, so: question only.
        self.assertEqual(kinds(game.checkin("p2")), [None, "mayor_question"])

    def test_a_pick_pending_alongside_an_export_survives_doing_the_export_first(self):
        # The slot set is fixed when the round opens. If it were recomputed from
        # "what is still undone", exporting first would make a question appear
        # and answering it could crowd out the pick that was already pending.
        game = new_game()
        everyone_exports(game)
        advance(game)
        game.submit_export("p1", "an export, submitted before picking")
        checkin = game.checkin("p1")
        self.assertEqual(kinds(checkin), ["import_pick", None])
        self.assertEqual(checkin["pending_game_actions"], 2)
        with self.assertRaises(RuleViolation):
            game.answer_question("p1", "sneaking a question in")
        self.assertIsNotNone(pick_first(game, "p1"))

    def test_the_question_slot_can_be_ungated_by_config(self):
        game = new_game(
            facilitator_questions__fill_second_slot_only_if_no_second_game_action_pending=False
        )
        everyone_exports(game)
        advance(game)
        self.assertEqual(
            kinds(game.checkin("p1")), ["import_pick", "export", "mayor_question"]
        )

    def test_slots_report_the_one_shared_round_deadline(self):
        game = new_game()
        checkin = game.checkin("p2")
        for slot in checkin["slots"]:
            if slot:
                self.assertEqual(slot["deadline"], checkin["deadline"])
        self.assertEqual(
            checkin["deadline"], game.timer.round_end(game.current_round).isoformat()
        )

    def test_no_check_in_once_the_game_has_ended(self):
        game = new_game()
        while game.phase == "running":
            everyone_exports(game)
            advance(game)
        with self.assertRaises(PhaseError):
            game.checkin("p2")


class OneCheckInPerRoundTest(unittest.TestCase):
    def test_a_used_slot_disappears_from_the_next_look(self):
        game = new_game()
        game.submit_export("p2", "the one export")
        self.assertEqual(kinds(game.checkin("p2")), [None, "mayor_question"])
        self.assertEqual(game.checkin_used("p2"), {"export": 1})

    def test_answering_twice_in_one_round_is_refused(self):
        game = new_game()
        game.answer_question("p2", "water, obviously")
        with self.assertRaises(CheckInExhausted):
            game.answer_question("p2", "on reflection, high ground")

    def test_slots_reset_each_round(self):
        game = new_game()
        game.submit_export("p2", "round one")
        game.submit_export("p3", "round one")
        self.assertEqual(game.checkin_used("p3"), {"export": 1})
        advance(game)  # round 2 opens p2's need, so p3 may export again
        self.assertEqual(game.checkin_used("p3"), {})
        self.assertIn("export", kinds(game.checkin("p3")))

    def test_a_question_cannot_be_answered_when_none_was_asked(self):
        game = new_game(facilitator_questions__enabled=False)
        with self.assertRaises(RuleViolation):
            game.answer_question("p2", "nobody asked")

    def test_an_empty_answer_is_refused_rather_than_recorded_as_a_skip(self):
        # Skipping is legitimate (asking_rules: a skipped mayor leaves the
        # denominator) but it is expressed by not answering, not by "".
        game = new_game()
        with self.assertRaises(RuleViolation):
            game.answer_question("p2", "   ")
        self.assertEqual(game.rounds[1].answers, {})


class AnswerRecordingTest(unittest.TestCase):
    def test_the_same_question_goes_to_every_mayor_in_a_round(self):
        game = new_game()
        question_id = game.rounds[1].question_id
        self.assertIsNotNone(question_id)
        for player_id in ("p1", "p2", "p3"):
            slot = [s for s in game.checkin(player_id)["slots"]
                    if s and s["kind"] == "mayor_question"][0]
            self.assertEqual(slot["question_id"], question_id)

    def test_answers_are_stored_against_the_round_that_asked(self):
        game = new_game()
        game.answer_question("p2", "the fish counter")
        game.answer_question("p3", "the water")
        self.assertEqual(
            game.rounds[1].answers, {"p2": "the fish counter", "p3": "the water"}
        )
        advance(game)
        self.assertEqual(game.rounds[2].answers, {})

    def test_every_question_is_framed_to_or_about_the_mayor(self):
        # Spec #24: questions are addressed to or about "the mayor" -- the
        # persona -- never to the person behind it.
        game = new_game()
        for question in game.content.questions:
            self.assertIn(question.get("framing"), ("to_the_mayor", "about_the_mayor"))
        slot = [s for s in game.checkin("p2")["slots"]
                if s and s["kind"] == "mayor_question"][0]
        self.assertIn(slot["framing"], ("to_the_mayor", "about_the_mayor"))
        self.assertTrue(slot["optional"])

    def test_answers_reach_the_newspaper_briefing_keyed_by_city_not_by_handle(self):
        from engine import views

        game = new_game()
        game.answer_question("p2", "the water")
        briefing = views.round_briefing(game, 1)["mayor_question"]
        self.assertEqual(briefing["answers_by_city"], {"Valparaíso": "the water"})
        self.assertNotIn("@bo", str(briefing))
        self.assertEqual(briefing["answered"], 1)
        self.assertIn("newspaper.wire", briefing["written_by"])


if __name__ == "__main__":
    unittest.main()
