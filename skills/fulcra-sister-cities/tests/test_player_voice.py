"""Spec #30b: whose words the paper's editorial register grades.

Spec #15 makes an export free-form text a mayor types. Spec #30 makes the paper
funny, colourful, pointed and never mean, and ``newspaper.tone`` puts a
mechanical floor under the last of those: a register of words whose only job in
a sentence is to attack somebody, run over the finished edition, refusing to
publish one that trips it.

Those two met during M11's re-recording. A winning offer contained the word
"stupid", the paper reprints a winning offer verbatim, and the edition refused
to publish -- which in a live game means the round cannot complete, because one
mayor chose one adjective. Spec #30b settles it:

    A player's freeform export is player voice, not newspaper editorial voice.
    If its exact text would trip the editorial tone gate, publication still
    proceeds: do not reject, rewrite, redact, or halt the game because of it.
    Present it clearly as player-entered text.

So there are four things to prove, and they pull against each other, which is
why they are proved together:

* the edition **publishes**, and the offer is in it **byte for byte** -- not
  rewritten, not redacted, not paraphrased;
* the page says **whose words they are**, so the paper is not handed credit for
  a mayor's wording (and, for a declined offer, says plainly that it is not
  telling -- spec #21 outranks the attribution);
* the paper's **own copy is still gated**, in the same edition;
* **nothing but a player's own text** can claim the exemption, or #30b would be
  a hole in #30 rather than a boundary on it.
"""

import copy as copy_module
import re
import tempfile
import unittest

import harness  # noqa: F401  (path setup)
from harness import advance, make_config, new_game
from engine.errors import ConfigError, MissingConfigKey, RuleViolation
from hosting import page
from newspaper import voice
from newspaper.copy import NewspaperCopy
from newspaper.edition import Paper
from newspaper.publish import publish_game
from newspaper.render import to_markdown
from newspaper.sample import BLUNT_OFFER, sample_game
from newspaper.tone import TonePolicy

#: An offer a mayor might really write: pointed about a decision, warm about the
#: goods, and containing one word from the paper's register. Under the rule this
#: file tests, that is the mayor's word choice and not the paper's problem.
BLUNT = (
    "Two hundred tins of the stew our last council bought by the pallet, which "
    "was a stupid thing to buy and has turned out to be a fine thing to eat."
)

#: The register term inside it, so the assertions can say what they are looking
#: for rather than trusting that :data:`BLUNT` still trips anything.
BLUNT_TERM = "stupid"

#: The other offers on the ballot. Written out rather than taken from
#: ``harness.everyone_exports``, whose texts carry the sending player's id --
#: which the paper is right to refuse to print (spec #28) and which would fail
#: this file's editions for a reason that has nothing to do with #30b.
POLITE = (
    "A crate of jam, the recipe, and somebody who will not permit you to alter it.",
    "Four hundred metres of bunting in colours the hills chose for themselves.",
    "Wool socks in a dozen sizes, all of them slightly wrong, and warm regardless.",
    "Biscuits by the tin, packed the way our grandmothers insisted they be packed.",
)


def submit_the_rest(game, sender_of_blunt):
    """Everybody else's offer for the open need, in nobody's name but a city's."""
    need = game.collecting_need()
    submitted = []
    for index, player_id in enumerate(sorted(game.players)):
        if player_id in (sender_of_blunt, need.importing_player_id):
            continue
        if "export" in game.checkin_used(player_id):
            continue
        submitted.append(game.submit_export(player_id, POLITE[index % len(POLITE)]))
    return submitted


def game_with_a_blunt_offer(win=True, seed=3, text=BLUNT):
    """A game in which ``text`` is submitted, and wins if asked to.

    Returns ``(game, round_index)`` where ``round_index`` is the round whose
    edition reports the resolution -- the round *after* the window closed, since
    the importing mayor gets a full window to pick (spec #18).
    """
    game = new_game(seed=seed)
    need = game.collecting_need()
    sender = next(
        player_id for player_id in sorted(game.players)
        if player_id != need.importing_player_id
    )
    game.submit_export(sender, text)
    submit_the_rest(game, sender)
    advance(game)

    importer = need.importing_player_id
    slot = next(
        entry for entry in game.checkin(importer)["slots"]
        if entry and entry["kind"] == "import_pick"
    )
    ref = next(
        entry["ballot_ref"] for entry in slot["ballot"]
        if (entry["export"] == text) is win
    )
    game.pick_winner(importer, ref)
    # The resolution belongs to the round that completes after the pick, so the
    # edition that reports it is that round's (spec #9's lockstep).
    advance(game)
    return game, game.needs[need.need_key].resolved_round


def blocks_of(edition):
    for department in edition["departments"]:
        for block in department["blocks"]:
            yield block


def player_voice_blocks(edition):
    return [block for block in blocks_of(edition) if block.get("voice") == voice.PLAYER]


class AWinningOfferInTheMayorsOwnWordsTest(unittest.TestCase):
    """The case #30b was written for, end to end."""

    @classmethod
    def setUpClass(cls):
        cls.game, cls.round = game_with_a_blunt_offer()
        cls.paper = Paper(cls.game)
        cls.edition = cls.paper.edition(cls.round)
        cls.markdown = to_markdown(cls.edition)

    def test_the_edition_publishes_at_all(self):
        """Before #30b this raised, and the round could not complete."""
        self.assertEqual(self.edition["round"], self.round)
        self.assertTrue(self.edition["departments"])

    def test_the_offer_is_printed_exactly_as_it_was_written(self):
        quote = next(
            block for block in player_voice_blocks(self.edition)
            if block["kind"] == "quote"
        )
        self.assertEqual(quote["text"], BLUNT)
        self.assertIn(BLUNT, self.markdown)
        # Not rewritten, not starred out, not paraphrased around the word.
        self.assertIn(BLUNT_TERM, self.markdown)

    def test_the_register_really_would_have_stopped_this(self):
        """Anti-vacuity: the offer must contain something the register catches."""
        self.assertTrue(self.paper.tone.findings(BLUNT))
        with self.assertRaises(RuleViolation):
            self.paper.tone.check(BLUNT, where="a test")

    def test_the_quotation_is_cited_to_the_mayor_who_wrote_it(self):
        quote = next(
            block for block in player_voice_blocks(self.edition)
            if block["kind"] == "quote"
        )
        winner = self.edition_winner_city()
        self.assertIn(winner, quote["cite"])
        self.assertIn(quote["cite"], self.markdown)

    def test_the_page_sets_it_apart_from_the_papers_own_voice(self):
        html = page.block_to_html(
            next(
                block for block in player_voice_blocks(self.edition)
                if block["kind"] == "quote"
            )
        )
        self.assertIn('<figure class="%s">' % page.PLAYER_VOICE_CLASS, html)
        self.assertIn("<figcaption>", html)
        self.assertIn(BLUNT_TERM, html)

    def test_the_papers_own_copy_around_it_is_still_gated(self):
        """The exemption is for the mayor's sentence, not for the column."""
        edition = copy_module.deepcopy(self.edition)
        editorial = next(
            block for block in blocks_of(edition)
            if block["kind"] == "para" and block.get("voice") != voice.PLAYER
        )
        editorial["text"] = editorial["text"] + " The mayor is, frankly, incompetent."
        with self.assertRaises(RuleViolation) as caught:
            self.paper._check(edition)
        self.assertIn("#30", str(caught.exception))

    def test_a_matching_editorial_repetition_is_not_mistaken_for_the_quote(self):
        """Authorship is structural, not a global textual substitution."""
        edition = copy_module.deepcopy(self.edition)
        edition["departments"][0]["blocks"].append(
            {"kind": "para", "text": "The paper repeats editorially: " + BLUNT}
        )
        with self.assertRaises(RuleViolation) as caught:
            self.paper._check(edition)
        self.assertIn(BLUNT_TERM, str(caught.exception))

    def test_the_edition_still_passes_the_identity_audit(self):
        """Publishing a mayor's wording changes nothing about #21 and #28."""
        from newspaper import redact

        self.assertTrue(
            redact.assert_edition_is_redacted(
                self.game, self.edition, rendered=[self.markdown]
            )
        )

    def edition_winner_city(self):
        for department in self.edition["departments"]:
            city = department.get("provenance", {}).get("winner_city")
            if city:
                return city
        self.fail("this edition reports no winner")


class ADeclinedOfferInTheSameRegisterTest(unittest.TestCase):
    """#30b for a losing offer, where #21 takes the byline away."""

    @classmethod
    def setUpClass(cls):
        cls.game, cls.round = game_with_a_blunt_offer(win=False)
        cls.paper = Paper(cls.game)
        cls.edition = cls.paper.edition(cls.round)
        cls.markdown = to_markdown(cls.edition)

    def test_the_edition_publishes_and_reprints_it_as_written(self):
        reprints = [
            block for block in player_voice_blocks(self.edition)
            if block["kind"] == "list"
        ]
        self.assertTrue(reprints, "the declined offers were not reprinted at all")
        printed = [item for block in reprints for item in block["items"]]
        self.assertIn(BLUNT, printed)
        self.assertIn(BLUNT, self.markdown)

    def test_the_cite_declines_to_name_anybody(self):
        block = next(
            block for block in player_voice_blocks(self.edition)
            if block["kind"] == "list"
        )
        cities = [player.city for player in self.game.players.values()]
        for city in cities:
            self.assertNotIn(city, block["cite"])
        self.assertIn(block["cite"], self.markdown)

    def test_the_origin_is_still_withheld_everywhere(self):
        from newspaper import redact

        self.assertTrue(
            redact.assert_edition_is_redacted(
                self.game, self.edition, rendered=[self.markdown]
            )
        )


class TheSubmissionDoorDoesNotScreenWordingTest(unittest.TestCase):
    """#30b's "do not reject" clause, at the only door an offer comes through.

    The other way to satisfy an edition that will not print a word is to refuse
    the offer that contains it. #30b rules that out as plainly as it rules out
    the rewrite, so the engine's export door checks that an offer *says*
    something (spec #15) and nothing whatever about what.
    """

    def test_an_offer_in_the_papers_register_is_accepted_as_typed(self):
        game = new_game()
        need = game.collecting_need()
        sender = next(
            player_id for player_id in sorted(game.players)
            if player_id != need.importing_player_id
        )
        submission = game.submit_export(sender, BLUNT)
        self.assertEqual(submission.text, BLUNT)
        self.assertEqual(game.submissions[submission.submission_id].text, BLUNT)


class AnOfferAMayorPressedReturnInsideTest(unittest.TestCase):
    """The rendered form of a multi-line quotation is not the payload's string.

    Every line of a quotation is printed with ``> `` in front of it, so a
    two-line offer never appears in the rendered edition as the one string the
    payload holds. If the exemption matched only that string, a mayor who used a
    line break would be back outside #30b without anybody having decided so.
    """

    TWO_LINES = (
        "Two hundred tins of the stew our last council bought by the pallet.\n"
        "It was a stupid thing to buy and it has turned out to be a fine thing "
        "to eat."
    )

    def test_it_publishes_and_keeps_both_lines(self):
        game, index = game_with_a_blunt_offer(text=self.TWO_LINES)
        markdown = to_markdown(Paper(game).edition(index))
        for line in self.TWO_LINES.splitlines():
            self.assertIn(line, markdown)
        self.assertIn(BLUNT_TERM, markdown)


class OnlyAPlayersOwnWordsMayClaimTheExemptionTest(unittest.TestCase):
    """The boundary that keeps #30b from being a hole in #30."""

    @classmethod
    def setUpClass(cls):
        cls.game, cls.round = game_with_a_blunt_offer()
        cls.paper = Paper(cls.game)
        cls.edition = cls.paper.edition(cls.round)

    def test_a_department_cannot_launder_its_own_line_as_a_mayors(self):
        edition = copy_module.deepcopy(self.edition)
        edition["departments"][0]["blocks"].append(
            voice.quoted(
                "The Mayor of anywhere is, frankly, incompetent.",
                "the paper, pretending to quote somebody",
            )
        )
        with self.assertRaises(RuleViolation) as caught:
            self.paper._check(edition)
        self.assertIn("#30b", str(caught.exception))

    def test_an_undeclared_span_cannot_smuggle_a_line_past_the_register(self):
        edition = copy_module.deepcopy(self.edition)
        edition["departments"][0]["blocks"].append(
            voice.within(
                {"kind": "para", "text": "A pitiful showing, this paper thinks."},
                "A pitiful showing, this paper thinks.",
            )
        )
        with self.assertRaises(RuleViolation):
            self.paper._check(edition)

    def test_what_counts_as_a_players_own_words(self):
        """Exports and mayoral answers, as typed. Nothing else."""
        texts = voice.player_texts(self.game)
        from newspaper.redact import comparable_export

        for submission in self.game.submissions.values():
            self.assertIn(comparable_export(submission.text), texts)
        self.assertNotIn(comparable_export("a sentence nobody typed"), texts)


class MaskingTest(unittest.TestCase):
    """:func:`newspaper.voice.editorial_only`, which is #30b's mechanics."""

    def test_a_span_is_replaced_and_the_rest_is_left_alone(self):
        masked = voice.editorial_only("The paper said: %s Fine." % BLUNT, [BLUNT])
        self.assertNotIn(BLUNT_TERM, masked)
        self.assertIn("The paper said:", masked)
        self.assertIn("Fine.", masked)
        self.assertIn(voice.MASK, masked)

    def test_masking_one_quote_does_not_hide_the_papers_own_word(self):
        text = "%s The paper found the whole thing pathetic." % BLUNT
        masked = voice.editorial_only(text, [BLUNT])
        self.assertIn("pathetic", masked)

    def test_the_longest_span_is_masked_first(self):
        """A span inside another must not leave the shorter one's tail behind."""
        outer = "socks, a thousand pairs, all slightly wrong"
        inner = "a thousand pairs"
        masked = voice.editorial_only("Offered: %s." % outer, [inner, outer])
        self.assertEqual(masked, "Offered: %s." % voice.MASK)

    def test_an_empty_span_list_changes_nothing(self):
        self.assertEqual(voice.editorial_only("as it was", []), "as it was")

    def test_a_span_a_mayor_pressed_return_inside_is_still_masked(self):
        """The renderers put ``> `` in front of every line of a quotation."""
        span = "Two hundred tins.\nOne stupid decision behind them."
        rendered = "\n".join("> %s" % line for line in span.splitlines())
        masked = voice.editorial_only(rendered, [span])
        self.assertNotIn(BLUNT_TERM, masked)


class ScopeComesFromConfigTest(unittest.TestCase):
    """``newspaper.tone.forbidden_register_scope`` is read, obeyed and refused."""

    def setUp(self):
        self.config = make_config()
        self.copy = NewspaperCopy.load(self.config)

    def test_the_shipped_value_is_the_one_this_paper_implements(self):
        policy = TonePolicy(self.config, self.copy)
        self.assertEqual(policy.scope, "newspaper_voice")
        described = policy.describe()["forbidden_register_scope"]
        self.assertEqual(described["value"], "newspaper_voice")
        self.assertIn("#30b", policy.describe()["spec"])

    def test_a_scope_this_paper_does_not_implement_is_refused(self):
        config = make_config(newspaper__tone__forbidden_register_scope="everything")
        with self.assertRaises(ConfigError) as caught:
            TonePolicy(config, self.copy)
        self.assertIn("#30b", str(caught.exception))

    def test_there_is_no_inline_default_behind_it(self):
        from test_config_conformance import config_without

        stripped = config_without("newspaper.tone.forbidden_register_scope")
        with self.assertRaises(MissingConfigKey):
            TonePolicy(stripped, self.copy)


class TheSampleGamePublishesOneTest(unittest.TestCase):
    """The committed sample run carries the case, in bytes a reader can open.

    ``newspaper/sample.py`` already contains an offer that names its own city so
    the archive shows spec #21's withholding rule working. :data:`BLUNT_OFFER`
    is the same idea for #30b: an offer whose own wording the paper would never
    write, printed anyway, cited to the mayor who wrote it.
    """

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls.paper = Paper(cls.game)
        cls.editions = [cls.paper.edition(index) for index in sorted(cls.game.rounds)]

    def test_the_blunt_offer_won_and_was_printed_verbatim(self):
        text = BLUNT_OFFER[1]
        winners = [
            submission for submission in self.game.submissions.values()
            if submission.is_winner and submission.text == text
        ]
        self.assertEqual(len(winners), 1, "the sample's blunt offer did not win")
        printed = [
            edition for edition in self.editions
            if text in to_markdown(edition)
        ]
        self.assertTrue(printed, "the sample's blunt offer was never printed")
        self.assertTrue(self.paper.tone.findings(text))

    def test_it_is_cited_to_its_mayor_on_the_page(self):
        text = BLUNT_OFFER[1]
        city = self.game.players[BLUNT_OFFER[0]].city
        quotes = [
            block for edition in self.editions
            for block in player_voice_blocks(edition)
            if block.get("text") == text
        ]
        self.assertTrue(quotes)
        for block in quotes:
            self.assertIn(city, block["cite"])

    def test_the_published_edition_file_carries_it(self):
        """Not just the payload: the file a reader opens.

        Published into a temporary directory rather than read out of
        ``editions/``, because the committed run is regenerated by
        ``tests/test_publish.py`` and a test that read it would be asserting on
        whichever run happened to go first.
        """
        with tempfile.TemporaryDirectory() as out:
            manifest = publish_game(self.game, label="player-voice", out_dir=out)
            found = []
            for entry in manifest["editions"]:
                with open(entry["files"]["markdown"], encoding="utf-8") as fh:
                    if BLUNT_OFFER[1] in fh.read():
                        found.append(entry["round"])
        self.assertTrue(found, "no published edition prints the blunt offer")


class ThePublishedPageDistinguishesTheTwoVoicesTest(unittest.TestCase):
    """The whole page a reader opens, not a block rendered in isolation."""

    @classmethod
    def setUpClass(cls):
        from test_reading_experience import BuiltSite

        cls.site = BuiltSite()
        cls.cities = sorted(
            player.city for player in cls.site.game.players.values()
        )
        cls.html = next(
            html for html in (cls.site.read(name) for name in cls.site.issue_names())
            if BLUNT_OFFER[1] in html
        )

    @classmethod
    def tearDownClass(cls):
        cls.site.cleanup()

    def test_the_offer_is_on_the_page_word_for_word(self):
        self.assertIn(BLUNT_OFFER[1], self.html)
        self.assertIn(BLUNT_TERM, self.html)

    def test_it_is_set_in_a_cited_figure_of_its_own(self):
        self.assertIn('<figure class="%s">' % page.PLAYER_VOICE_CLASS, self.html)
        city = self.site.game.players[BLUNT_OFFER[0]].city
        self.assertIn("<figcaption>", self.html)
        self.assertIn(city, self.html)

    def test_the_stylesheet_has_something_to_say_about_that_class(self):
        """A class no stylesheet styles is a distinction only a grep can see."""
        self.assertIn(
            "figure.%s" % page.PLAYER_VOICE_CLASS, self.site.read("style.css")
        )

    def test_the_declined_reprints_on_that_page_are_cited_to_nobody(self):
        figures = re.findall(
            r'<figure class="%s">(.*?)</figure>' % page.PLAYER_VOICE_CLASS,
            self.html, re.DOTALL,
        )
        lists = [block for block in figures if "<ul>" in block]
        self.assertTrue(lists, "this page reprints no declined offers")
        for block in lists:
            caption = re.search(r"<figcaption>(.*?)</figcaption>", block, re.DOTALL)
            self.assertIsNotNone(caption)
            for city in self.cities:
                self.assertNotIn(city, caption.group(1))


class TheWholeSampleRunStillPublishesTest(unittest.TestCase):
    """Every edition, plus the last one, with #30b in force."""

    def test_nothing_in_the_run_refuses_to_publish(self):
        paper = Paper(sample_game())
        archive = paper.archive()
        self.assertTrue(archive["editions"])
        self.assertIsNotNone(archive["final"])

    def test_every_player_voice_block_carries_a_cite(self):
        paper = Paper(sample_game())
        archive = paper.archive()
        editions = list(archive["editions"]) + [archive["final"]]
        seen = 0
        for edition in editions:
            for block in player_voice_blocks(edition):
                self.assertTrue(block.get("cite"), block)
                seen += 1
        self.assertGreater(seen, 0)

    def test_the_final_edition_marks_its_quotations_too(self):
        paper = Paper(sample_game())
        final = paper.final_edition()
        quotes = [
            block for block in player_voice_blocks(final)
            if block["kind"] == "quote"
        ]
        self.assertTrue(quotes, "the twist article quotes nobody")


if __name__ == "__main__":
    unittest.main()
