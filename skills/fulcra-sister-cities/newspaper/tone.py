"""The mechanical half of spec #30.

Spec #30 asks for funny, fun and colourful, allows humour that is pointed rather
than uniformly laudatory, and forbids snide or mean. Three of those four are
judgements and are graded as judged criteria by the Evaluator role. The fourth
has a floor that can be checked by a machine, and this is it: a register of
words whose only job in a sentence is to attack somebody.

The check is deliberately modest about itself. Passing it does not mean an
edition is kind; it means the edition does not contain the specific vocabulary
that is never kind. The register lives in ``content/newspaper.json`` because
which words are out of bounds is an editorial decision, and
``config.newspaper.tone.disallow_snide_or_mean`` decides whether tripping it
blocks publication.

It is also modest about *whose* prose it grades. An editorial rule binds the
editor, and half the words in this paper were typed by mayors: an export is
free-form (spec #15) and reprinted exactly as written. Spec #30b settles what
happens when one of those contains a register term -- the edition publishes, the
words stand, and the paper marks them as the mayor's -- so the register runs
over the edition with its player-voice passages subtracted
(:mod:`newspaper.voice`). ``newspaper.tone.forbidden_register_scope`` is where
that is written down; see :data:`SCOPES`.

The other three flags are honoured elsewhere, and honoured for real rather than
echoed:

* ``allow_pointed_humor`` filters frames in :class:`newspaper.copy.Chooser`
* ``funny`` drops the editorial asides in :mod:`newspaper.departments`
* ``colorful`` selects the monochrome palette in :mod:`newspaper.svg`
"""

import re

from engine.errors import ConfigError, RuleViolation

from . import voice

#: What ``newspaper.tone.forbidden_register_scope`` may say, and what this paper
#: does about it. One entry, because spec #30b leaves one behaviour available:
#: the register is an editorial standard and the paper is answerable for its own
#: copy only. A config that asked for anything else -- "everything", say, which
#: is what this deliverable did before #30b -- is refused at load rather than
#: silently ignored, the same way ``publish_cadence`` and
#: ``player_identity_style`` are: the key exists so the scope is stated in the
#: one place config lives, not so a typo can quietly re-arm a gate against
#: players.
SCOPES = {
    "newspaper_voice": "the register is run over the paper's own copy; passages a "
                       "player typed are printed as written and marked as theirs "
                       "(spec #30b)",
}


class TonePolicy:
    """What this game's ``newspaper.tone`` block asks the paper to be."""

    __slots__ = (
        "funny", "colorful", "allow_pointed", "disallow_snide", "forbidden", "scope",
    )

    def __init__(self, config, copy):
        self.funny = config.require_bool("newspaper.tone.funny")
        self.colorful = config.require_bool("newspaper.tone.colorful")
        self.allow_pointed = config.require_bool("newspaper.tone.allow_pointed_humor")
        self.disallow_snide = config.require_bool("newspaper.tone.disallow_snide_or_mean")
        self.scope = self._resolve_scope(config)
        self.forbidden = tuple(copy.tone()["forbidden_register"])

    @staticmethod
    def _resolve_scope(config):
        scope = config.require_str("newspaper.tone.forbidden_register_scope")
        if scope not in SCOPES:
            raise ConfigError(
                "config.newspaper.tone.forbidden_register_scope is %r; this paper "
                "implements %s. Spec #30b: a player's freeform export is player "
                "voice, and publication proceeds without rejecting, rewriting or "
                "redacting it" % (scope, sorted(SCOPES))
            )
        return scope

    def describe(self):
        return {
            "funny": self.funny,
            "colorful": self.colorful,
            "allow_pointed_humor": self.allow_pointed,
            "disallow_snide_or_mean": self.disallow_snide,
            "forbidden_register_scope": {"value": self.scope, "means": SCOPES[self.scope]},
            "forbidden_register_terms": len(self.forbidden),
            "spec": "#30, #30b",
            "note": "The funny/colourful/pointed half of #30 is a judged criterion; "
                    "the snide-or-mean half has a mechanical floor, checked over this "
                    "edition's finished prose in the paper's own voice. A passage a "
                    "mayor typed is printed as typed and attributed to them (#30b).",
        }

    @staticmethod
    def pattern_for(term):
        """The register term as a pattern that matches words, not substrings.

        A leading word boundary, and deliberately no trailing one. The register
        is written with stems in it -- ``humiliat`` is there to catch humiliate,
        humiliated and humiliating with one entry -- so anchoring the end would
        quietly disarm them. Anchoring only the start is what actually matters:
        without it ``loser`` fires inside "closer" and ``liar`` inside
        "familiar", and since the paper reprints exports exactly as mayors wrote
        them (that is the one string it must reproduce verbatim), an ordinary
        word in an ordinary offer would block the edition it appeared in.
        """
        escaped = re.escape(term.lower())
        return (r"\b" + escaped) if term[:1].isalnum() else escaped

    def findings(self, text):
        """Every forbidden term this text contains, with its context."""
        lowered = text.lower()
        found = []
        for term in self.forbidden:
            for match in re.finditer(self.pattern_for(term), lowered):
                start = max(match.start() - 40, 0)
                found.append(
                    {
                        "term": term,
                        "context": text[start:match.end() + 40].replace("\n", " "),
                    }
                )
        return found

    def check(self, text, where="edition", player_voice=()):
        """Raise if the *paper's own* prose trips the register (spec #30, #30b).

        ``player_voice`` is every passage in this text that a mayor typed, as
        :func:`newspaper.voice.spans_in` reads them off the edition. They are
        masked out before the register runs, which is the whole of #30b's
        mechanics: the words still publish, byte for byte, and the paper is
        still held to its own standard in the sentences around them.
        """
        if not self.disallow_snide:
            return []
        found = self.findings(voice.editorial_only(text, player_voice))
        if found:
            raise RuleViolation(
                "%s trips content/newspaper.json's forbidden register in the paper's "
                "own voice, and config.newspaper.tone.disallow_snide_or_mean is true "
                "(spec #30): %r. Player-voice passages were exempt from this check "
                "(spec #30b), so this is the paper's wording to fix, not a mayor's"
                % (where, found)
            )
        return found
