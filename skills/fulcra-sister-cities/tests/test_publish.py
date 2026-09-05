"""Writing editions to disk, and the committed sample run.

M5's "done when" is a rendered edition artifact on disk with correct redaction,
correct aggregate phrasing and a recorded image modality. This module both checks
that and produces it: :class:`SampleEditionArtifactTest` regenerates
``editions/sample-game/`` from the scripted game in :mod:`newspaper.sample`.

That test writes into the repository on purpose. The sample game is deterministic,
so a run that changes nothing leaves the working tree clean, and a run that
changes the paper shows up as a diff in the committed editions -- which is the
review anybody would want anyway. The same files come out of
``python3 -m newspaper.publish``; the test is the route that works in a harness
where only the test runner is allowed to execute.
"""

import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from harness import make_config
from engine.config import repo_root
from newspaper import imagery, redact
from newspaper.publish import publish_game, without_image_content
from newspaper.sample import sample_game

SAMPLE_LABEL = "sample-game"


class PublishTest(unittest.TestCase):
    """Pure checks, in a temporary directory."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.manifest = publish_game(cls.game, label="tmp", out_dir=cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_one_set_of_files_per_round(self):
        self.assertEqual(
            [entry["round"] for entry in self.manifest["editions"]],
            sorted(self.game.rounds),
        )
        for entry in self.manifest["editions"]:
            for kind in ("markdown", "json", "image"):
                self.assertTrue(os.path.getsize(entry["files"][kind]) > 0, entry)

    def test_the_archive_index_lists_every_edition(self):
        with open(self.manifest["index"], encoding="utf-8") as fh:
            index = fh.read()
        for entry in self.manifest["editions"]:
            self.assertIn("round-%02d.md" % entry["round"], index)

    def test_an_earlier_edition_is_never_overwritten_by_a_later_one(self):
        # Spec #27: an archive, not an overwrite.
        names = {os.path.basename(entry["files"]["markdown"])
                 for entry in self.manifest["editions"]}
        self.assertEqual(len(names), len(self.manifest["editions"]))

    def test_the_recorded_image_modality_is_the_one_that_was_used(self):
        for entry in self.manifest["editions"]:
            self.assertEqual(entry["image_modality"], imagery.SVG_PROCEDURAL)
            self.assertEqual(entry["image_provider"], imagery.BUILTIN_SVG_PROVIDER)
            self.assertTrue(entry["files"]["image"].endswith(".svg"))

    def test_the_json_records_the_image_without_inlining_it(self):
        with open(self.manifest["editions"][3]["files"]["json"], encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertNotIn("content", payload["image"])
        self.assertEqual(payload["image"]["file"], payload["image"]["filename"])
        self.assertEqual(payload["image"]["provenance"]["modality"], imagery.SVG_PROCEDURAL)

    def test_every_written_file_is_free_of_handles_and_placeholders(self):
        for entry in self.manifest["editions"]:
            for path in entry["files"].values():
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                self.assertNotIn("[[", text)
                for player in self.game.players.values():
                    self.assertNotIn(player.handle, text)

    def test_an_unknown_output_format_is_refused(self):
        from engine.errors import ConfigError

        game = sample_game(config=make_config(newspaper__output__formats=["pdf"]))
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaises(ConfigError):
                publish_game(game, label="tmp", out_dir=out)

    def test_the_formats_written_follow_config(self):
        game = sample_game(config=make_config(newspaper__output__formats=["markdown"]))
        with tempfile.TemporaryDirectory() as out:
            manifest = publish_game(game, label="tmp", out_dir=out)
        self.assertEqual(set(manifest["editions"][0]["files"]), {"markdown"})

    def test_dropping_image_content_leaves_the_edition_otherwise_intact(self):
        from newspaper import build_edition

        edition = build_edition(self.game, 5)
        trimmed = without_image_content(edition)
        self.assertIn("content", edition["image"])
        self.assertNotIn("content", trimmed["image"])
        self.assertEqual(trimmed["departments"], edition["departments"])


class SampleEditionArtifactTest(unittest.TestCase):
    """Regenerates the committed sample run and checks what it wrote.

    See the module docstring: this one writes into the repository, deliberately.
    """

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls.manifest = publish_game(cls.game, label=SAMPLE_LABEL)

    def test_the_sample_lands_where_config_says_editions_go(self):
        expected = os.path.join(
            repo_root(),
            self.game.config.require_str("newspaper.output.editions_dir"),
            SAMPLE_LABEL,
        )
        self.assertEqual(self.manifest["directory"], expected)
        self.assertTrue(os.path.isdir(expected))

    def test_it_wrote_a_full_game_of_editions(self):
        self.assertEqual(len(self.manifest["editions"]), 12)
        self.assertTrue(os.path.exists(self.manifest["index"]))
        self.assertTrue(os.path.exists(self.manifest["archive"]))

    def test_every_committed_image_is_well_formed_svg(self):
        for entry in self.manifest["editions"]:
            ET.parse(entry["files"]["image"])

    def test_every_committed_edition_passes_the_redaction_audit(self):
        with open(self.manifest["archive"], encoding="utf-8") as fh:
            archive = json.load(fh)
        for edition in archive["editions"]:
            redact.assert_edition_is_redacted(self.game, edition)

    def test_the_committed_markdown_reads_as_a_newspaper(self):
        with open(self.manifest["editions"][4]["files"]["markdown"], encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("# The Daily Manifest", "## Wanted", "## Sealed Bids",
                       "## Arrivals", "## Corrections & Clarifications", "![" ):
            self.assertIn(marker, text)

    def test_republishing_writes_the_same_bytes(self):
        """The drift check: a deterministic paper leaves a clean working tree."""
        before = {}
        for entry in self.manifest["editions"]:
            for path in entry["files"].values():
                with open(path, "rb") as fh:
                    before[path] = fh.read()
        publish_game(sample_game(), label=SAMPLE_LABEL)
        for path, content in before.items():
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), content, path)


if __name__ == "__main__":
    unittest.main()
