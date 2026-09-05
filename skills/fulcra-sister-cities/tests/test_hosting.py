"""M6: the paper's address, its archive, and what may be published at it.

Spec #26 (one fixed, non-publicly-discoverable URL, reachable by every player)
and #27 (prior editions stay browsable at it). The milestone's "done when" has
three parts and so does this module:

* a rendered edition is **reachable at a stable URL** -- checked by starting the
  real server and fetching over real HTTP, because "the file is on disk" and
  "the URL answers" are different claims and only the second one is the
  requirement;
* the archive **exposes prior editions without overwriting them** -- checked by
  building a game twice, at different lengths, and asserting the first build's
  editions are still there, byte for byte, at the same names;
* **only curated files are published** -- checked from both ends: the public
  root must equal the manifest exactly, and the guard must actually refuse the
  things it claims to refuse.

Like :mod:`tests.test_publish`, one class here writes into the repository on
purpose: it regenerates the committed ``site/`` so that what is committed is
what the code produces, and drift shows up as a diff.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from harness import advance, make_config, new_game, pick_first
from engine.config import repo_root
from engine.errors import ConfigError
from newspaper.edition import Paper
from newspaper.sample import sample_game

import hosting
from hosting import build, guard, identity as identity_module, manifest as manifest_module, page, serve

FAKE_ID = "abcdefghijklmnopqrstuvwxyz"


def fake_identity(config=None, site_id=FAKE_ID):
    """A fixed address, so a test can assert on URLs without minting a secret."""
    config = config or make_config()
    return identity_module.SiteIdentity(
        site_id, "test", None,
        config.require_str("hosting.scheme"),
        config.require_str("hosting.base_domain"),
    )


def build_into(tmp, game=None, config=None, identity=None):
    game = game if game is not None else sample_game(config=config)
    return hosting.build_site(game, out_dir=tmp, identity=identity or fake_identity(game.config))


class SiteIdentityTest(unittest.TestCase):
    """The address is a credential, so it behaves like one."""

    def test_a_generated_id_is_a_legal_dns_label_with_real_entropy(self):
        config = make_config()
        for _ in range(20):
            site_id = identity_module.generate(config.require_int("hosting.site_id_bytes"))
            self.assertRegex(site_id, identity_module.DNS_LABEL)
            self.assertLessEqual(len(site_id), 63)
            # 16 bytes of base32 is 26 characters; anything much shorter would
            # mean the configured entropy never reached the label.
            self.assertGreaterEqual(len(site_id), 20)

    def test_two_generated_ids_differ(self):
        made = {identity_module.generate(16) for _ in range(50)}
        self.assertEqual(len(made), 50)

    def test_a_short_id_is_refused_rather_than_padded(self):
        with self.assertRaises(ConfigError):
            identity_module.generate(4)
        with self.assertRaises(ConfigError):
            identity_module.generate("16")

    def test_the_address_is_fixed_once_minted(self):
        """Spec #26's 'single fixed URL': round 12's link is round 1's link."""
        config = make_config()
        with tempfile.TemporaryDirectory() as root:
            first = identity_module.load_or_create(config, root=root, env={})
            second = identity_module.load_or_create(config, root=root, env={})
            third = identity_module.load_or_create(config, root=root, env={})
        self.assertEqual(first.site_id, second.site_id)
        self.assertEqual(second.site_id, third.site_id)
        self.assertEqual(first.source, "file (created)")
        self.assertEqual(second.source, "file")

    def test_the_stored_id_is_readable_only_by_its_owner(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as root:
            stored = identity_module.load_or_create(config, root=root, env={})
            mode = os.stat(stored.path).st_mode & 0o777
        self.assertEqual(mode, 0o600, "the site id must not be group- or world-readable")

    def test_an_injected_id_wins_and_writes_nothing_to_disk(self):
        config = make_config()
        variable = config.require_str("hosting.site_id_env_var")
        with tempfile.TemporaryDirectory() as root:
            injected = identity_module.load_or_create(
                config, root=root, env={variable: "injected-address"}
            )
            self.assertEqual(injected.site_id, "injected-address")
            self.assertEqual(injected.source, "env:%s" % variable)
            self.assertFalse(
                os.path.exists(identity_module.site_id_path(config, root=root)),
                "a deployment that injects its own secret must not get a copy on disk",
            )

    def test_an_illegal_injected_id_is_refused(self):
        config = make_config()
        variable = config.require_str("hosting.site_id_env_var")
        with self.assertRaises(ConfigError):
            identity_module.load_or_create(config, env={variable: "Not A Hostname"})

    def test_the_canonical_url_is_the_unguessable_subdomain(self):
        config = make_config()
        address = fake_identity(config)
        self.assertEqual(
            address.url(),
            "%s://%s.%s/" % (
                config.require_str("hosting.scheme"),
                FAKE_ID,
                config.require_str("hosting.base_domain"),
            ),
        )
        self.assertEqual(address.url("round-03.html"), address.url() + "round-03.html")

    def test_what_may_be_written_down_about_the_address_is_not_the_address(self):
        address = fake_identity()
        committed = json.dumps(address.describe())
        self.assertNotIn(FAKE_ID, committed)
        self.assertIn("address_withheld", committed)
        # Machine-local, so it stays out of the file that gets reviewed in a repo.
        self.assertNotIn(identity_module.fingerprint(FAKE_ID), committed)

        facilitators = json.dumps(address.describe(with_fingerprint=True))
        self.assertNotIn(FAKE_ID, facilitators)
        self.assertIn(identity_module.fingerprint(FAKE_ID), facilitators)

    def test_the_id_file_is_gitignored(self):
        """A committed address is a published address."""
        with open(os.path.join(repo_root(), ".gitignore"), encoding="utf-8") as fh:
            ignored = [line.strip() for line in fh]
        self.assertIn(identity_module.DEFAULT_SITE_ID_FILE, ignored)
        self.assertEqual(
            make_config().require_str("hosting.site_id_file"),
            identity_module.DEFAULT_SITE_ID_FILE,
            "config points the site id somewhere .gitignore does not cover",
        )

    def test_matching_an_id_does_not_leak_how_close_a_guess_was(self):
        address = fake_identity()
        self.assertTrue(address.matches(FAKE_ID))
        self.assertFalse(address.matches(FAKE_ID[:-1]))
        self.assertFalse(address.matches(None))


class BuildTest(unittest.TestCase):
    """One build of the sample game, in a temporary directory."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.record = build_into(cls._tmp.name, game=cls.game)
        cls.public = cls.record["public_root"]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def read(self, name):
        with open(os.path.join(self.public, name), encoding="utf-8") as fh:
            return fh.read()

    def test_every_edition_has_its_own_page_and_its_own_image(self):
        for round_index in sorted(self.game.rounds):
            self.assertTrue(os.path.exists(
                os.path.join(self.public, page.edition_page_name(round_index))
            ))
            self.assertTrue(os.path.exists(
                os.path.join(self.public, "round-%02d.svg" % round_index)
            ))
        self.assertEqual(self.record["rounds"], sorted(self.game.rounds))

    def test_the_archive_index_links_every_edition(self):
        shelf = self.read(page.ARCHIVE_PAGE_NAME)
        for round_index in sorted(self.game.rounds):
            self.assertIn('href="%s"' % page.edition_page_name(round_index), shelf)

    def test_the_index_order_follows_config(self):
        newest = self.read(page.ARCHIVE_PAGE_NAME)
        first_listed = newest.index('href="round-12.html"')
        last_listed = newest.index('href="round-01.html"')
        self.assertLess(first_listed, last_listed, "newest_first was configured")

        with tempfile.TemporaryDirectory() as tmp:
            oldest = build_into(
                tmp, config=make_config(hosting__archive_order="oldest_first"),
            )
            with open(os.path.join(oldest["public_root"], page.ARCHIVE_PAGE_NAME),
                      encoding="utf-8") as fh:
                text = fh.read()
        self.assertLess(text.index('href="round-01.html"'), text.index('href="round-12.html"'))

    def test_an_unknown_archive_order_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                build_into(tmp, config=make_config(hosting__archive_order="shuffled"))

    def test_every_page_carries_the_noindex_instruction(self):
        expected = self.game.config.require_str("hosting.privacy.meta_robots")
        for name in ("index.html", "archive.html", "round-01.html", "round-12.html"):
            self.assertIn('name="robots" content="%s"' % expected, self.read(name))

    def test_robots_txt_disallows_everything(self):
        robots = self.read("robots.txt")
        self.assertIn("User-agent: *", robots)
        self.assertIn("Disallow: /", robots)

    def test_editions_are_navigable_in_both_directions(self):
        middle = self.read("round-05.html")
        self.assertIn('href="round-04.html"', middle)
        self.assertIn('href="round-06.html"', middle)
        # The two fixed destinations spec #30a asks for on every edition: the
        # current issue at the paper's own address, and the shelf.
        self.assertIn('href="index.html"', middle)
        self.assertIn('href="archive.html"', middle)
        # The ends have no neighbour on one side, and say nothing rather than
        # linking to a page that is not there.
        self.assertNotIn('href="round-00.html"', self.read("round-01.html"))
        self.assertNotIn('href="round-13.html"', self.read("round-12.html"))

    def test_a_page_carries_the_edition_it_is_supposed_to_carry(self):
        page_five = self.read("round-05.html")
        self.assertIn("Vol. I, No. 5", page_five)
        self.assertIn('<h2 class="dept-title">Wanted</h2>', page_five)
        self.assertIn('<img src="round-05.svg"', page_five)

    def test_the_copy_s_inline_marks_are_obeyed_and_not_printed(self):
        """``**PUBLIC NOTICE**`` is a lede, not four asterisks."""
        for name in ("round-01.html", "round-05.html", "round-12.html"):
            text = self.read(name)
            self.assertNotIn("**", text, name)
        self.assertIn("<strong>PUBLIC NOTICE</strong>", self.read("round-05.html"))
        self.assertIn("<em>", self.read("round-05.html"))

    def test_an_export_can_never_put_markup_on_the_page(self):
        """Everything is escaped before the two inline marks are applied."""
        self.assertEqual(
            page.inline('<script>alert("x")</script> **bold**'),
            "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; <strong>bold</strong>",
        )
        self.assertEqual(page.inline("a * b * c"), "a * b * c")
        self.assertEqual(page.inline("2 * 3 = 6"), "2 * 3 = 6")

    def test_no_page_reaches_another_origin(self):
        """A private URL leaks through Referer the moment a page fetches anything."""
        for entry in self.record["files"]:
            text = self.read(entry["path"])
            for scheme in ('src="http', "src='http", 'href="http', "href='http", 'src="//'):
                self.assertNotIn(scheme, text, entry["path"])

    def test_the_curated_json_carries_the_editions_and_not_the_internals(self):
        payload = json.loads(self.read("archive.json"))
        self.assertEqual(len(payload["editions"]), 12)
        self.assertNotIn("phase", payload)
        self.assertNotIn("hosting", payload)
        for edition in payload["editions"]:
            self.assertNotIn("provenance", edition)
            self.assertEqual(edition["image"]["modality"], "svg_procedural")
            self.assertNotIn("content", edition["image"])

    def test_a_field_added_to_an_edition_is_not_published_by_accident(self):
        """The curated projection is an allowlist, which is the whole point of it."""
        edition = dict(
            Paper(self.game).edition(4),
            facilitator_only_note="who sent what",
        )
        self.assertNotIn("facilitator_only_note", build.curated_edition(edition))

    def test_the_manifest_is_beside_the_public_root_and_not_in_it(self):
        self.assertEqual(
            os.path.dirname(self.record["manifest_path"]),
            os.path.dirname(self.public),
        )
        self.assertFalse(os.path.exists(os.path.join(self.public, build.MANIFEST_FILENAME)))

    def test_the_manifest_says_why_each_file_is_public(self):
        categories = manifest_module.CATEGORIES
        for entry in self.record["files"]:
            self.assertIn(entry["category"], categories)
            self.assertTrue(entry["why_public"].strip())
            self.assertTrue(entry["sha256"])
            self.assertTrue(entry["content_type"])

    def test_nothing_written_anywhere_contains_the_address(self):
        for base, _, names in os.walk(self.record["site_dir"]):
            for name in names:
                with open(os.path.join(base, name), "rb") as fh:
                    self.assertNotIn(FAKE_ID.encode(), fh.read(), name)

    def test_the_build_record_tells_the_facilitator_where_the_paper_is(self):
        self.assertTrue(self.record["published"])
        self.assertEqual(self.record["url"], fake_identity(self.game.config).url())

    def test_a_deployment_with_no_publisher_says_so_rather_than_implying_one(self):
        self.assertEqual(self.record["delivery"]["publishers"], [])
        self.assertFalse(self.record["delivery"]["resolves_today"])

    def test_an_unregistered_publisher_is_a_config_error_not_a_quiet_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                build_into(tmp, config=make_config(hosting__publishers=["some-cdn"]))

    def test_hosting_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = build_into(tmp, config=make_config(hosting__enabled=False))
            self.assertFalse(record["published"])
            self.assertEqual(os.listdir(tmp), [], "a disabled build wrote something")


class CuratedPublicationTest(unittest.TestCase):
    """Only intentionally curated files are published -- from both ends."""

    def test_the_public_root_is_exactly_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = build_into(tmp)
            on_disk = sorted(os.listdir(record["public_root"]))
            declared = sorted(entry["path"] for entry in record["files"])
        self.assertEqual(on_disk, declared)

    def test_a_stray_file_from_an_earlier_build_is_removed_not_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = build_into(tmp)
            stray = os.path.join(record["public_root"], "inbox-dump.txt")
            with open(stray, "w", encoding="utf-8") as fh:
                fh.write("private things\n")
            build_into(tmp)
            self.assertFalse(os.path.exists(stray))

    def test_config_decides_which_categories_are_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = build_into(tmp, config=make_config(
                hosting__publish=["front_page", "archive_index", "editions", "robots"],
            ))
            names = sorted(entry["path"] for entry in record["files"])
        self.assertNotIn("style.css", names)
        self.assertNotIn("archive.json", names)
        self.assertNotIn("round-01.svg", names)
        self.assertIn("round-01.html", names)
        self.assertIn("robots.txt", names)

    def test_edition_and_city_images_are_independently_linked_only_when_published(self):
        """The two supported image categories must not create dangling links."""
        common = [
            "front_page", "archive_index", "editions", "final_edition",
            "archive_json", "stylesheet", "robots",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            edition_only = build_into(tmp, config=make_config(
                hosting__publish=common + ["edition_images"],
            ))
            names = {entry["path"] for entry in edition_only["files"]}
            with open(os.path.join(edition_only["public_root"], "archive.html"), encoding="utf-8") as fh:
                archive = fh.read()
            with open(os.path.join(edition_only["public_root"], "final.html"), encoding="utf-8") as fh:
                final = fh.read()
            self.assertTrue(any(name.startswith("round-") and name.endswith(".svg") for name in names))
            self.assertFalse(any(name.startswith("city-") for name in names))
            self.assertNotIn("city-", archive)
            self.assertNotIn("city-", final)

        with tempfile.TemporaryDirectory() as tmp:
            city_only = build_into(tmp, config=make_config(
                hosting__publish=common + ["city_images"],
            ))
            names = {entry["path"] for entry in city_only["files"]}
            with open(os.path.join(city_only["public_root"], "archive.html"), encoding="utf-8") as fh:
                archive = fh.read()
            with open(os.path.join(city_only["public_root"], "final.html"), encoding="utf-8") as fh:
                final = fh.read()
            cities = sorted(name for name in names if name.startswith("city-") and name.endswith(".svg"))
            self.assertTrue(cities)
            self.assertFalse(any(name.startswith("round-") and name.endswith(".svg") for name in names))
            for portrait in cities:
                self.assertIn(portrait, archive)
                self.assertIn(portrait, final)

    def test_an_unknown_category_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                build_into(tmp, config=make_config(
                    hosting__publish=["front_page", "archive_index", "player_handles"],
                ))

    def test_publishing_robots_with_the_exclusion_switched_off_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                build_into(tmp, config=make_config(hosting__privacy__robots_txt=False))

    def test_a_file_outside_the_flat_public_root_cannot_be_declared(self):
        with self.assertRaises(ConfigError):
            manifest_module.PublicFile(
                "secrets/keys.txt", "editions", "x", "y", "z",
            )
        with self.assertRaises(ConfigError):
            manifest_module.PublicFile(".site-id", "editions", "x", "y", "z")

    def test_two_files_cannot_claim_the_same_name(self):
        book = manifest_module.PublicationManifest(
            "p", "g", fake_identity(), manifest_module.CATEGORIES, "public",
        )
        book.add(manifest_module.PublicFile("round-01.html", "editions", "s", "w", "c", round=1))
        with self.assertRaises(ConfigError):
            book.add(
                manifest_module.PublicFile("round-01.html", "editions", "s", "w", "c", round=1)
            )


class GuardTest(unittest.TestCase):
    """The guard refuses the things it says it refuses."""

    def setUp(self):
        self.game = sample_game()
        self.identity = fake_identity(self.game.config)
        self.paper = Paper(self.game)
        self.archive = self.paper.archive()
        self.copy = self.paper.copy
        self.privacy = build.resolve_privacy(self.game.config)

    def _manifest(self):
        return build.build_manifest(
            self.archive, self.copy, self.game.config, self.identity, self.privacy,
        )

    def _assert_refused(self, path, category, source, why, content):
        book, rendered, curated = self._manifest()
        book.add(manifest_module.PublicFile(path, category, source, why, content))
        with self.assertRaises(guard.PublicationRefused):
            guard.assert_publishable(
                self.game, book, self.archive["editions"], identity=self.identity,
                rendered_by_round=rendered, payloads=[curated],
            )

    def test_a_clean_build_passes(self):
        book, rendered, curated = self._manifest()
        self.assertTrue(guard.assert_publishable(
            self.game, book, self.archive["editions"], identity=self.identity,
            rendered_by_round=rendered, payloads=[curated],
        ))

    def test_a_file_containing_the_address_is_refused(self):
        self._assert_refused(
            "index.json", "archive_json", "hosting.build.curated_archive",
            "a well-meant convenience link",
            json.dumps({"read_it_here": self.identity.url()}),
        )

    def test_a_file_derived_from_private_repo_data_is_refused(self):
        for source in ("coordinator/verdict-m6.md", "workspace/inboxes/p2.json",
                       ".site-id", "config.json", "tests/harness.py"):
            with self.subTest(source=source):
                self._assert_refused(
                    "extra.txt", "archive_json", source, "it seemed useful", "hello\n",
                )

    def test_a_credential_in_a_published_file_is_refused(self):
        for secret in (
            "api_key = sk-live-9f2b\n",
            "-----BEGIN RSA PRIVATE KEY-----\nMII\n",
            "Authorization: Bearer abc123\n",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_0123456789abcdefghijklmnopqrstuvwx",
        ):
            with self.subTest(secret=secret[:20]):
                self._assert_refused(
                    "notes.txt", "archive_json", "hosting.build.curated_archive",
                    "notes", secret,
                )

    def test_an_external_reference_is_refused(self):
        self._assert_refused(
            "extra.txt", "stylesheet", "content/site.css", "a nice font",
            "@font-face { src: url(https://fonts.example/x.woff2); }",
        )

    def test_a_facilitator_view_is_refused(self):
        self._assert_refused(
            "standings.json", "archive_json", "engine.views.standings",
            "the full table",
            json.dumps({"audience": "facilitator", "leaderboard": []}),
        )

    def test_an_unfinished_milestone_stub_is_refused(self):
        self._assert_refused(
            "notes.txt", "archive_json", "hosting.build.curated_archive",
            # A marker of the shape the engine used to emit for work a later
            # milestone owed. None are left; the guard still refuses the shape,
            # which is what this asserts.
            "notes", "[[M9: the copy for this section goes here]]",
        )

    def test_a_handle_in_a_published_page_is_refused(self):
        """Spec #28, re-checked over the HTML rather than over the markdown."""
        handle = self.game.players["m-vlp"].handle
        self._assert_refused(
            "notes.txt", "archive_json", "hosting.build.curated_archive",
            "notes", "<p>Tip from %s, thanks.</p>" % handle,
        )

    def test_a_file_with_no_stated_reason_is_refused(self):
        self._assert_refused(
            "notes.txt", "archive_json", "hosting.build.curated_archive", "   ", "hello\n",
        )

    def test_nothing_in_config_json_can_switch_the_guard_off(self):
        with open(os.path.join(repo_root(), "config.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(guard.assert_no_config_can_disable(data), [])

    def test_the_guard_runs_whatever_the_configurable_flags_say(self):
        """Exposure policy is configurable (#22); leaking is not."""
        game = sample_game(config=make_config(
            newspaper__tone__disallow_snide_or_mean=False,
            newspaper__tone__allow_pointed_humor=False,
            economy__leaderboard_visible_in_newspaper=False,
        ))
        paper = Paper(game)
        archive = paper.archive()
        privacy = build.resolve_privacy(game.config)
        book, rendered, curated = build.build_manifest(
            archive, paper.copy, game.config, self.identity, privacy,
        )
        book.add(manifest_module.PublicFile(
            "leak.txt", "archive_json", "hosting.build.curated_archive", "why not",
            "api_key = sk-live-9f2b",
        ))
        with self.assertRaises(guard.PublicationRefused):
            guard.assert_publishable(
                game, book, archive["editions"], identity=self.identity,
                rendered_by_round=rendered, payloads=[curated],
            )

    def test_the_public_root_must_match_the_manifest_on_disk_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = build_into(tmp, game=self.game)
            book, _, _ = self._manifest()
            with open(os.path.join(record["public_root"], "leftover.html"), "w") as fh:
                fh.write("<p>hi</p>")
            with self.assertRaises(guard.PublicationRefused):
                guard.assert_public_root_matches(book, record["public_root"])


class ArchiveIsAppendOnlyTest(unittest.TestCase):
    """Spec #27: prior editions remain browsable at the same URL."""

    #: Offers with no city and no player id in them. The shared fixture's
    #: ``everyone_exports`` writes "export from p2", and the paper reprints
    #: declined offers verbatim -- so that fixture cannot publish, which is
    #: :func:`newspaper.redact.assert_edition_is_redacted` working rather than a
    #: problem to route around.
    OFFERS = (
        "A brass band, briefly, and the sheet music for one more.",
        "Two hundred metres of very good rope and somebody who can splice it.",
        "A committee that has already failed at this and can save you the time.",
        "Rain, in quantity, and the infrastructure to shrug at it.",
        "A quiet room with a view of water, available Tuesdays.",
    )

    def _submit_exports(self, game):
        need = game.collecting_need()
        if need is None:
            return
        for index, player_id in enumerate(sorted(game.players)):
            if player_id == need.importing_player_id:
                continue
            if "export" in game.checkin_used(player_id):
                continue
            game.submit_export(
                player_id, self.OFFERS[(index + game.current_round) % len(self.OFFERS)]
            )

    def _game_after(self, rounds, config=None):
        """The same game, deterministically, stopped after ``rounds`` have closed."""
        game = new_game(seed=7, config=config)
        for _ in range(rounds):
            if game.phase != "running":
                break
            for player_id in sorted(game.players):
                pick_first(game, player_id)
            self._submit_exports(game)
            advance(game)
        return game

    @staticmethod
    def _article(html):
        """The edition itself, without the navigation wrapped around it.

        The distinction spec #27 actually draws: an edition must not *change*,
        and the archive around it must keep *growing*. Round 3's page gains a
        "next edition" link when round 4 goes to press, which is the archive
        working -- a link appearing is not the issue being rewritten. So the
        article is asserted byte-identical and the navigation is asserted to
        have only gained.
        """
        start = html.index('<article class="edition">')
        return html[start:html.index("</article>", start)]

    def test_a_later_build_leaves_the_earlier_editions_exactly_where_they_were(self):
        early = self._game_after(3)
        with tempfile.TemporaryDirectory() as tmp:
            first = build_into(tmp, game=early)
            before = {}
            for entry in first["files"]:
                with open(os.path.join(first["public_root"], entry["path"]),
                          encoding="utf-8") as fh:
                    before[entry["path"]] = fh.read()

            later = self._game_after(6)
            second = build_into(tmp, game=later)

            self.assertGreater(len(second["rounds"]), len(first["rounds"]))
            for round_index in first["rounds"]:
                self.assertIn(round_index, second["rounds"])
                name = page.edition_page_name(round_index)
                with open(os.path.join(second["public_root"], name), encoding="utf-8") as fh:
                    now = fh.read()
                self.assertEqual(
                    self._article(now), self._article(before[name]),
                    "round %d's edition changed; a mayor's bookmark now shows a "
                    "different paper" % round_index,
                )
                for link in ('href="index.html"', 'href="round-%02d.html"' % (round_index - 1)):
                    if link in before[name]:
                        self.assertIn(link, now, "round %d lost a link" % round_index)

                image = "round-%02d.svg" % round_index
                with open(os.path.join(second["public_root"], image), encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), before[image], image)

    def test_a_build_that_would_drop_a_published_edition_is_refused(self):
        long_game = self._game_after(6)
        with tempfile.TemporaryDirectory() as tmp:
            build_into(tmp, game=long_game)
            short_game = self._game_after(2)
            with self.assertRaises(guard.PublicationRefused):
                build_into(tmp, game=short_game)

    def test_switching_the_archive_off_is_a_config_decision_not_a_silent_loss(self):
        """``archive_prior_editions: false`` publishes only the latest, on purpose.

        Spec #27 is the default and this is the knob under it; the append-only
        check stands down when a facilitator has said, in config, that they do
        not want an archive -- which is a decision, not a build failing to keep
        its promise.
        """
        game = self._game_after(4, config=make_config(
            newspaper__archive_prior_editions=False,
        ))
        with tempfile.TemporaryDirectory() as tmp:
            record = build_into(tmp, game=game)
            record = build_into(tmp, game=self._game_after(2, config=game.config))
        self.assertEqual(len(record["rounds"]), 1)
        self.assertFalse(record["archive_prior_editions"])

    def test_the_round_in_progress_has_no_edition_yet(self):
        """Spec #26 publishes once per *completed* round."""
        from engine import views

        game = self._game_after(3)
        self.assertIn(game.current_round, game.rounds)
        self.assertNotIn(game.current_round, views.published_rounds(game))
        with tempfile.TemporaryDirectory() as tmp:
            record = build_into(tmp, game=game)
        self.assertNotIn(game.current_round, record["rounds"])


class ServingTest(unittest.TestCase):
    """The URL answers. Checked over real HTTP, because that is the requirement."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.identity = fake_identity(cls.game.config)
        cls.record = build_into(cls._tmp.name, game=cls.game, identity=cls.identity)
        cls.httpd, cls.url = serve.make_server(
            cls.game.config, cls.identity, site_dir=cls._tmp.name,
        )
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.httpd.server_address[0], cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    #: No proxy handler. A test that went through an ambient HTTP proxy would be
    #: testing the proxy, and would also be handing this paper's address to it.
    OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def fetch(self, path, method="GET"):
        request = urllib.request.Request(
            "http://%s:%d%s" % (self.host, self.port, path), method=method,
        )
        return self.OPENER.open(request, timeout=5)

    def assert_status(self, path, status):
        try:
            response = self.fetch(path)
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, status, path)
            return error
        self.assertEqual(response.status, status, path)
        return response

    def test_an_edition_is_reachable_at_the_stable_url(self):
        response = self.assert_status("/%s/round-05.html" % FAKE_ID, 200)
        body = response.read().decode("utf-8")
        self.assertIn("Vol. I, No. 5", body)
        self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")

    def test_the_one_url_every_mayor_holds_answers_with_the_latest_edition(self):
        """Spec #30a: the stable URL opens the newest issue, not a contents list."""
        body = self.assert_status("/%s/" % FAKE_ID, 200).read().decode("utf-8")
        newest = max(self.game.rounds)
        self.assertIn("Vol. I, No. %d" % newest, body)
        self.assertIn('href="%s"' % page.edition_page_name(newest), body)
        self.assertIn('href="%s"' % page.ARCHIVE_PAGE_NAME, body)

    def test_the_shelf_answers_at_its_own_name_and_lists_every_edition(self):
        body = self.assert_status(
            "/%s/%s" % (FAKE_ID, page.ARCHIVE_PAGE_NAME), 200
        ).read().decode("utf-8")
        for round_index in sorted(self.game.rounds):
            self.assertIn('href="%s"' % page.edition_page_name(round_index), body)

    def test_prior_editions_are_still_there_at_the_same_url(self):
        """Spec #27, as a reader experiences it: every back issue still answers."""
        for round_index in sorted(self.game.rounds):
            self.assert_status("/%s/%s" % (FAKE_ID, page.edition_page_name(round_index)), 200)

    def test_the_image_and_the_stylesheet_are_served_with_their_own_types(self):
        image = self.assert_status("/%s/round-05.svg" % FAKE_ID, 200)
        self.assertEqual(image.headers["Content-Type"], "image/svg+xml; charset=utf-8")
        css = self.assert_status("/%s/style.css" % FAKE_ID, 200)
        self.assertEqual(css.headers["Content-Type"], "text/css; charset=utf-8")

    def test_every_response_carries_the_noindex_and_no_referrer_headers(self):
        config = self.game.config
        for path in ("/%s/" % FAKE_ID, "/%s/round-01.html" % FAKE_ID, "/nothing-here"):
            response = self.assert_status(path, 200 if FAKE_ID in path else 404)
            headers = response.headers
            self.assertEqual(
                headers["X-Robots-Tag"], config.require_str("hosting.privacy.x_robots_tag"), path,
            )
            self.assertEqual(
                headers["Referrer-Policy"],
                config.require_str("hosting.privacy.referrer_policy"), path,
            )
            self.assertEqual(
                headers["Cache-Control"],
                config.require_str("hosting.privacy.cache_control"), path,
            )
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff", path)

    def test_robots_txt_answers_without_the_address(self):
        body = self.assert_status("/robots.txt", 200).read().decode("utf-8")
        self.assertIn("Disallow: /", body)
        self.assertNotIn(FAKE_ID, body)

    def test_nothing_is_reachable_without_the_address(self):
        for path in ("/", "/index.html", "/round-01.html", "/style.css",
                     "/wrong-address/round-01.html", "/%s/round-01.html" % FAKE_ID[:-1]):
            self.assert_status(path, 404)

    def test_the_manifest_and_anything_else_off_the_list_are_not_served(self):
        for path in (
            "/%s/%s" % (FAKE_ID, build.MANIFEST_FILENAME),
            "/%s/round-99.html" % FAKE_ID,
            "/%s/../publication-manifest.json" % FAKE_ID,
            "/%s/nested/round-01.html" % FAKE_ID,
            "/%s/.site-id" % FAKE_ID,
        ):
            self.assert_status(path, 404)

    def test_a_head_request_answers_the_same_way(self):
        response = self.fetch("/%s/round-01.html" % FAKE_ID, method="HEAD")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b"")
        self.assertNotEqual(response.headers["Content-Length"], "0")

    def test_serving_a_site_that_was_never_built_is_refused(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(ConfigError):
                serve.make_server(self.game.config, self.identity, site_dir=empty)


class SiteArtifactTest(unittest.TestCase):
    """Regenerates the committed ``site/``.

    Like :class:`tests.test_publish.SampleEditionArtifactTest`, this writes into
    the repository deliberately: the build is deterministic, so a run that
    changes nothing leaves a clean tree and a run that changes the paper shows
    up as a reviewable diff. It uses the repository's real site id if one has
    been minted -- and publishes nothing containing it, which is the property
    that makes the committed tree safe.
    """

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls.identity = identity_module.load_or_create(cls.game.config)
        cls.record = hosting.build_site(cls.game, identity=cls.identity)

    def test_it_lands_where_config_says_the_site_goes(self):
        config = self.game.config
        expected = os.path.join(
            repo_root(),
            config.require_str("hosting.site_dir"),
            config.require_str("hosting.public_subdir"),
        )
        self.assertEqual(self.record["public_root"], expected)

    def test_the_committed_tree_is_exactly_the_manifest(self):
        with open(self.record["manifest_path"], encoding="utf-8") as fh:
            book = json.load(fh)
        self.assertEqual(
            sorted(os.listdir(self.record["public_root"])),
            sorted(entry["path"] for entry in book["files"]),
        )
        self.assertEqual(book["published_rounds"], sorted(self.game.rounds))
        self.assertTrue(book["address"]["address_withheld"])
        self.assertNotIn(
            "site_id_fingerprint", book["address"],
            "the committed manifest must not carry a machine-local field",
        )

    def test_no_committed_byte_contains_the_address(self):
        """The property that makes committing a private paper's site safe."""
        needle = self.identity.site_id.encode()
        for base, _, names in os.walk(os.path.dirname(self.record["public_root"])):
            for name in names:
                with open(os.path.join(base, name), "rb") as fh:
                    self.assertNotIn(needle, fh.read(), name)

    def test_rebuilding_writes_the_same_bytes(self):
        before = {}
        for base, _, names in os.walk(self.record["public_root"]):
            for name in names:
                path = os.path.join(base, name)
                with open(path, "rb") as fh:
                    before[path] = fh.read()
        hosting.build_site(sample_game(), identity=self.identity)
        for path, content in before.items():
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), content, path)


if __name__ == "__main__":
    unittest.main()
