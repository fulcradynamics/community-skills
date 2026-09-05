"""M10: what a reader actually gets when they open the paper (spec #30a).

Spec #26 and #27 are about the *address*: one URL, not discoverable, every
edition still there. They are satisfied by a shelf of files, and M6 proved that.
Spec #30a is about the *reading*, and it asks for two things a shelf of files
does not give you:

* the stable URL **opens the newest available edition**, rather than a contents
  page a reader has to shop in before they can read anything;
* every edition has **clear navigation** to the latest issue, the archive and
  its neighbours -- so a reader who arrives at round 3 from a two-week-old link
  can get to today's paper without editing a URL.

Both are mechanical, and this module checks them mechanically: the front page's
issue is compared against that issue's own permanent page, every issue's links
are enumerated, and the whole thing is fetched over real HTTP so that "the file
says so" and "the address answers with it" stay different claims.

The third part of #30a -- that the rendered pages read as a newspaper rather
than as a plain document -- is a judgement, and the Evaluator's. What is checked
here is the structure that judgement needs to be *possible*: that the markup
carries an editorial hierarchy at all (a masthead, a lead department, columns,
department treatment), that the stylesheet published beside it is the one that
lays that out, and that each issue still carries a picture drawn from its own
round. A layout cannot be judged good; it can be judged, and a page with no
structure in it could only be judged plain.
"""

import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from harness import advance, make_config, new_game, pick_first
from newspaper.edition import Paper
from newspaper.sample import sample_game

import hosting
from hosting import build, identity as identity_module, page

FAKE_ID = "abcdefghijklmnopqrstuvwxyz"


def fake_identity(config=None):
    config = config or make_config()
    return identity_module.SiteIdentity(
        FAKE_ID, "test", None,
        config.require_str("hosting.scheme"),
        config.require_str("hosting.base_domain"),
    )


def article_of(html):
    """The issue itself, without the chrome around it.

    The front page and an issue's permanent page carry the same edition and
    different navigation -- that is the point of there being two -- so what has
    to match between them is this.
    """
    marker = '<article class="edition">'
    start = html.index(marker)
    return html[start:html.index("</article>", start)]


def links_in(nav_html):
    """``[(kind, href)]`` for one rendered ``<nav>``."""
    return re.findall(r'<a class="nav-([a-z]+)" href="([^"]+)"', nav_html)


def navs_of(html):
    """Every navigation strip on a page, head and foot, as link lists."""
    return [
        links_in(match)
        for match in re.findall(r'<nav class="issue-nav[^>]*>.*?</nav>', html, re.DOTALL)
    ]


class BuiltSite:
    """One built site in a temporary directory, read back as text."""

    def __init__(self, game=None, config=None):
        self.game = game if game is not None else sample_game(config=config)
        self._tmp = tempfile.TemporaryDirectory()
        self.record = hosting.build_site(
            self.game, out_dir=self._tmp.name, identity=fake_identity(self.game.config),
        )
        self.public = self.record["public_root"]

    def cleanup(self):
        self._tmp.cleanup()

    def read(self, name):
        with open(os.path.join(self.public, name), encoding="utf-8") as fh:
            return fh.read()

    def names(self):
        return sorted(os.listdir(self.public))

    def issue_names(self):
        """Every issue's own permanent page (spec #27), oldest first."""
        rounds = [page.edition_page_name(index) for index in sorted(self.game.rounds)]
        return [name for name in rounds if name in self.names()] + (
            [page.FINAL_PAGE_NAME] if page.FINAL_PAGE_NAME in self.names() else []
        )

    def newest_name(self):
        if page.FINAL_PAGE_NAME in self.names():
            return page.FINAL_PAGE_NAME
        return page.edition_page_name(max(self.record["rounds"]))


class FrontDoorTest(unittest.TestCase):
    """The stable URL opens the newest available edition (spec #30a)."""

    @classmethod
    def setUpClass(cls):
        cls.site = BuiltSite()

    @classmethod
    def tearDownClass(cls):
        cls.site.cleanup()

    def test_the_front_page_carries_the_newest_edition_itself(self):
        front = self.site.read(page.FRONT_PAGE_NAME)
        newest = self.site.read(self.site.newest_name())
        self.assertEqual(
            article_of(front), article_of(newest),
            "the paper's own address does not open the newest issue",
        )

    def test_the_newest_edition_is_the_final_one_once_the_game_has_ended(self):
        """The last edition is the newest available edition (spec #31, #30a)."""
        self.assertEqual(self.site.game.phase, "ended")
        self.assertEqual(self.site.newest_name(), page.FINAL_PAGE_NAME)
        final = Paper(self.site.game).final_edition()
        self.assertTrue(final["endgame"])
        front = self.site.read(page.FRONT_PAGE_NAME)
        for department in final["departments"]:
            self.assertIn(department["title"], front)

    def test_the_front_page_links_the_issue_it_is_carrying_at_its_own_name(self):
        """A reader who wants *this* issue rather than *the current* one."""
        front = self.site.read(page.FRONT_PAGE_NAME)
        kinds = dict(navs_of(front)[0])
        self.assertEqual(kinds["permalink"], self.site.newest_name())
        self.assertNotIn(
            "latest", kinds, "the front page links itself as the latest edition",
        )

    def test_the_front_page_says_it_is_the_current_issue(self):
        front = self.site.read(page.FRONT_PAGE_NAME)
        self.assertIn('class="front-flag"', front)
        self.assertNotIn('class="front-flag"', self.site.read(self.site.newest_name()))

    def test_the_front_page_does_not_replace_any_permanent_page(self):
        """Spec #27's promise, which #30a's front door must not spend."""
        for name in self.site.issue_names():
            self.assertIn(name, self.site.names())
        self.assertIn(page.FRONT_PAGE_NAME, self.site.names())
        self.assertIn(page.ARCHIVE_PAGE_NAME, self.site.names())

    def test_the_front_page_moves_on_and_the_back_issues_do_not(self):
        """Two builds of a growing game: only the front door changes hands."""
        offers = (
            "A brass band, briefly, and the sheet music for one more.",
            "Two hundred metres of very good rope and somebody who can splice it.",
            "Rain, in quantity, and the infrastructure to shrug at it.",
            "A quiet room with a view of water, available Tuesdays.",
        )

        def game_after(rounds):
            game = new_game(seed=11)
            for _ in range(rounds):
                if game.phase != "running":
                    break
                for player_id in sorted(game.players):
                    pick_first(game, player_id)
                need = game.collecting_need()
                if need is not None:
                    for index, player_id in enumerate(sorted(game.players)):
                        if player_id == need.importing_player_id:
                            continue
                        if "export" in game.checkin_used(player_id):
                            continue
                        game.submit_export(
                            player_id, offers[(index + game.current_round) % len(offers)]
                        )
                advance(game)
            return game

        with tempfile.TemporaryDirectory() as tmp:
            early = hosting.build_site(
                game_after(3), out_dir=tmp, identity=fake_identity(),
            )
            with open(os.path.join(early["public_root"], "index.html"), encoding="utf-8") as fh:
                first_front = fh.read()
            with open(os.path.join(early["public_root"], "round-01.html"), encoding="utf-8") as fh:
                round_one = fh.read()
            early_newest = max(early["rounds"])

            later = hosting.build_site(
                game_after(6), out_dir=tmp, identity=fake_identity(),
            )
            with open(os.path.join(later["public_root"], "index.html"), encoding="utf-8") as fh:
                second_front = fh.read()
            with open(os.path.join(later["public_root"], "round-01.html"), encoding="utf-8") as fh:
                round_one_again = fh.read()
            later_newest = max(later["rounds"])

        self.assertGreater(later_newest, early_newest)
        self.assertIn("No. %d" % early_newest, first_front)
        self.assertIn("No. %d" % later_newest, second_front)
        self.assertEqual(
            article_of(round_one), article_of(round_one_again),
            "round one's issue changed when a later round went to press",
        )

    def test_before_the_first_round_closes_the_address_still_answers(self):
        """No edition yet is a reason to print an empty shelf, not a 404."""
        game = new_game(seed=3)
        with tempfile.TemporaryDirectory() as tmp:
            record = hosting.build_site(game, out_dir=tmp, identity=fake_identity())
            with open(os.path.join(record["public_root"], "index.html"), encoding="utf-8") as fh:
                front = fh.read()
        self.assertEqual(record["rounds"], [])
        self.assertIn('class="empty"', front)
        self.assertNotIn('<article class="edition">', front)

    def test_a_build_asked_to_drop_the_front_page_is_refused(self):
        """The one category that is the URL rather than a thing served at it."""
        from engine.errors import ConfigError

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                hosting.build_site(
                    sample_game(config=make_config(
                        hosting__publish=["archive_index", "editions", "robots"],
                    )),
                    out_dir=tmp, identity=fake_identity(),
                )

    def test_the_front_page_is_audited_as_a_rendering_of_its_edition(self):
        """The most-read page on the site must not be the least-checked one."""
        game = self.site.game
        paper = Paper(game)
        archive = paper.archive()
        privacy = build.resolve_privacy(game.config)
        manifest, rendered, _ = build.build_manifest(
            archive, paper.copy, game.config, fake_identity(game.config), privacy,
        )
        front = manifest.get(page.FRONT_PAGE_NAME)
        self.assertIsNotNone(front)
        self.assertIn(front.content, rendered["final"])

    def test_the_whole_site_still_passes_the_publication_guard(self):
        """The new pages are published bytes like any other (spec #21, #26, #28)."""
        from hosting import guard

        game = self.site.game
        paper = Paper(game)
        archive = paper.archive()
        identity = fake_identity(game.config)
        privacy = build.resolve_privacy(game.config)
        manifest, rendered, curated = build.build_manifest(
            archive, paper.copy, game.config, identity, privacy,
        )
        audited = list(archive["editions"]) + [archive["final"]]
        self.assertTrue(guard.assert_publishable(
            game, manifest, audited, identity=identity,
            rendered_by_round=rendered, payloads=[curated],
        ))
        self.assertIn(page.FRONT_PAGE_NAME, manifest.paths())
        self.assertIn(page.ARCHIVE_PAGE_NAME, manifest.paths())

    def test_a_leak_on_the_front_page_is_refused_like_any_other(self):
        """The front page's bytes are scanned, not inherited as already-clean."""
        from hosting import guard

        game = self.site.game
        paper = Paper(game)
        archive = paper.archive()
        identity = fake_identity(game.config)
        privacy = build.resolve_privacy(game.config)
        manifest, rendered, curated = build.build_manifest(
            archive, paper.copy, game.config, identity, privacy,
        )
        front = manifest.get(page.FRONT_PAGE_NAME)
        handle = next(iter(game.players.values())).handle
        front.content = front.content + "\n<p>Tip from %s.</p>\n" % handle
        with self.assertRaises(guard.PublicationRefused):
            guard.assert_publishable(
                game, manifest, list(archive["editions"]) + [archive["final"]],
                identity=identity, rendered_by_round=rendered, payloads=[curated],
            )

    def test_the_curated_json_says_where_the_front_door_goes(self):
        import json

        payload = json.loads(self.site.read("archive.json"))
        self.assertEqual(payload["front_page"], page.FRONT_PAGE_NAME)
        self.assertEqual(payload["archive_page"], page.ARCHIVE_PAGE_NAME)
        self.assertEqual(payload["latest"], self.site.newest_name())


class NavigationTest(unittest.TestCase):
    """Latest, archive and adjacent issues, on every edition (spec #30a)."""

    @classmethod
    def setUpClass(cls):
        cls.site = BuiltSite()

    @classmethod
    def tearDownClass(cls):
        cls.site.cleanup()

    def test_every_issue_offers_the_latest_edition_and_the_shelf(self):
        for name in self.site.issue_names():
            kinds = dict(navs_of(self.site.read(name))[0])
            self.assertEqual(kinds.get("latest"), page.FRONT_PAGE_NAME, name)
            self.assertEqual(kinds.get("archive"), page.ARCHIVE_PAGE_NAME, name)

    def test_the_navigation_is_at_the_head_and_the_foot_of_every_page(self):
        """A reader who has finished an edition is at the bottom of it."""
        for name in [page.FRONT_PAGE_NAME, page.ARCHIVE_PAGE_NAME] + self.site.issue_names():
            html = self.site.read(name)
            strips = re.findall(r'<nav class="issue-nav ([a-z]+)"', html)
            self.assertEqual(strips, ["head", "foot"], name)

    def test_adjacent_issues_are_linked_and_the_ends_are_not_invented(self):
        rounds = sorted(self.site.game.rounds)
        for index, round_index in enumerate(rounds):
            kinds = dict(navs_of(self.site.read(page.edition_page_name(round_index)))[0])
            if index > 0:
                self.assertEqual(
                    kinds["previous"], page.edition_page_name(rounds[index - 1]), round_index
                )
            else:
                self.assertNotIn("previous", kinds)
            if index + 1 < len(rounds):
                self.assertEqual(
                    kinds["next"], page.edition_page_name(rounds[index + 1]), round_index
                )
            else:
                self.assertNotIn("next", kinds)

    def test_the_last_round_hands_the_reader_on_to_the_final_edition(self):
        last = page.edition_page_name(max(self.site.game.rounds))
        kinds = dict(navs_of(self.site.read(last))[0])
        self.assertEqual(kinds["endgame"], page.FINAL_PAGE_NAME)
        # And the final edition does not link itself as the endgame.
        final_kinds = dict(navs_of(self.site.read(page.FINAL_PAGE_NAME))[0])
        self.assertNotIn("endgame", final_kinds)
        self.assertEqual(
            final_kinds["previous"], page.edition_page_name(max(self.site.game.rounds)),
        )

    def test_the_shelf_lists_every_issue_with_its_own_writing(self):
        shelf = self.site.read(page.ARCHIVE_PAGE_NAME)
        for name in self.site.issue_names():
            self.assertIn('href="%s"' % name, shelf)
        self.assertEqual(
            shelf.count('class="issue-card'), len(self.site.issue_names()),
            "the shelf is not one card per issue",
        )
        # Each card carries a line from the issue it points at, so the shelf can
        # be read rather than merely counted.
        teaser = page.issue_teaser(Paper(self.site.game).edition(5))
        self.assertTrue(teaser)
        self.assertIn("<p class=\"teaser\">", shelf)

    def test_the_shelf_shows_each_issue_s_picture_and_marks_the_last_one(self):
        shelf = self.site.read(page.ARCHIVE_PAGE_NAME)
        for round_index in sorted(self.site.game.rounds):
            self.assertIn('<img src="round-%02d.svg"' % round_index, shelf)
        self.assertIn('class="issue-card final"', shelf)
        self.assertIn('href="%s"' % page.FRONT_PAGE_NAME, shelf)

    def test_a_teaser_is_never_a_cut_inline_mark(self):
        """The shelf reprints copy; copy carries ``**`` marks and is truncated."""
        shelf = self.site.read(page.ARCHIVE_PAGE_NAME)
        self.assertNotIn("**", shelf)
        long_line = "**PUBLIC NOTICE** " + "a very wordy standfirst " * 20
        teaser = page.issue_teaser(
            {"departments": [{"blocks": [{"kind": "standfirst", "text": long_line}]}]}
        )
        self.assertNotIn("*", teaser)
        self.assertTrue(teaser.endswith("…"))
        self.assertLessEqual(len(teaser), page.TEASER_LENGTH + 1)

    def test_a_nav_never_links_a_page_this_build_did_not_publish(self):
        """``hosting.publish`` can leave the shelf out; the nav then omits it."""
        game = sample_game(config=make_config(
            hosting__publish=["front_page", "editions", "final_edition", "robots"],
        ))
        with tempfile.TemporaryDirectory() as tmp:
            record = hosting.build_site(game, out_dir=tmp, identity=fake_identity(game.config))
            names = [entry["path"] for entry in record["files"]]
            with open(os.path.join(record["public_root"], "round-05.html"),
                      encoding="utf-8") as fh:
                html = fh.read()
        self.assertNotIn(page.ARCHIVE_PAGE_NAME, names)
        kinds = dict(navs_of(html)[0])
        self.assertNotIn("archive", kinds)
        self.assertEqual(kinds["latest"], page.FRONT_PAGE_NAME)

    def test_a_shelf_never_links_an_issue_this_build_did_not_publish(self):
        """The same rule the other way round: a listed issue with no page.

        An odd publish list, and the point is that it degrades to a readable
        shelf rather than to twelve links that 404 at a private address nobody
        can debug from the outside.
        """
        game = sample_game(config=make_config(
            hosting__publish=["front_page", "archive_index", "robots"],
        ))
        with tempfile.TemporaryDirectory() as tmp:
            record = hosting.build_site(game, out_dir=tmp, identity=fake_identity(game.config))
            served = {entry["path"] for entry in record["files"]}
            pages = {
                name: open(os.path.join(record["public_root"], name), encoding="utf-8").read()
                for name in served if name.endswith(".html")
            }
        self.assertEqual(served, {"index.html", "archive.html", "robots.txt"})
        # The shelf still lists every issue, by name and date, and links none of
        # them; the front door still carries the newest issue itself.
        self.assertIn('class="issue-card', pages["archive.html"])
        self.assertNotIn('class="issue"', pages["archive.html"])
        self.assertIn('<article class="edition">', pages["index.html"])
        for name, html in pages.items():
            for href in re.findall(r'(?:href|src)="([^"#]+)"', html):
                self.assertIn(href, served, "%s links %s, which is not published" % (name, href))


class NewspaperLayoutTest(unittest.TestCase):
    """The structure a judgement about layout needs in order to be possible."""

    @classmethod
    def setUpClass(cls):
        cls.site = BuiltSite()
        cls.edition = cls.site.read("round-05.html")

    @classmethod
    def tearDownClass(cls):
        cls.site.cleanup()

    def test_the_masthead_is_a_masthead(self):
        for marker in (
            '<header class="masthead">',
            '<h1 class="nameplate">',
            '<p class="motto">',
            '<p class="dateline">',
            '<div class="folio">',
        ):
            self.assertIn(marker, self.edition, marker)

    def test_the_issue_has_a_lead_department_and_a_page_grid(self):
        self.assertIn('<div class="pages">', self.edition)
        self.assertIn('<section class="department lead"', self.edition)
        # Exactly one lead: two would be two front pages.
        self.assertEqual(self.edition.count('class="department lead'), 1)
        self.assertGreater(self.edition.count('<section class="department'), 2)

    def test_the_lead_marks_its_opening_paragraph_for_the_drop_cap(self):
        lead = self.edition[self.edition.index('<section class="department lead'):]
        lead = lead[: lead.index("</section>")]
        self.assertIn('<p class="opener">', lead)
        self.assertEqual(lead.count('<p class="opener">'), 1)

    def test_a_department_declares_what_it_contains_so_it_can_be_laid_out(self):
        """Columns are for prose; a table split down the middle is unreadable."""
        self.assertIn("has-table", self.edition)
        ledger = self.edition[self.edition.index('id="the_ledger"'):]
        self.assertIn("<table>", ledger[: ledger.index("</section>")])
        final = self.site.read(page.FINAL_PAGE_NAME)
        self.assertIn("has-figures", final)

    def test_every_department_is_a_titled_section_with_its_own_anchor(self):
        sections = re.findall(
            r'<section class="([^"]+)" id="([^"]+)">\n<h2 class="dept-title">([^<]+)</h2>',
            self.edition,
        )
        self.assertGreaterEqual(len(sections), 3)
        for classes, ident, title in sections:
            self.assertIn("department", classes)
            self.assertTrue(ident.strip())
            self.assertTrue(title.strip())

    def test_the_issue_prints_its_own_contents(self):
        strip = re.search(r'<nav class="inside".*?</nav>', self.edition, re.DOTALL)
        self.assertIsNotNone(strip, "a multi-department issue printed no contents strip")
        for ident in re.findall(r'<section class="department[^"]*" id="([^"]+)"', self.edition):
            self.assertIn('href="#%s"' % ident, strip.group(0))

    def test_the_stylesheet_published_beside_it_is_the_one_that_lays_it_out(self):
        css = self.site.read("style.css")
        for rule in (
            ".nameplate", ".dept-title", ".pages", ".lead .opener::first-letter",
            "columns:", "grid-template-columns", ".issue-nav", ".issue-card",
            "@media print", "prefers-color-scheme: dark",
        ):
            self.assertIn(rule, css, rule)
        # Narrow first, wider by exception: the small-screen layout is the base
        # and the grid arrives in a min-width query.
        self.assertTrue(re.search(r"@media \(min-width: \d+rem\)", css))
        self.assertNotIn("max-width: 0", css)

    def test_the_stylesheet_reaches_no_other_origin(self):
        """A private address leaks through Referer (spec #26); checked in M6 too.

        Scanned with the comments removed, because the file's own comments
        explain the rule by naming the things it forbids -- and a header that
        says "no ``@import``" should not be what trips a check for ``@import``.
        """
        css = re.sub(r"/\*.*?\*/", "", self.site.read("style.css"), flags=re.DOTALL)
        for smell in ("@import", "//", "http:", "https:", "url(h"):
            self.assertNotIn(smell, css, smell)

    def test_every_issue_still_carries_its_own_picture(self):
        for round_index in sorted(self.site.game.rounds):
            html = self.site.read(page.edition_page_name(round_index))
            self.assertIn('<img src="round-%02d.svg"' % round_index, html)
            self.assertIn('<figure class="edition-image">', html)
            self.assertIn("<figcaption>", html)
        front = self.site.read(page.FRONT_PAGE_NAME)
        self.assertIn('<figure class="edition-image">', front)

    def test_each_picture_is_drawn_from_its_own_round(self):
        """Spec #29, as #30a's "materially informed by the edition" restates it."""
        cities = [player.city for player in self.site.game.players.values()]
        for round_index in sorted(self.site.game.rounds):
            svg = self.site.read("round-%02d.svg" % round_index)
            self.assertIn("<svg", svg)
            self.assertIn("Vol. I, No. %d" % round_index, svg)
            self.assertTrue(
                any(city[:6] in svg for city in cities),
                "round %d's picture names none of the cities in the game" % round_index,
            )
            # More than a placeholder: the harbour is built out of the round's
            # own facts, so it is made of many elements rather than a few.
            self.assertGreater(svg.count("<rect"), 12, round_index)
            self.assertGreater(len(svg), 4000, round_index)

    def test_the_last_edition_carries_a_portrait_of_every_city(self):
        """Spec #32, still true after the layout changed around it."""
        html = self.site.read(page.FINAL_PAGE_NAME)
        portraits = Paper(self.site.game).final_edition()["city_images"]
        self.assertEqual(
            {entry["city"] for entry in portraits},
            {player.city for player in self.site.game.players.values()},
        )
        for entry in portraits:
            self.assertIn(entry["filename"], self.site.names())
            self.assertIn('<img src="%s"' % entry["filename"], html)
        self.assertIn('<figure class="city-portrait">', html)


class ServedRoutingTest(unittest.TestCase):
    """Over real HTTP, because "the URL answers" is the requirement."""

    @classmethod
    def setUpClass(cls):
        cls.site = BuiltSite()
        cls.identity = fake_identity(cls.site.game.config)
        from hosting import serve

        cls.httpd, _ = serve.make_server(
            cls.site.game.config, cls.identity, site_dir=cls.site._tmp.name,
        )
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.httpd.server_address[0], cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls.site.cleanup()

    OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path):
        request = urllib.request.Request("http://%s:%d%s" % (self.host, self.port, path))
        try:
            response = self.OPENER.open(request, timeout=5)
        except urllib.error.HTTPError as error:  # pragma: no cover - a routing bug
            self.fail("%s answered %d" % (path, error.code))
        return response.read().decode("utf-8")

    def test_the_bare_address_answers_with_the_newest_edition(self):
        body = self.get("/%s/" % FAKE_ID)
        self.assertEqual(article_of(body), article_of(self.site.read(self.site.newest_name())))

    def test_the_address_without_a_trailing_slash_answers_the_same_way(self):
        self.assertEqual(self.get("/%s" % FAKE_ID), self.get("/%s/" % FAKE_ID))

    def test_the_shelf_and_every_permanent_issue_answer(self):
        self.assertIn(
            'class="issues"', self.get("/%s/%s" % (FAKE_ID, page.ARCHIVE_PAGE_NAME)),
        )
        for name in self.site.issue_names():
            self.assertIn('<article class="edition">', self.get("/%s/%s" % (FAKE_ID, name)))

    def test_every_link_on_every_page_resolves(self):
        """No dangling navigation: what a page links, the address serves."""
        served = set(self.site.names())
        for name in [page.FRONT_PAGE_NAME, page.ARCHIVE_PAGE_NAME] + self.site.issue_names():
            html = self.site.read(name)
            for href in re.findall(r'(?:href|src)="([^"#]+)"', html):
                self.assertIn(href, served, "%s links %s, which is not published" % (name, href))


if __name__ == "__main__":
    unittest.main()
