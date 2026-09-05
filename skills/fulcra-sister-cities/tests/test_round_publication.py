"""Spec #26: a completed round publishes itself, and tells the group.

M9's half of the newspaper requirement. M5 proved an edition can be rendered and
M6 proved an archive can be served; what neither proved is that anybody does it
without being asked, which is the clause spec #26 spells out ("a manually
callable renderer alone does not satisfy this requirement"). So every test here
plays a game and *never calls a renderer*: the only thing that moves is the
clock.
"""

import json
import os
import shutil
import tempfile
import unittest

from harness import advance, new_game, pick_first, play_out
from engine.errors import ConfigError, RuleViolation
from facilitator import Facilitator
from facilitator.transaction import resolve_steps
from newspaper.copy import Chooser

#: Offers with no city and no player id in them. The shared fixture's
#: ``everyone_exports`` writes "export from p2", and the paper reprints declined
#: offers verbatim -- so that fixture cannot publish, which is
#: :func:`newspaper.redact.assert_edition_is_redacted` working rather than a
#: problem to route around. Same reasoning as ``tests/test_endgame.py``'s.
OFFERS = (
    "A brass band, briefly, and the sheet music for one more.",
    "Two hundred metres of very good rope and somebody who can splice it.",
    "Eleven crates of seed potatoes and one very opinionated agronomist.",
    "A clock tower mechanism, dismantled, with most of the instructions.",
    "Forty metres of bunting and the committee that deploys it.",
    "A retired harbourmaster, on loan, with strong opinions and a thermos.",
    "Rain, in quantity, and the raincoats to shrug at it.",
    "A quiet room with a view of water, available Tuesdays.",
)


class PublishingGame:
    """A game with a desk attached, publishing into a temporary directory."""

    def __init__(self, tmp, **kwargs):
        self.tmp = tmp
        self.game = new_game()
        self.desk = Facilitator.attach(
            self.game,
            editions_dir=os.path.join(tmp, "editions"),
            site_dir=os.path.join(tmp, "site"),
            root=tmp,
            **kwargs
        )
        self.offer_index = 0

    @property
    def editions_dir(self):
        return os.path.join(self.tmp, "editions")

    @property
    def public_root(self):
        return os.path.join(self.tmp, "site", "public")

    def written(self):
        return sorted(os.listdir(self.editions_dir))

    def play(self, rounds=None):
        """Play the game out -- exports, picks, and the clock. Nothing else."""
        played = 0
        while self.game.phase == "running" and played < (rounds or 40):
            for player_id in sorted(self.game.players):
                pick_first(self.game, player_id)
            self._export()
            advance(self.game)
            played += 1
        return self.game

    def _export(self):
        need = self.game.collecting_need()
        if need is None:
            return
        for player_id in sorted(self.game.players):
            if player_id == need.importing_player_id:
                continue
            if "export" in self.game.checkin_used(player_id):
                continue
            self.game.submit_export(player_id, OFFERS[self.offer_index % len(OFFERS)])
            self.offer_index += 1


class AutomaticPublicationTest(unittest.TestCase):
    """#26: one edition per completed round, produced by the round ending."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fixture = PublishingGame(self.tmp)

    def test_a_finished_round_publishes_itself_with_nobody_calling_a_renderer(self):
        self.fixture.play()
        game, desk = self.fixture.game, self.fixture.desk
        completed = game.completed_rounds()
        self.assertEqual([t.round for t in desk.transactions], completed)
        self.assertEqual(completed, sorted(game.rounds))
        for index in completed:
            self.assertIn("round-%02d.md" % index, self.fixture.written())

    def test_exactly_one_edition_per_completed_round_and_not_batched(self):
        # Checked after every single round window rather than at the end:
        # "not batched" is a statement about *when*, and a run that published
        # everything on the last day would pass an end-state check.
        seen = 0
        while self.fixture.game.phase == "running":
            self.fixture._export()
            advance(self.fixture.game)
            completed = self.fixture.game.completed_rounds()
            editions = [name for name in self.fixture.written()
                        if name.startswith("round-") and name.endswith(".md")]
            self.assertEqual(
                editions, ["round-%02d.md" % index for index in completed]
            )
            # The last clock tick completes two rounds -- the one that was
            # running and the one that ends the game -- and publishes both, one
            # edition each. Every other tick completes exactly one.
            self.assertIn(len(editions) - seen, (1, 2))
            seen = len(editions)

    def test_the_round_in_progress_has_no_edition_yet(self):
        self.fixture._export()
        advance(self.fixture.game)
        current = self.fixture.game.current_round
        self.assertNotIn("round-%02d.md" % current, self.fixture.written())
        self.assertEqual(self.fixture.desk.transactions[-1].round, current - 1)

    def test_publishing_round_five_does_not_reprint_round_one(self):
        """Spec #27: an archive, not an overwrite."""
        self.fixture._export()
        advance(self.fixture.game)
        first = os.path.join(self.fixture.editions_dir, "round-01.md")
        with open(first, encoding="utf-8") as fh:
            as_published = fh.read()
        self.fixture.play()
        with open(first, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), as_published)

    def test_the_site_carries_every_published_round_at_one_address(self):
        self.fixture.play()
        pages = os.listdir(self.fixture.public_root)
        for index in self.fixture.game.completed_rounds():
            self.assertTrue(
                any("%02d" % index in name and name.endswith(".html") for name in pages),
                "round %d is not reachable at the paper's address" % index,
            )
        self.assertIn("index.html", pages)
        self.assertIn("archive.html", pages)
        self.assertIn("robots.txt", pages)

    def test_the_last_round_publishes_the_final_edition_too(self):
        """Spec #31: the endgame lands with the last round, unasked, like the rest."""
        self.fixture.play()
        self.assertEqual(self.fixture.game.phase, "ended")
        self.assertIn("final.md", self.fixture.written())
        last = self.fixture.desk.transactions[-1]
        self.assertTrue(last.ended)
        self.assertTrue(last.published["final"])
        self.assertEqual(last.notice.kind, "final")

    def test_an_edition_that_would_leak_stops_the_game_rather_than_publishing(self):
        """The transaction is also the gate (spec #21, #28, #30)."""
        game = self.fixture.game
        need = game.collecting_need()
        exporter = next(
            pid for pid in sorted(game.players) if pid != need.importing_player_id
        )
        game.submit_export(exporter, "An offer signed, unwisely, by p2 of this parish.")
        # The offer reaches print in the edition for the round its need
        # resolves in, which is two rounds after this one -- so the refusal
        # lands mid-game, in the middle of a tick, and stops it.
        with self.assertRaises(RuleViolation):
            self.fixture.play()
        self.assertNotIn("final.md", self.fixture.written())
        self.assertLess(len(self.fixture.desk.transactions), len(game.rounds))

    def test_failed_completed_round_is_not_skipped_and_retries_before_advancing(self):
        """A publication failure leaves the round incomplete for the next tick."""
        game = new_game()
        calls = []

        def fail_once(_game, round_index):
            calls.append(round_index)
            if len(calls) == 1:
                raise RuleViolation("simulated publication failure")

        game.on_round_completed(fail_once)
        with self.assertRaises(RuleViolation):
            advance(game)
        self.assertEqual(game.current_round, 1)
        self.assertFalse(game.rounds[1].completed)
        self.assertEqual(calls, [1])

        # The same elapsed tick retries round 1; it may create round 2 only
        # after the formerly unpublished round's hook has succeeded.
        game.tick()
        self.assertEqual(calls, [1, 1])
        self.assertTrue(game.rounds[1].completed)
        self.assertEqual(game.current_round, 2)

    def test_failed_final_round_retries_without_opening_another_round(self):
        """The terminal publication remains reachable before ENDED is committed."""
        game = new_game()
        calls = []

        def fail_final_once(current, round_index):
            if current._game_is_over():
                calls.append(round_index)
                if len(calls) == 1:
                    raise RuleViolation("simulated final publication failure")

        game.on_round_completed(fail_final_once)
        with self.assertRaises(RuleViolation):
            play_out(game)
        final_round = game.current_round
        self.assertEqual(game.phase, "running")
        self.assertFalse(game.rounds[final_round].completed)
        self.assertEqual(calls, [final_round])

        # Both public retry paths complete the same final round.  Explicit
        # advancement must not create a fictional successor round.
        game.advance_round()
        self.assertEqual(calls, [final_round, final_round])
        self.assertTrue(game.rounds[final_round].completed)
        self.assertEqual(game.phase, "ended")
        self.assertEqual(game.ended_round, final_round)
        self.assertEqual(game.current_round, final_round)
        self.assertNotIn(final_round + 1, game.rounds)


class NoticeTest(unittest.TestCase):
    """#26's last clause: the group is told the edition is available."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fixture = PublishingGame(self.tmp)

    def test_every_published_round_produces_one_notice(self):
        self.fixture.play()
        desk = self.fixture.desk
        self.assertEqual(
            [notice.round for notice in desk.notices], self.fixture.game.completed_rounds()
        )

    def test_the_notice_carries_the_address_and_says_what_the_paper_leads_on(self):
        self.fixture._export()
        advance(self.fixture.game)
        notice = self.fixture.desk.notices[0]
        need = next(n for n in self.fixture.game.needs.values() if n.opened_round == 1)
        self.assertIn(self.fixture.desk.identity.url(), notice.text)
        self.assertIn(need.importing_city, notice.text)
        self.assertIn(need.rendered["title"], notice.text)

    def test_the_written_down_notice_withholds_the_address(self):
        """The address is the paper's only credential (spec #26)."""
        self.fixture.play()
        desk = self.fixture.desk
        site_id = desk.identity.site_id
        for notice in desk.notices:
            self.assertIn(site_id, notice.text)
            self.assertNotIn(site_id, json.dumps(notice.describe()))
        self.assertNotIn(site_id, json.dumps(desk.describe()))

    def test_a_notice_without_the_url_still_tells_the_group_it_is_out(self):
        config_off = self.fixture.game.config.overridden(
            facilitator__notice__include_url=False
        )
        game = new_game(config=config_off)
        desk = Facilitator.attach(
            game,
            editions_dir=os.path.join(self.tmp, "quiet-editions"),
            site_dir=os.path.join(self.tmp, "quiet-site"),
            root=self.tmp,
        )
        advance(game)
        notice = desk.notices[0]
        self.assertFalse(notice.carries_url)
        self.assertNotIn(desk.identity.site_id, notice.text)
        self.assertIn("usual address", notice.text)


class ForcedChooser(Chooser):
    """A chooser pinned to one frame index, so a sweep can reach them all."""

    def __init__(self, index, allow_pointed=True):
        super().__init__(allow_pointed=allow_pointed)
        self.index = index

    def pick(self, frames, key, where, offset=0):
        candidates = self.allowed(frames, where)
        return candidates[(self.index + offset) % len(candidates)]


class BulletinFramesTest(unittest.TestCase):
    """Every notice the paper could send has to render (spec #26).

    ``tests/test_frame_coverage.py`` sweeps the frames that reach the *page*
    the same way. A notice is the one piece of the paper's writing that is
    never printed in an edition, so the sweep there cannot see it, and a frame
    with a placeholder nobody fills would fail on whichever round it came up.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fixture = PublishingGame(self.tmp)
        self.fixture.play()

    def test_every_notice_frame_renders_for_a_round_and_for_the_last_one(self):
        desk = self.fixture.desk
        bulletin = desk.copy.bulletin()
        widest = max(len(bulletin[family]) for family in
                     ("round_notice", "final_notice", "opened_lede", "quiet_lede"))
        rounds = self.fixture.game.completed_rounds()
        for index in range(widest):
            desk.chooser = ForcedChooser(index, allow_pointed=desk.paper.tone.allow_pointed)
            for round_index in rounds:
                notice = desk.notify(round_index)
                self.assertTrue(notice.text.strip())
                self.assertNotIn("{", notice.text)

    def test_a_quiet_round_says_so_rather_than_leaving_a_gap(self):
        """The drain rounds at the end of a game open no notice at all."""
        desk = self.fixture.desk
        drained = [
            index for index in self.fixture.game.completed_rounds()
            if not any(e["op"] == "OPEN" and e["need"]
                       for e in self.fixture.game.rounds[index].events)
        ]
        self.assertTrue(drained, "this game has no drain round to check")
        notice = next(n for n in desk.notices if n.round == drained[0])
        self.assertTrue(notice.text.strip())


class TransactionPolicyTest(unittest.TestCase):
    """#26 is the requirement; config.json holds its parameters, not a switch."""

    def setUp(self):
        self.config = new_game(start=False).config

    def test_the_shipped_transaction_runs_all_four_steps_in_order(self):
        self.assertEqual(
            resolve_steps(self.config),
            ["render_edition", "publish_editions", "build_site", "notify_group"],
        )

    def test_a_config_that_drops_publication_is_refused(self):
        for dropped in ("render_edition", "publish_editions", "notify_group"):
            steps = [s for s in
                     ("render_edition", "publish_editions", "build_site", "notify_group")
                     if s != dropped]
            with self.assertRaises(ConfigError) as caught:
                resolve_steps(
                    self.config.overridden(facilitator__completed_round_transaction=steps)
                )
            self.assertIn("#26", str(caught.exception))

    def test_an_unknown_step_is_refused_rather_than_ignored(self):
        with self.assertRaises(ConfigError):
            resolve_steps(
                self.config.overridden(
                    facilitator__completed_round_transaction=["render_edition", "email_everyone"]
                )
            )

    def test_the_steps_run_in_the_declared_order_whatever_config_lists(self):
        reordered = self.config.overridden(
            facilitator__completed_round_transaction=[
                "notify_group", "publish_editions", "render_edition"
            ]
        )
        self.assertEqual(
            resolve_steps(reordered),
            ["render_edition", "publish_editions", "notify_group"],
        )


if __name__ == "__main__":
    unittest.main()
