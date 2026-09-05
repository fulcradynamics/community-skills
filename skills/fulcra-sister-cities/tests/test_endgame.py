"""The last edition: the crown, the twist article, and a portrait per city.

Spec #31 and #32. M7's "done when" is that a full simulated game reaches its end
condition and produces all three endgame artifacts, so most of this module runs
against :func:`newspaper.sample.sample_game` -- twelve real rounds, a ramp-up, an
even split, a signed offer and a mayor who stops answering -- rather than against
a fixture built to make the assertions easy.

The tests are grouped by what they are defending:

* :class:`EndgameReportTest` -- the facts, before anybody writes prose over them
* :class:`CrownTest` -- #31's first half, including the two ways a crown can be
  awarded without a figure to quote
* :class:`TwistArticleTest` -- #31's second half, and specifically that it is
  about this game rather than about trade in general
* :class:`CityPortraitTest` -- #32: a description *and* an image per city, both
  built from that city's own history, with unchosen offers as "excess"
* :class:`ExcessIsNeverAttributedTest` -- the collision between #32 and #21, in
  detail. This is the one to read first if the design looks odd.
* :class:`EndgameConfigTest` -- every switch in ``config.endgame`` doing what its
  note in config.json says it does
* :class:`EndgamePublicationTest` -- the last edition reaching the paper's one
  private URL with the archive intact (#26, #27 still hold on the last day)
"""

import unittest
import xml.etree.ElementTree as ET

from harness import LATECOMER, advance, make_config, new_game, pick_first

from engine import views
from engine.endgame import mayor_excess_dossier
from engine.errors import ConfigError, PhaseError
from newspaper import redact
from newspaper.copy import NewspaperCopy, counted
from newspaper.edition import Paper
from newspaper.endgame import EndgamePolicy, city_image_name, ordinal_word
from newspaper.render import to_markdown
from newspaper.sample import sample_game


#: Export texts for the games this module plays itself. ``harness`` writes
#: "export from p3", which is a player id, which the paper refuses to print
#: (spec #28) -- correctly, but it makes the harness unusable for building an
#: edition. These read like something a mayor would actually send, name no city
#: (so the reprint path is exercised rather than the withholding one), and are
#: all different, so no two offers collide by accident.
OFFERS = (
    "A lighthouse keeper's spare lamp, and the keeper, on a fortnight's notice.",
    "Three tonnes of extremely good gravel, graded twice.",
    "A choir that knows four hundred songs and will not take requests.",
    "The plans for a bridge that was never built, with the objections attached.",
    "A weekly market, transplantable, noise and arguments included.",
    "Eleven crates of seed potatoes and one very opinionated agronomist.",
    "A clock tower mechanism, dismantled, with most of the instructions.",
    "Two retired ferry captains who have not spoken since 1998.",
    "A recipe that takes nine hours and cannot be halved.",
    "Forty metres of bunting and the committee that deploys it.",
    "A public bath, portable, and a strong recommendation about the temperature.",
    "The last working printing press of its kind, and the ink to match.",
)


def play_cooperatively(game, limit=40):
    """Run a game to its end with everyone exporting and every importer picking.

    :func:`harness.play_out` with export text a newspaper is allowed to print.
    """
    index = 0
    rounds = 0
    while game.phase == "running" and rounds < limit:
        for player_id in sorted(game.players):
            pick_first(game, player_id)
        need = game.collecting_need()
        if need is not None:
            for player_id in sorted(game.players):
                if player_id == need.importing_player_id:
                    continue
                if "export" in game.checkin_used(player_id):
                    continue
                game.submit_export(player_id, OFFERS[index % len(OFFERS)])
                index += 1
        advance(game)
        rounds += 1
    return game


def all_strings(node):
    """Every string anywhere in a payload, keys included."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from all_strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from all_strings(value)


def department(edition, name):
    for entry in edition["departments"]:
        if entry["id"] == name:
            return entry
    return None


def prose_of(node):
    """The printed text of a department or edition, as one string."""
    return "\n".join(
        block.get("text", "") or " ".join(block.get("items", []) or ())
        for block in _blocks(node)
    )


def _blocks(node):
    if "blocks" in node:
        return node["blocks"]
    return [block for entry in node["departments"] for block in entry["blocks"]]


class EndgameFixture(unittest.TestCase):
    """The scripted twelve-round game, played once for the whole module."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls.paper = Paper(cls.game)
        cls.report = views.endgame_briefing(cls.game)
        cls.edition = cls.paper.final_edition()
        cls.cities = sorted(p.city for p in cls.game.players.values())


class EndgameReportTest(EndgameFixture):
    """The facts the last edition is written from (spec #31, #32)."""

    def test_the_sample_game_actually_reaches_its_end_condition(self):
        # M7's "done when" starts here: without this the rest of the module is
        # testing an endgame that no game ever arrives at.
        self.assertEqual(self.game.phase, "ended")
        self.assertIsNotNone(self.game.ended_round)
        self.assertEqual(self.report["ended_round"], self.game.ended_round)

    def test_a_live_game_has_no_endgame_report(self):
        live = play_cooperatively(new_game(), limit=3)
        self.assertEqual(live.phase, "running")
        with self.assertRaises(PhaseError):
            views.endgame_briefing(live)

    def test_every_city_gets_a_dossier(self):
        self.assertEqual(
            sorted(entry["city"] for entry in self.report["cities"]), self.cities
        )

    def test_the_world_totals_agree_with_the_cities(self):
        chosen = sum(
            len(record["chosen"])
            for entry in self.report["cities"]
            for record in entry["imports"]
        )
        declined = sum(
            len(record["declined"])
            for entry in self.report["cities"]
            for record in entry["imports"]
        )
        world = self.report["world"]
        self.assertEqual(world["offers_chosen"], chosen)
        self.assertEqual(world["offers_sent"], chosen + declined)
        # The world's excess is the whole unchosen pile, counted once and with
        # no city attached to any part of it (spec #21, #32).
        self.assertEqual(world["excess_total"], declined)

    def test_every_arrival_names_a_winner_and_only_a_winner(self):
        for arrival in self.report["arrivals"]:
            self.assertIn(arrival["from_city"], self.cities)
            self.assertIn(arrival["to_city"], self.cities)
            need = self.game.needs[arrival["need"]]
            winners = [
                s for s in self.game.submissions_for(need.need_key) if s.is_winner
            ]
            self.assertIn(arrival["export"], [s.text for s in winners])


class CrownTest(EndgameFixture):
    """Spec #31: crown the overall cumulative-profit winner."""

    def test_the_crown_goes_to_the_top_of_the_cumulative_leaderboard(self):
        board = self.game.leaderboard()
        top = board[0]["profit"]["exact"]
        expected = sorted(
            row["city"] for row in board if row["profit"]["exact"] == top
        )
        crowned = sorted(row["city"] for row in self.report["crown"]["winners"])
        self.assertEqual(crowned, expected)

    def test_the_crowned_city_is_named_in_the_printed_article(self):
        crown = department(self.edition, "the_crown")
        self.assertIsNotNone(crown)
        text = prose_of(crown)
        for row in self.report["crown"]["winners"]:
            self.assertIn(row["city"], text)

    def test_the_crown_quotes_the_winning_total(self):
        crown = department(self.edition, "the_crown")
        self.assertIn(self.report["crown"]["profit"]["display"], prose_of(crown))

    def test_a_tie_at_the_top_is_crowned_as_a_tie(self):
        # Two cities on identical totals must both be crowned; a paper that
        # picked one of them would be inventing a tiebreak the spec has not got.
        board = [
            {"city": "Alpha", "mayor": "the Mayor of Alpha",
             "profit": {"exact": "7", "approx": 7.0, "display": "7"}, "rank": 1,
             "tied": True},
            {"city": "Beta", "mayor": "the Mayor of Beta",
             "profit": {"exact": "7", "approx": 7.0, "display": "7"}, "rank": 1,
             "tied": True},
            {"city": "Gamma", "mayor": "the Mayor of Gamma",
             "profit": {"exact": "2", "approx": 2.0, "display": "2"}, "rank": 3,
             "tied": False},
        ]
        from engine.endgame import _crown

        crown = _crown(board, 2, True, {"Alpha": 1, "Beta": 1}, set())
        self.assertTrue(crown["shared"])
        self.assertEqual(sorted(r["city"] for r in crown["winners"]), ["Alpha", "Beta"])
        self.assertEqual(crown["runner_up"]["city"], "Gamma")

    def test_the_winner_is_still_crowned_when_the_standings_are_private(self):
        # Spec #22 makes the running table an exposure decision; spec #31 makes
        # the crowning a requirement. A game that hid the table all along still
        # ends with a winner -- named, without a figure beside it.
        game = sample_game(
            config=make_config(economy__leaderboard_visible_in_newspaper=False)
        )
        report = views.endgame_briefing(game)
        self.assertFalse(report["crown"]["profit_visible"])
        self.assertNotIn("leaderboard", report)
        self.assertTrue(report["crown"]["winners"])
        for row in report["crown"]["winners"]:
            self.assertNotIn("profit", row)

        edition = Paper(game).final_edition()
        crown = department(edition, "the_crown")
        text = prose_of(crown)
        for row in report["crown"]["winners"]:
            self.assertIn(row["city"], text)
        # No table, and no figure smuggled into the prose.
        self.assertFalse([b for b in crown["blocks"] if b["kind"] == "table"])
        for row in game.leaderboard():
            self.assertNotIn(row["profit"]["display"], text)

    def test_ordinals_run_out_gracefully(self):
        self.assertEqual(ordinal_word(1), "first")
        self.assertEqual(ordinal_word(10), "tenth")
        self.assertEqual(ordinal_word(11), "11th")


class TwistArticleTest(EndgameFixture):
    """Spec #31's tongue-in-cheek piece on the problems the trade caused."""

    def setUp(self):
        self.twist = department(self.edition, "consequences")
        self.assertIsNotNone(self.twist)

    def test_it_is_built_from_arrivals_that_really_happened(self):
        # The judged criterion is "clearly informed by actual game history, not
        # generic filler", so the mechanical half of it is checked here: every
        # export the article quotes is an export somebody really sent and
        # somebody really chose.
        quoted = [b["text"] for b in self.twist["blocks"] if b["kind"] == "quote"]
        self.assertTrue(quoted)
        real = {arrival["export"] for arrival in self.report["arrivals"]}
        for text in quoted:
            self.assertIn(text, real)

    def test_it_credits_both_ends_of_each_arrival(self):
        text = prose_of(self.twist)
        for arrival in self.report["arrivals"][: len(
            [b for b in self.twist["blocks"] if b["kind"] == "quote"]
        )]:
            if arrival["export"] in text:
                self.assertIn(arrival["to_city"], text)

    def test_it_respects_the_configured_item_cap(self):
        cap = self.game.config.require_int("endgame.twist_article_items")
        quoted = [b for b in self.twist["blocks"] if b["kind"] == "quote"]
        self.assertLessEqual(len(quoted), cap)
        self.assertEqual(self.twist["provenance"]["cap"], cap)

    def test_it_spreads_itself_across_categories(self):
        # Four consequences drawn from four kinds of need is a better article
        # than four from one, and the seeded content has a line per category to
        # make that worth doing.
        quoted = [b["text"] for b in self.twist["blocks"] if b["kind"] == "quote"]
        categories = [
            arrival["category"]
            for arrival in self.report["arrivals"]
            if arrival["export"] in quoted
        ]
        self.assertEqual(len(set(categories)), len(categories))

    def test_it_reports_the_worlds_excess_without_attributing_any_of_it(self):
        self.assertFalse(self.twist["provenance"]["excess_attributed_to_any_city"])
        self.assertEqual(
            self.twist["provenance"]["world_excess"], self.report["world"]["excess_total"]
        )

    def test_it_follows_up_on_the_fallback_paths_the_game_actually_took(self):
        text = prose_of(self.twist)
        if self.report["world"]["ramp_ups"]:
            self.assertIn(self.report["world"]["ramp_ups"][0]["city"], text)
        if self.report["world"]["even_splits"]:
            self.assertIn(self.report["world"]["even_splits"][0]["city"], text)


class CityPortraitTest(EndgameFixture):
    """Spec #32: a description and an image per city, from its own history."""

    def setUp(self):
        self.excess = department(self.edition, "the_excess")
        self.assertIsNotNone(self.excess)

    def test_every_city_gets_a_heading_and_a_description(self):
        headings = [
            b["text"] for b in self.excess["blocks"] if b["kind"] == "heading"
        ]
        self.assertEqual(sorted(headings), self.cities)
        self.assertEqual(sorted(self.excess["provenance"]["cities"]), self.cities)

    def test_every_city_gets_an_image(self):
        figures = [b for b in self.excess["blocks"] if b["kind"] == "figure"]
        self.assertEqual(len(figures), len(self.cities))
        self.assertEqual(
            sorted(entry["city"] for entry in self.edition["city_images"]), self.cities
        )

    def test_every_portrait_is_well_formed_and_actually_drawn_from_the_city(self):
        for image in self.edition["city_images"]:
            ET.fromstring(image["content"])
            self.assertIn(image["city"], image["content"])
            self.assertIn(image["city"], image["alt"])
            # Spec #32 defers to #29's modality policy rather than having one of
            # its own, so a portrait records the same provenance an edition
            # image does.
            self.assertIn(image["provenance"]["modality"], ("raster", "svg_procedural"))
            self.assertEqual(image["kind"], "city_portrait")

    def test_portrait_filenames_are_flat_stable_and_ascii(self):
        # Valparaíso and Reykjavík are in the sample game precisely so this is
        # exercised: a filename is a URL, and an accented one is two URLs.
        for image in self.edition["city_images"]:
            self.assertEqual(image["filename"], city_image_name(image["city"]))
            self.assertTrue(image["filename"].isascii())
            self.assertNotIn("/", image["filename"])

    def test_a_description_is_built_from_that_citys_own_record(self):
        text = prose_of(self.excess)
        for entry in self.report["cities"]:
            city = entry["city"]
            self.assertIn(city, text)
            for record in entry["imports"]:
                # Its own notices, by title -- the clearest evidence that the
                # portrait is this city's rather than a template with a name in.
                self.assertIn(record["title"], text)

    def test_the_portrait_counts_the_excess_on_that_citys_own_quay(self):
        for image in self.edition["city_images"]:
            entry = next(
                e for e in self.report["cities"] if e["city"] == image["city"]
            )
            self.assertIn(
                str(entry["excess"]["declined_on_own_quay"]), image["content"] + image["alt"]
            )

    def test_a_citys_own_answers_can_appear_in_its_portrait(self):
        text = prose_of(self.excess)
        quoted = [
            answer["answer"]
            for entry in self.report["cities"]
            for answer in (entry.get("answers") or ())
            if answer["answer"] in text
        ]
        self.assertTrue(quoted, "no mayor's own words reached their city's portrait")

    def test_the_cap_on_quoted_answers_is_config_s(self):
        cap = self.game.config.require_int("endgame.quote_mayor_answers_per_city")
        for entry in self.report["cities"]:
            quoted = [
                answer for answer in (entry.get("answers") or ())
                if answer["answer"] in prose_of(self.excess)
            ]
            self.assertLessEqual(len(quoted), cap)


class ExcessIsNeverAttributedTest(EndgameFixture):
    """Where spec #32 meets spec #21, which is the whole design of this module.

    #32 wants each city's non-chosen exports treated as "excess" and #21 forbids
    ever saying who sent a non-chosen export. The last edition resolves that by
    publishing the pile from the *importing* end -- offers that arrived at a
    city's own quay and were declined, reprinted with no sender -- and by
    stating, rather than quietly omitting, that the sender's-end view exists and
    is not the paper's to print.
    """

    def test_a_dossier_never_pairs_a_declined_offer_with_a_sender(self):
        for entry in self.report["cities"]:
            for record in entry["imports"]:
                for item in record["declined"]:
                    # Absent, not None and not "withheld": a key that is present
                    # and empty is a key somebody later fills in.
                    self.assertEqual(list(item), ["export"])

    def test_the_published_report_says_the_senders_end_is_not_itemised(self):
        for entry in self.report["cities"]:
            sent = entry["excess"]["sent_and_not_chosen"]
            self.assertFalse(sent["itemised"])
            self.assertIn("#21", sent["spec"])

    def test_the_edition_states_the_omission_rather_than_hiding_it(self):
        text = prose_of(department(self.edition, "the_excess"))
        for city in self.cities:
            self.assertIn(city, text)
        # The shed with the door shut is in every portrait that uses excess at
        # all, and it carries no number -- a number is what would make the pile
        # attributable.
        for image in self.edition["city_images"]:
            self.assertIn("shed", image["alt"])

    def test_no_reprinted_offer_names_a_city(self):
        for item in self._reprinted():
            self.assertEqual(redact.cities_named_in(item, self.cities), [])

    def test_no_reprinted_offer_matches_one_the_paper_credits_by_name(self):
        # The subtle half of #21, and the one a reader could actually exploit:
        # the same words can win one notice and lose another, so a sentence
        # quoted under "Valparaíso wrote that" in the twist article must not
        # reappear as an unattributed declined offer in the portraits.
        attributed = redact.attributed_export_texts(self.game)
        self.assertTrue(attributed)
        for item in self._reprinted():
            self.assertNotIn(redact.comparable_export(item), attributed)

    def test_the_audit_catches_a_reprint_that_matches_an_attributed_offer(self):
        # The filter above is the rule; this is the tripwire under it, so a
        # department added by a later milestone cannot reintroduce the leak by
        # forgetting to pass the set.
        winner = next(
            s.text
            for need in self.game.needs.values()
            for s in self.game.submissions_for(need.need_key)
            if s.is_winner
        )
        forged = {
            "round": self.edition["round"],
            "endgame": True,
            "departments": [
                {
                    "id": "the_excess",
                    "title": "The Excess",
                    "blocks": [{"kind": "list", "role": redact.DECLINED_ROLE,
                                "items": [winner]}],
                }
            ],
        }
        with self.assertRaises(Exception) as caught:
            redact.assert_edition_is_redacted(self.game, forged)
        self.assertIn("attributed", str(caught.exception))

    def test_the_private_dossier_is_the_only_place_the_senders_end_exists(self):
        for player_id, player in self.game.players.items():
            dossier = mayor_excess_dossier(self.game, player_id)
            self.assertEqual(dossier["audience"], "facilitator")
            self.assertFalse(dossier["publishable"])
            self.assertEqual(dossier["city"], player.city)
            for entry in dossier["excess"]:
                self.assertFalse(entry["chosen"])

    def test_the_private_dossier_is_not_written_to_disk_by_default(self):
        # config.endgame.write_private_excess_dossiers is off, and the reason is
        # in its note: a dossier names which unchosen offers a city *sent*, and
        # writing that into a repository anybody can read publishes exactly what
        # spec #21 forbids.
        self.assertFalse(
            self.game.config.require_bool("endgame.write_private_excess_dossiers")
        )
        self.assertFalse(EndgamePolicy(self.game.config).write_dossiers)

    def test_no_handle_or_player_id_reaches_the_last_edition(self):
        rendered = [to_markdown(self.edition)]
        rendered.extend(image["content"] for image in self.edition["city_images"])
        rendered.append(self.edition["image"]["content"])
        self.assertEqual(redact.find_printed_identities(self.game, rendered), {})

    def _reprinted(self):
        return [
            item
            for block in _blocks(self.edition)
            if block.get("role") == redact.DECLINED_ROLE
            for item in block["items"]
        ]


class EndgameConfigTest(unittest.TestCase):
    """Every switch in ``config.endgame`` does what its note says it does."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()

    def _edition(self, **overrides):
        game = sample_game(config=make_config(**overrides))
        return Paper(game).final_edition()

    def test_all_three_articles_off_means_no_final_edition_at_all(self):
        # Not an empty edition with a masthead on it: an edition that says
        # nothing is worse than the absence it stands in for.
        edition = self._edition(
            endgame__crown_cumulative_profit_winner=False,
            endgame__publish_twist_article=False,
            endgame__generate_per_city_description_and_image=False,
        )
        self.assertIsNone(edition)

    def test_each_article_can_be_switched_off_on_its_own(self):
        for key, dept in (
            ("endgame__crown_cumulative_profit_winner", "the_crown"),
            ("endgame__publish_twist_article", "consequences"),
            ("endgame__generate_per_city_description_and_image", "the_excess"),
        ):
            edition = self._edition(**{key: False})
            self.assertIsNone(department(edition, dept), dept)
            self.assertTrue(edition["departments"], "the other articles still print")

    def test_switching_portraits_off_also_stops_the_images(self):
        edition = self._edition(endgame__generate_per_city_description_and_image=False)
        self.assertEqual(edition["city_images"], [])

    def test_excess_material_can_be_withheld_from_the_portraits(self):
        edition = self._edition(endgame__per_city_excess_uses_non_chosen_exports=False)
        excess = department(edition, "the_excess")
        self.assertFalse(
            [b for b in excess["blocks"] if b.get("role") == redact.DECLINED_ROLE]
        )
        for image in edition["city_images"]:
            self.assertNotIn("shed", image["alt"])

    def test_the_reprint_cap_is_obeyed(self):
        edition = self._edition(endgame__max_excess_offers_printed_per_city=0)
        blocks = [
            b for b in _blocks(edition) if b.get("role") == redact.DECLINED_ROLE
        ]
        self.assertEqual(blocks, [])

    def test_the_twist_cap_is_obeyed(self):
        edition = self._edition(endgame__twist_article_items=1)
        twist = department(edition, "consequences")
        self.assertEqual(
            len([b for b in twist["blocks"] if b["kind"] == "quote"]), 1
        )

    def test_the_portrait_canvas_comes_from_config(self):
        edition = self._edition(
            endgame__city_image__width=640, endgame__city_image__height=400
        )
        for image in edition["city_images"]:
            self.assertIn('width="640"', image["content"])
            self.assertIn('height="400"', image["content"])

    def test_answers_stay_out_of_the_portraits_when_the_policy_says_so(self):
        game = sample_game(
            config=make_config(
                facilitator_questions__answers_shared_in_newspaper=False
            )
        )
        report = views.endgame_briefing(game)
        for entry in report["cities"]:
            self.assertNotIn("answers", entry)
        text = prose_of(Paper(game).final_edition())
        for index in game.rounds:
            for answer in game.answers_by_city(index).values():
                self.assertNotIn(answer, text)

    def test_a_nonsense_endgame_setting_refuses_to_start_a_game(self):
        # Validated when the Paper is built rather than on the last day: a game
        # whose endgame settings are malformed should refuse to start, not
        # refuse to finish.
        for overrides in (
            {"endgame__twist_article_items": -1},
            {"endgame__max_excess_offers_printed_per_city": -2},
            {"endgame__city_image__width": 0},
        ):
            with self.assertRaises(ConfigError):
                Paper(new_game(config=make_config(**overrides)))

    def test_the_endgame_policy_is_recorded_in_the_edition(self):
        edition = Paper(self.game).final_edition()
        recorded = edition["provenance"]["endgame_policy"]
        for key in (
            "crown_cumulative_profit_winner", "publish_twist_article",
            "generate_per_city_description_and_image",
            "per_city_excess_uses_non_chosen_exports",
        ):
            self.assertEqual(recorded[key], self.game.config.require_bool("endgame.%s" % key))


class EndgamePublicationTest(EndgameFixture):
    """The last edition reaches the paper's one URL and joins the archive."""

    def test_the_archive_carries_the_final_edition_beside_the_rounds(self):
        archive = self.paper.archive()
        self.assertTrue(archive["ended"])
        self.assertIsNotNone(archive["final"])
        # Spec #26 is "one edition per completed round", so the final edition is
        # carried beside `editions` rather than inside it -- a list with two
        # entries for the last round would break that rule to make room for
        # something that is not a round edition.
        rounds = [edition["round"] for edition in archive["editions"]]
        self.assertEqual(len(rounds), len(set(rounds)))

    def test_a_running_game_has_no_final_edition_in_its_archive(self):
        live = play_cooperatively(new_game(), limit=3)
        archive = Paper(live).archive()
        self.assertIsNone(archive["final"])
        self.assertFalse(archive["ended"])

    def test_the_final_edition_has_its_own_permanent_name(self):
        from hosting import page

        self.assertEqual(page.page_name_for(self.edition), page.FINAL_PAGE_NAME)
        # It shares the last round's number, so a shared name would be one
        # document overwriting the other -- exactly what spec #27 forbids.
        self.assertNotEqual(
            page.page_name_for(self.edition),
            page.edition_page_name(self.edition["round"]),
        )

    def test_the_last_edition_reads_as_a_last_edition(self):
        markdown = to_markdown(self.edition)
        self.assertIn("FINAL EDITION", markdown)
        self.assertIn("## The Crown", markdown)
        self.assertIn("## Consequences", markdown)
        self.assertIn("## The Excess", markdown)
        # No deadline: there is no notice open and no window closing.
        self.assertNotIn("Offers for the current notice close", markdown)

    def test_the_masthead_ships_the_final_editions_own_lines(self):
        masthead = NewspaperCopy.load(self.game.config).masthead(self.game.config)
        for field in ("final_edition_line", "final_standing_line", "final_foot"):
            self.assertTrue(masthead[field])

    def test_the_finale_image_is_well_formed_and_drawn_from_the_finished_game(self):
        image = self.edition["image"]
        ET.fromstring(image["content"])
        self.assertEqual(image["kind"], "endgame_finale")
        for row in self.report["crown"]["winners"]:
            self.assertIn(row["city"], image["content"])


class EndgameCountingTest(unittest.TestCase):
    """The small helper that keeps the last edition's arithmetic readable."""

    def test_a_count_of_one_reads_as_one(self):
        self.assertEqual(counted(1, "offer"), "one offer")
        self.assertEqual(counted(3, "offer"), "three offers")
        self.assertEqual(counted(0, "offer"), "no offers")

    def test_it_takes_an_irregular_plural(self):
        self.assertEqual(counted(2, "city", "cities"), "two cities")


class ShortGameEndgameTest(unittest.TestCase):
    """A game that ends without the sample's convenient shape still publishes.

    The endgame must not depend on there having been a ramp-up, an even split, a
    signed offer or a single answered question -- a three-player game where
    everybody cooperates is a legitimate way to finish, and it exercises the
    "nothing to report" branch of every frame family.
    """

    @classmethod
    def setUpClass(cls):
        cls.game = play_cooperatively(new_game())
        cls.edition = Paper(cls.game).final_edition()

    def test_it_ends(self):
        self.assertEqual(self.game.phase, "ended")

    def test_it_publishes_all_three_articles(self):
        self.assertEqual(
            [entry["id"] for entry in self.edition["departments"]],
            ["the_crown", "consequences", "the_excess"],
        )

    def test_it_draws_a_portrait_for_every_city(self):
        self.assertEqual(
            sorted(image["city"] for image in self.edition["city_images"]),
            sorted(p.city for p in self.game.players.values()),
        )

    def test_it_survives_the_redaction_and_tone_gates(self):
        # final_edition() already ran both; this asserts the edition it returned
        # is the checked one rather than a payload that skipped them.
        self.assertTrue(
            redact.assert_edition_is_redacted(
                self.game, self.edition, rendered=[to_markdown(self.edition)]
            )
        )


class NoExportsEndgameTest(unittest.TestCase):
    """A game where nobody ever exports still crowns somebody (spec #17, #31).

    Every notice ramps up its own industry, every city is paid its roll, and the
    world's excess is zero. The last edition has to cope with a game in which
    nothing was ever chosen -- which is the degenerate case that would otherwise
    only be found on the night.
    """

    @classmethod
    def setUpClass(cls):
        game = new_game()
        rounds = 0
        while game.phase == "running" and rounds < 40:
            advance(game)
            rounds += 1
        cls.game = game
        cls.edition = Paper(game).final_edition()

    def test_the_game_ended_with_every_notice_ramped_up(self):
        self.assertEqual(self.game.phase, "ended")
        report = views.endgame_briefing(self.game)
        self.assertEqual(report["world"]["offers_sent"], 0)
        self.assertEqual(report["world"]["excess_total"], 0)
        self.assertTrue(report["world"]["ramp_ups"])

    def test_a_crown_is_still_awarded(self):
        crown = department(self.edition, "the_crown")
        self.assertIsNotNone(crown)
        self.assertTrue(prose_of(crown).strip())

    def test_the_twist_article_admits_there_was_no_surplus(self):
        twist = department(self.edition, "consequences")
        self.assertFalse([b for b in twist["blocks"] if b["kind"] == "quote"])
        self.assertTrue(prose_of(twist).strip())

    def test_every_city_is_still_drawn(self):
        self.assertEqual(
            sorted(image["city"] for image in self.edition["city_images"]),
            sorted(p.city for p in self.game.players.values()),
        )


class LateJoinerEndgameTest(unittest.TestCase):
    """A city that joined late is described by the year it actually had (#5, #32)."""

    @classmethod
    def setUpClass(cls):
        game = new_game()
        play_cooperatively(game, limit=2)
        game.register_player(*LATECOMER)
        play_cooperatively(game)
        cls.game = game
        cls.edition = Paper(game).final_edition()

    def test_the_latecomer_gets_a_portrait_like_everybody_else(self):
        cities = sorted(p.city for p in self.game.players.values())
        self.assertEqual(
            sorted(image["city"] for image in self.edition["city_images"]), cities
        )

    def test_the_portrait_reflects_the_turns_it_actually_got(self):
        report = views.endgame_briefing(self.game)
        for entry in report["cities"]:
            self.assertEqual(len(entry["imports"]), entry["import_turns_served"])


if __name__ == "__main__":
    unittest.main()
