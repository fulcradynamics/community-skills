"""Every frame in ``content/newspaper.json``, rendered by the code that owns it.

Which frame the paper prints is chosen by a CRC of game state (see
:class:`newspaper.copy.Chooser`): same round, same need, same words, forever.
That is the right behaviour for a newspaper and an awkward one for a test
suite, because it means an unrenderable frame does not fail when it is written,
or in the sample game, or anywhere in this suite -- it fails in whichever real
game first happens to hash its way onto it.

That is exactly how The Crown's third standfirst got in. It used ``{n_needs}``,
which ``_placeholders`` declares for that department and which the standfirst
family was rendered without, and it stayed invisible through the whole of M7
because no game had yet hashed onto frame 2 of that family. The eight-mayor
integration game did, on its final edition, and the paper refused to publish.

So this test takes the chooser's discretion away. It pins the chooser to frame
*i* of every family it is asked for, for every *i* up to the largest family in
the file, and rebuilds the entire paper -- twelve editions and the final one --
each time. Every frame the sample game's departments reach is therefore rendered
by its own department, against the values that department really passes.

Two checks, one from each side of the failure:

* :class:`EveryFrameRendersTest` -- the dynamic side. Nothing raises, and the
  frame that broke is demonstrably among the ones now rendered.
* :class:`DeclaredPlaceholdersTest` -- the static side. No frame anywhere in the
  file uses a substitution its department does not declare, which is the same
  mistake made in the other direction and is cheap to rule out for the whole
  file at once.
"""

import json
import os
import re
import unittest

import harness  # noqa: F401  (path setup)
from engine.errors import ContentError
from newspaper import copy as copy_module
from newspaper.copy import Chooser
from newspaper.edition import Paper
from newspaper.sample import sample_game

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER = re.compile(r"\{(\w+)\}")

#: The frame this test exists because of. If the sweep ever stops reaching it,
#: the sweep has stopped doing its job and this test would pass vacuously.
REGRESSION_FRAME = "{n_needs}"


def newspaper_content():
    with open(os.path.join(ROOT, "content", "newspaper.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def frames_under(node, path=()):
    """Every frame in the file, as ``(dotted path, text)``.

    A frame is a string in a list, or the ``line`` of a ``{line, pointed}``
    object in a list (see ``_pointed_note``). Keys beginning with ``_`` are
    commentary and declarations, not copy.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if not key.startswith("_"):
                for found in frames_under(value, path + (key,)):
                    yield found
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                yield ".".join(path), item
            elif isinstance(item, dict) and isinstance(item.get("line"), str):
                yield ".".join(path), item["line"]
            else:
                for found in frames_under(item, path):
                    yield found


class ForcedChooser(Chooser):
    """A chooser with its discretion removed: always frame ``index``.

    It overrides the two methods that select -- :meth:`pick`, which
    :meth:`~newspaper.copy.Chooser.line` and
    :meth:`~newspaper.copy.Chooser.rotate` are both built on, and :meth:`lines`,
    which selects its own run -- and leaves filling, tone policy and sentence
    casing exactly as they are. The point is to change *which* frame is rendered
    and nothing whatever about *how*.
    """

    def __init__(self, index, allow_pointed=True):
        Chooser.__init__(self, allow_pointed=allow_pointed)
        self.index = index

    def pick(self, frames, key, where, offset=0):
        candidates = self.allowed(frames, where)
        return candidates[(self.index + offset) % len(candidates)]

    def lines(self, frames, key, where, values=None, count=1):
        candidates = self.allowed(frames, where)
        chosen = [
            candidates[(self.index + offset) % len(candidates)]
            for offset in range(min(count, len(candidates)))
        ]
        return [
            copy_module.sentence_case(copy_module.fill(frame, values or {}, where))
            for frame in chosen
        ]


def paper_pinned_to(game, index):
    """A Paper whose every frame choice is frame ``index``."""
    paper = Paper(game)
    forced = ForcedChooser(index, allow_pointed=paper.tone.allow_pointed)
    paper.chooser = forced
    # The two department writers were handed the original chooser in Paper's
    # constructor, so replacing the attribute alone would pin nothing.
    paper.departments.chooser = forced
    paper.endgame_departments.chooser = forced
    return paper


class EveryFrameRendersTest(unittest.TestCase):
    """The sweep. Rebuilds the whole paper once per frame index."""

    @classmethod
    def setUpClass(cls):
        cls.game = sample_game()
        cls.content = newspaper_content()
        cls.all_frames = list(frames_under(cls.content))
        # One pass per frame index, up to the largest family in the file: past
        # that, every family has wrapped and nothing new is reached.
        cls.widest = max(
            len(value)
            for _, value in _families(cls.content)
        )
        cls.rendered = set()
        cls.errors = []
        for index in range(cls.widest):
            paper = paper_pinned_to(cls.game, index)
            recorder, restore = _record_fills(cls.rendered)
            try:
                paper.archive()
            except ContentError as exc:
                cls.errors.append("frame index %d: %s" % (index, exc))
            finally:
                restore()
            del recorder

    def test_every_reachable_frame_renders(self):
        self.assertEqual(self.errors, [], "\n".join(self.errors))

    def test_the_sweep_reaches_more_frames_than_one_ordinary_edition(self):
        """Anti-vacuity: pinning must actually change what gets rendered."""
        unpinned = set()
        recorder, restore = _record_fills(unpinned)
        try:
            Paper(self.game).archive()
        finally:
            restore()
        del recorder
        self.assertGreater(len(self.rendered), len(unpinned))
        self.assertTrue(unpinned.issubset(self.rendered))

    def test_the_frame_this_test_exists_for_is_among_them(self):
        crown = [
            frame for path, frame in self.all_frames
            if path == "departments.the_crown.standfirsts" and REGRESSION_FRAME in frame
        ]
        self.assertEqual(len(crown), 1, "the regression frame has moved or been deleted")
        self.assertIn(crown[0], self.rendered)

    def test_it_renders_the_endgame_departments_too(self):
        """The failure was in the final edition, so the sweep must reach it."""
        endgame = {
            frame for path, frame in self.all_frames
            if path.startswith("departments.the_crown.")
            or path.startswith("departments.consequences.")
            or path.startswith("departments.the_excess.")
        }
        self.assertTrue(endgame & self.rendered)


def _families(content):
    """Every family in the file, as ``(dotted path, list of frames)``."""
    seen = {}
    for path, frame in frames_under(content):
        seen.setdefault(path, []).append(frame)
    return sorted(seen.items())


def _record_fills(sink):
    """Patch :func:`newspaper.copy.fill` to record every frame it renders.

    Returns ``(original, restore)``. Recording at ``fill`` rather than at the
    chooser catches frames rendered by anything that fills a template, which is
    the definition of "reached the page" this test wants.
    """
    original = copy_module.fill

    def recording(template, values, where):
        result = original(template, values, where)
        sink.add(template)
        return result

    copy_module.fill = recording

    def restore():
        copy_module.fill = original

    return original, restore


class DeclaredPlaceholdersTest(unittest.TestCase):
    """The static half: no frame may use a substitution its family cannot have.

    ``_placeholders`` in the content file declares, per department, which
    substitutions its frames may use, and the file's own comment says the table
    is "enforced rather than merely documented". This is where it is enforced
    over the whole file at once, rather than one department at a time whenever a
    game happens to render one.
    """

    @classmethod
    def setUpClass(cls):
        cls.content = newspaper_content()
        cls.declared = cls.content["_placeholders"]

    def test_the_table_covers_every_department(self):
        departments = set(self.content["departments"]) - {"_comment"}
        undeclared = departments - set(self.declared)
        self.assertEqual(undeclared, set(), "departments with no _placeholders entry")

    def test_no_department_frame_uses_an_undeclared_placeholder(self):
        everywhere = {name.strip("{}") for name in self.declared["everywhere"]}
        offences = []
        for path, frame in frames_under(self.content["departments"]):
            department = path.split(".")[0]
            allowed = {
                name.strip("{}") for name in self.declared.get(department, [])
            } | everywhere
            for name in PLACEHOLDER.findall(frame):
                if name not in allowed:
                    offences.append("departments.%s uses {%s}: %r" % (path, name, frame))
        self.assertEqual(offences, [], "\n".join(offences))


class SeededContentIsPrintableTest(unittest.TestCase):
    """Seeded prose must survive the paper's own forbidden register (#30, #33).

    The register is enforced over each finished edition, so a seeded string the
    register objects to does not fail at load: it fails on whichever night the
    game happens to draw it, by refusing to publish the edition that quotes it.
    A seeded question did exactly that here -- "the most useless thing you refuse
    to throw away" is innocent about an object and identical, to a substring
    matcher, to an insult -- and it held up an edition of the integration game.

    ``content/newspaper.json``'s own note on the register says the cost of a
    false positive is a rewrite and the cost of a false negative is a player
    reading something unkind about themselves, and that the trade is not close.
    This test is that trade, applied to the seed files at build time instead of
    at 3am on game night.
    """

    #: Keys whose values are identifiers, categories or schema plumbing rather
    #: than prose the paper can print. ``id`` in particular is excluded on
    #: purpose: question ids are referenced by recorded games (see
    #: ``playtest/transcript.json``), so they are keys, not copy, and renaming
    #: one to satisfy a prose rule would silently rewrite a played game.
    NOT_PROSE = frozenset({
        "id", "set_id", "category", "framing", "answer_shape", "buckets",
        "schema_version", "scope", "source", "required_in", "renders_to",
        # The register is the list of terms itself. It is the rule, not copy,
        # and it necessarily contains every word it forbids.
        "forbidden_register",
    })

    @classmethod
    def setUpClass(cls):
        cls.tone = Paper(sample_game()).tone

    def printable_strings(self, data, path=()):
        if isinstance(data, dict):
            for key, value in data.items():
                if key.startswith("_") or key in self.NOT_PROSE:
                    continue
                for found in self.printable_strings(value, path + (key,)):
                    yield found
        elif isinstance(data, list):
            for item in data:
                for found in self.printable_strings(item, path):
                    yield found
        elif isinstance(data, str):
            yield ".".join(path), data

    def assert_file_is_printable(self, filename):
        with open(os.path.join(ROOT, "content", filename), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        offences = [
            "%s at %s: %r" % (filename, path, finding)
            for path, text in self.printable_strings(data)
            for finding in self.tone.findings(text)
        ]
        self.assertEqual(offences, [], "\n".join(offences))

    def test_the_question_bank_is_printable(self):
        self.assert_file_is_printable("questions.json")

    def test_the_seeded_import_needs_are_printable(self):
        self.assert_file_is_printable("import_needs.json")

    def test_the_papers_own_copy_is_printable(self):
        self.assert_file_is_printable("newspaper.json")

    def test_the_check_would_actually_catch_a_bad_seed(self):
        """Anti-vacuity: the walker must reach the fields it claims to reach."""
        bad = {"questions": [{"id": "q-x", "text": "Mayor, why so useless?"}]}
        found = [
            finding
            for _, text in self.printable_strings(bad)
            for finding in self.tone.findings(text)
        ]
        self.assertTrue(found)
        # ...and must not object to the id, which is a key rather than copy.
        self.assertEqual(
            [path for path, _ in self.printable_strings(bad)], ["questions.text"]
        )


if __name__ == "__main__":
    unittest.main()
