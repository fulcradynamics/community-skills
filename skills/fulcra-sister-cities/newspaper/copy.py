"""``content/newspaper.json``: loading it, and choosing from it.

The paper's sentences are content, not code. This module loads that content and
owns the three mechanical decisions that turn a list of frames into one printed
line:

* **which frame** -- deterministically, from the round's own facts, so a game
  replayed from the same seed produces the same paper (:class:`Chooser`)
* **whether a frame is allowed** -- ``newspaper.tone.allow_pointed_humor``
  decides whether frames content marks ``pointed`` may be used at all (spec #30)
* **whether it filled** -- :func:`fill` refuses to return a line with an
  unfilled ``{placeholder}`` in it, so a typo in the content file is a failure
  to publish rather than a brace printed in the newspaper

Nothing here knows what a department is; that is :mod:`newspaper.departments`.
"""

import json
import os
import re
import zlib

from engine.config import repo_root
from engine.errors import ConfigError, ContentError

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_NUMBER_WORDS = (
    "no", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
)


def count_word(n):
    """``4 -> "four"``, ``0 -> "no"``, ``31 -> "31"``.

    The paper spells small numbers out because papers do. Above twenty it stops
    pretending and prints the figure.
    """
    return _NUMBER_WORDS[n] if 0 <= n < len(_NUMBER_WORDS) else str(n)


def counted(n, singular, plural=None):
    """``1, "offer" -> "one offer"``; ``3, "offer" -> "three offers"``.

    A frame that writes "{count_word} offers" prints "one offers" the day a
    count comes back as one, and the last edition counts small piles constantly
    -- how many offers a city declined, how many of those are reprinted, how
    many are withheld. Giving the frames a phrase that already agrees with its
    own number is cheaper than writing a singular twin of each of them, and it
    fails less often than remembering to.
    """
    return "%s %s" % (count_word(n), singular if n == 1 else (plural or singular + "s"))


def fill(template, values, where):
    """Substitute ``{name}`` placeholders, refusing to leave any behind.

    Two failures, both content errors rather than silent output:

    * a placeholder this call has no value for -- the frame was written against
      a different family's substitution table (see ``_placeholders`` in
      ``content/newspaper.json``)
    * a value that is ``None`` -- which would print "None" in the paper

    There is no ``str.format`` here on purpose: ``format`` would also interpret
    ``{}`` and ``{0}`` and would raise on a stray brace in an export a player
    wrote, and an export is the one string in this game the paper must be able
    to reproduce exactly.
    """
    used = set()

    def replace(match):
        name = match.group(1)
        if name not in values:
            raise ContentError(
                "%s: frame uses {%s}, which is not available here. Frames may only use "
                "the placeholders their family declares in content/newspaper.json's "
                "_placeholders table; available: %s"
                % (where, name, sorted(values))
            )
        value = values[name]
        if value is None:
            raise ContentError("%s: {%s} has no value for this round" % (where, name))
        used.add(name)
        return str(value)

    return _PLACEHOLDER.sub(replace, template)


def sentence_case(text):
    """Capitalise the start of every sentence in a rendered line.

    Frames are written to start a sentence with a substitution as often as not
    -- ``"{count_word} offers are now on the desk"``, ``"{mayor} has taken out an
    advertisement"`` -- and what goes in is a lower-case noun phrase ("three",
    "the Mayor of Hobart"). Doing this once, here, is why the content file does
    not need a capitalised twin of every value.

    It capitalises after ``.``, ``?`` and ``!`` as well as at the start, which
    would mishandle a sentence beginning immediately after an abbreviation. The
    paper's copy contains none, deliberately: an abbreviation mid-frame would be
    a reason to rewrite the frame rather than to complicate this.
    """
    out = []
    pending = True
    for char in text:
        if pending and char.isalpha():
            out.append(char.upper())
            pending = False
            continue
        out.append(char)
        if char in ".?!":
            pending = True
        elif char not in _TRANSPARENT:
            # A closing quote, a dash or a figure ends the run: what follows is
            # mid-sentence. Only the characters that can sit *between* a full
            # stop and the first word of the next sentence are transparent.
            pending = False
    return "".join(out)


#: Characters that neither open nor close a sentence. An opening quote, a
#: bracket and Markdown's emphasis markers all sit in front of the first word;
#: a *closing* quote does not, which is why ``”`` is deliberately absent.
_TRANSPARENT = " \t“\"'(*_["


class Chooser:
    """Picks one frame from a list, deterministically and within tone policy.

    The key is game state -- round number, need key, resolution mode -- never a
    counter and never a random number: two mayors reading the same edition must
    read the same words, and a game replayed from its seed must produce the same
    paper it produced the first time.
    """

    def __init__(self, allow_pointed=True):
        self.allow_pointed = allow_pointed

    @staticmethod
    def normalize(frames, where):
        """``["a", {"line": "b", "pointed": true}]`` -> a list of pairs."""
        if not isinstance(frames, list) or not frames:
            raise ContentError("%s must be a non-empty list of frames" % where)
        out = []
        for frame in frames:
            if isinstance(frame, str):
                out.append((frame, False))
            elif isinstance(frame, dict) and isinstance(frame.get("line"), str):
                out.append((frame["line"], bool(frame.get("pointed"))))
            else:
                raise ContentError(
                    "%s: a frame is either a string or {line, pointed}, got %r"
                    % (where, frame)
                )
            if not out[-1][0].strip():
                raise ContentError("%s has an empty frame" % where)
        return out

    def allowed(self, frames, where):
        """The frames this game's tone policy permits (spec #30)."""
        candidates = self.normalize(frames, where)
        if self.allow_pointed:
            return [line for line, _ in candidates]
        plain = [line for line, pointed in candidates if not pointed]
        if not plain:
            raise ContentError(
                "%s offers only pointed frames, so it has nothing to say when "
                "config.newspaper.tone.allow_pointed_humor is false. Every family in "
                "content/newspaper.json must keep at least one unpointed frame." % where
            )
        return plain

    def pick(self, frames, key, where, offset=0):
        """One frame, chosen by ``key``, verbatim. Same key, same frame, forever.

        Returns the frame *as written*: unfilled and not sentence-cased. That is
        what makes it the right method for choosing a **fragment** rather than a
        line -- an aggregate phrase from the ladder ("one lone municipality")
        goes on to be interpolated into a frame, and may well land mid-sentence,
        so capitalising it here would be capitalising it in the wrong place. Use
        :meth:`line` or :meth:`rotate` for anything that is itself a sentence.
        """
        candidates = self.allowed(frames, where)
        digest = zlib.crc32(("|".join(str(part) for part in key)).encode("utf-8"))
        return candidates[(digest + offset) % len(candidates)]

    def rotate(self, frames, key, where, offset, values=None):
        """One filled, sentence-cased line, ``offset`` places past ``key``'s.

        For a run of consecutive sentences from the same family -- three outliers
        quoted one after another -- where repeating a frame reads as a template
        showing through. Same key and same offset, same frame, forever.
        """
        chosen = self.pick(frames, key, where, offset=offset)
        return sentence_case(fill(chosen, values or {}, where))

    def line(self, frames, key, where, values=None):
        """:meth:`pick`, then :func:`fill`, then :func:`sentence_case`."""
        chosen = self.pick(frames, key, where)
        return sentence_case(fill(chosen, values or {}, where))

    def lines(self, frames, key, where, values=None, count=1):
        """``count`` *distinct* frames from one family, in a stable order.

        Used where the paper wants two or three consecutive sentences from the
        same pool (the corrections column, the ramp-up colour) without printing
        the same one twice. If the family is smaller than ``count``, it returns
        what there is rather than repeating.
        """
        candidates = self.allowed(frames, where)
        digest = zlib.crc32(("|".join(str(part) for part in key)).encode("utf-8"))
        start = digest % len(candidates)
        chosen = [candidates[(start + offset) % len(candidates)]
                  for offset in range(min(count, len(candidates)))]
        return [sentence_case(fill(frame, values or {}, where)) for frame in chosen]


class NewspaperCopy:
    """``content/newspaper.json``, validated enough to fail early."""

    def __init__(self, data, source="<memory>"):
        if not isinstance(data, dict):
            raise ContentError("newspaper content must be a JSON object")
        self.data = data
        self.source = source
        for block in ("mastheads", "departments", "wire_styles", "imagery", "site",
                      "bulletin", "tone"):
            if not isinstance(data.get(block), dict):
                raise ContentError(
                    "newspaper content at %s has no %r block" % (source, block)
                )

    @classmethod
    def load(cls, config, root=None):
        root = root or repo_root()
        path = os.path.join(root, config.require_str("content.newspaper_file"))
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            raise ContentError("newspaper content not found at %s" % path)
        except ValueError as exc:
            raise ContentError("newspaper content at %s is not valid JSON: %s" % (path, exc))
        return cls(data, source=path)

    # -- lookups ----------------------------------------------------------

    def masthead(self, config):
        """The masthead ``newspaper.masthead_id`` names."""
        masthead_id = config.require_str("newspaper.masthead_id")
        try:
            masthead = self.data["mastheads"][masthead_id]
        except KeyError:
            raise ConfigError(
                "config.newspaper.masthead_id is %r; %s ships mastheads %s"
                % (masthead_id, self.source, sorted(self.data["mastheads"]))
            )
        for field in ("publication", "motto", "edition_line", "price_lines", "weather_lines",
                      # The last edition's own three lines (spec #31). Required
                      # rather than optional-with-a-fallback: a final edition
                      # headed "Vol. I, No. 12" like any other round would be the
                      # paper failing to notice its own last day.
                      "final_edition_line", "final_standing_line", "final_foot"):
            if not masthead.get(field):
                raise ContentError("masthead %r is missing %r" % (masthead_id, field))
        return masthead

    def wire_style(self, config):
        """The prose register ``facilitator_questions.aggregate_phrasing_style`` names.

        The *claim* is not in here -- that is decided arithmetically in
        :mod:`engine.aggregate`. This is only the sentence it goes into, which is
        why it is a separate config key from the ladder: a game can change how
        the paper writes without changing what counts as true.
        """
        style_id = config.require_str("facilitator_questions.aggregate_phrasing_style")
        try:
            style = self.data["wire_styles"][style_id]
        except KeyError:
            raise ConfigError(
                "config.facilitator_questions.aggregate_phrasing_style is %r; %s ships "
                "styles %s" % (style_id, self.source, sorted(self.data["wire_styles"]))
            )
        required = (
            "put_it_to", "tier_claim", "tie_claim", "fragmented_claim", "floor_claim",
            "count_full", "count_partial", "count_tie", "count_fragmented", "count_floor",
            "subgroup", "outlier", "floor_quote", "closers",
        )
        missing = [field for field in required if not style.get(field)]
        if missing:
            raise ContentError("wire style %r is missing %s" % (style_id, missing))
        return style

    def department(self, name):
        try:
            return self.data["departments"][name]
        except KeyError:
            raise ContentError(
                "%s has no department %r; it ships %s"
                % (self.source, name, sorted(self.data["departments"]))
            )

    def imagery(self):
        imagery = self.data["imagery"]
        for field in ("palettes", "monochrome_palette", "default_palette", "cutlines", "labels"):
            if not imagery.get(field):
                raise ContentError("imagery block is missing %r" % field)
        if imagery["default_palette"] not in imagery["palettes"]:
            raise ContentError(
                "imagery.default_palette %r is not one of the palettes"
                % imagery["default_palette"]
            )
        return imagery

    def endgame_imagery(self):
        """The art direction for the last edition's pictures (spec #31, #32).

        A separate block from :meth:`imagery` because it is a separate brief --
        the round pictures are a harbour on one day, and these are the whole
        world at the end and one city at a time. The palettes are shared, since a
        city's colours should not change on the last day.
        """
        imagery = self.imagery()
        endgame = imagery.get("endgame")
        if not isinstance(endgame, dict):
            raise ContentError("imagery block has no 'endgame' block (spec #31, #32)")
        for field in ("finale_cutlines", "city_cutlines", "labels"):
            if not endgame.get(field):
                raise ContentError("imagery.endgame is missing %r" % field)
        for outcome in ("crowned", "shared", "uncrowned"):
            if not endgame["finale_cutlines"].get(outcome):
                raise ContentError(
                    "imagery.endgame.finale_cutlines is missing %r; the finale has one "
                    "cutline family per way the game can finish" % outcome
                )
        return endgame

    def palette(self, category, colorful=True):
        """The palette for a category, or the monochrome one (spec #30's ``colorful``)."""
        imagery = self.imagery()
        if not colorful:
            return dict(imagery["monochrome_palette"])
        palettes = imagery["palettes"]
        return dict(palettes.get(category) or palettes[imagery["default_palette"]])

    def site(self):
        """The archive's own chrome (spec #26, #27) -- what the site says about itself.

        Separate from :meth:`masthead` because it is a different voice: the
        masthead is the paper talking about a day, this is the paper talking
        about the shelf all the days are kept on.
        """
        site = self.data["site"]
        for field in ("front_title", "front_flag", "archive_title", "archive_heading",
                      "archive_blurb", "empty_archive", "privacy_notice",
                      "identity_notice", "colophon", "nav", "labels", "robots_preamble"):
            if not site.get(field):
                raise ContentError("site block is missing %r" % field)
        # Spec #30a's navigation set, in full: a page that could not name one of
        # these would be a page quietly missing a way out of itself.
        for field in ("title", "archive", "previous", "next", "latest", "permalink",
                      "top", "endgame"):
            if not site["nav"].get(field):
                raise ContentError("site.nav is missing %r" % field)
        for field in ("editions_count", "image", "round", "inside", "endgame",
                      "endgame_kicker", "portrait"):
            if not site["labels"].get(field):
                raise ContentError("site.labels is missing %r" % field)
        return site

    def bulletin(self):
        """What the facilitator says to the group when an edition lands (#26).

        Not printed in the paper, and still the paper's voice, so it lives with
        the rest of the copy rather than in the code that sends it.
        """
        bulletin = self.data["bulletin"]
        for field in ("round_notice", "round_notice_without_url", "final_notice",
                      "final_notice_without_url", "opened_lede", "quiet_lede"):
            if not isinstance(bulletin.get(field), list) or not bulletin[field]:
                raise ContentError("bulletin block is missing %r (spec #26)" % field)
        return bulletin

    def tone(self):
        tone = self.data["tone"]
        if not isinstance(tone.get("forbidden_register"), list) or not tone["forbidden_register"]:
            raise ContentError("tone.forbidden_register must be a non-empty list (spec #30)")
        return tone

    def player_voice(self):
        """The lines that say which words in this paper a mayor wrote (#30b).

        A separate block from :meth:`tone` although the two are one decision
        read from either end: ``tone`` is the standard the desk holds itself to,
        and this is how the page tells a reader that a passage is not the desk
        talking. Every family is required, because a quote whose cite family was
        missing would print as an unattributed quotation -- which for a declined
        offer is exactly the leak spec #21 forbids, and for a winning one is the
        paper taking credit for a mayor's writing.
        """
        block = self.data["player_voice"]
        for field in ("winner_quote", "declined_quote", "twist_quote", "excess_quote"):
            if not isinstance(block.get(field), list) or not block[field]:
                raise ContentError(
                    "player_voice.%s must be a non-empty list (spec #30b)" % field
                )
        return block
