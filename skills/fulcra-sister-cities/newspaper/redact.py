"""Who the paper may name, and how (spec #21, #28).

Spec #28 says players are identified in the newspaper by city and office only,
never by real name or handle, and that the policy is configurable. Spec #21 says
a non-winning export's origin city is never exposed -- not during the round and
not after it. Those are different rules with different enforcement:

* the handle rule is *absolute over the whole edition*. There is no place in a
  newspaper where a handle is correct, so the check is "does this string appear
  anywhere at all", including in the rendered markdown and in the image.
* the origin rule is *structural*. The engine already makes a losing export's
  city unavailable without a deliberate, reasoned ledger read
  (:mod:`engine.state`), so the paper cannot print one by accident. What it
  *can* do by accident is reprint an export whose own text names its sender --
  a mayor who signed their work -- and publishing that would leak the origin
  just as thoroughly as printing a field would. So a declined export is
  reprinted only if its text names no city in the game
  (:func:`may_reprint_declined`), and the paper says, in character, that it has
  withheld one.

Both are then re-checked over the finished edition by
:func:`assert_edition_is_redacted`, which leans on :mod:`engine.audit` rather
than reimplementing it -- the audit already walks arbitrary payloads, and
running the same tripwire the engine's own tests use is the point.
"""

import re

from engine import audit
from engine.content import normalize_city
from engine.errors import ConfigError, RuleViolation

#: The identity styles this paper knows how to print (spec #28). An unknown
#: style is refused rather than treated as "print whatever": the config key
#: exists to make the paper *more* anonymous later, and a typo in it must not be
#: the thing that makes it less.
IDENTITY_STYLES = {
    "city_mayor_only": {
        "prints": "the city's name and the office of its mayor",
        "never_prints": "a real name, a handle, or a player id",
        "spec": "#28",
    },
}

#: Block role used by :mod:`newspaper.departments` for the reprinted losing
#: exports. Named here because :func:`assert_edition_is_redacted` is what makes
#: the role mean anything.
DECLINED_ROLE = "declined_exports"


def resolve_identity_style(config):
    style = config.require_str("newspaper.player_identity_style")
    try:
        return style, IDENTITY_STYLES[style]
    except KeyError:
        raise ConfigError(
            "config.newspaper.player_identity_style is %r; this paper implements %s "
            "(spec #28)" % (style, sorted(IDENTITY_STYLES))
        )


def cities_named_in(text, cities):
    """Which of ``cities`` this text names, diacritics and case ignored.

    Matching is done on the normalised forms the rest of the engine compares
    cities by (:func:`engine.content.normalize_city`), so "Reykjavik" in an
    export is caught as readily as "Reykjavík".
    """
    if not isinstance(text, str) or not text.strip():
        return []
    haystack = normalize_city(text) if text.strip() else ""
    found = []
    for city in cities:
        needle = normalize_city(city)
        if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(needle), haystack):
            found.append(city)
    return found


def comparable_export(text):
    """An export text reduced to what a reader would recognise it by.

    Whitespace collapsed and case folded, and nothing else -- this is used to
    ask "has a reader seen this exact sentence somewhere else in the paper",
    which is a question about the words, not about the typography.
    """
    return " ".join(str(text).split()).casefold()


def attributed_export_texts(engine, through_round=None):
    """Export texts the paper has printed a sender's name against, by ``through_round``.

    Winners, and only winners: a chosen export's origin is public (spec #18,
    #20), Arrivals names it round by round, and the last edition's twist article
    quotes it under the sending city's name (spec #31).

    Which makes the *text itself* an identifier, and that is the leak this set
    exists to close. The same words can be sent to two different needs and win
    one and lose the other -- the sample game does exactly this -- and a paper
    that quotes "Hobart wrote that" in one column and reprints the identical
    sentence as an unattributed declined offer in another has told the reader
    whose the declined one was just as plainly as a byline would. So a declined
    offer that reads exactly like an attributed one is withheld (spec #21).

    ``through_round`` is why this takes an argument at all, and the reasoning is
    spec #27's. An edition is a historical document: rebuild round 5 in round 12
    and it must come out byte-for-byte as it did when it was published, or the
    archive is an overwrite pretending to be an archive. So a round edition asks
    only about winners resolved *by that round* -- a set that is fixed the moment
    the round closes and never grows again. The final edition passes ``None`` and
    gets the whole game, which is both safe and necessary: it is published once,
    from a finished game, and it is the edition that prints game-wide reprints
    and game-wide attributions on the same page.

    What this deliberately does not do is reach forward. An offer reprinted
    unattributed in round 5 may be matched by an attribution the paper prints in
    round 9, and no rule available here can prevent that: closing it would mean
    either rewriting round 5 (forbidden by #27) or withholding round 9's winner
    (required by #18 and #20). The last edition closes it for everything the last
    edition itself prints, and ``docs/m7-endgame.md`` records the residue.
    """
    texts = set()
    for need in engine.needs.values():
        if through_round is not None and (
            need.resolved_round is None or need.resolved_round > through_round
        ):
            continue
        for submission in engine.submissions_for(need.need_key):
            if submission.is_winner:
                texts.add(comparable_export(submission.text))
    return texts


def may_reprint_declined(text, cities, attributed=()):
    """Whether a losing export may be printed verbatim (spec #21).

    The paper reprints losing exports because they are the best writing in the
    game and because "The Excess" (see ``NAME.md``) needs them. Two things stop
    it reprinting one:

    * the text names a city. The export text is the one string the paper must
      reproduce exactly, so the only way to keep the origin blind is to decline
      to reproduce it at all.
    * the text is one the paper attributes to a city somewhere else
      (:func:`attributed_export_texts`). Printing it unattributed here would not
      make it anonymous; it would just make the attribution one column away.
    """
    if cities_named_in(text, cities):
        return False
    return comparable_export(text) not in set(attributed)


def find_printed_identities(engine, strings):
    """Handles and player ids written into any of ``strings`` (spec #28).

    :func:`engine.audit.find_handle_leaks` matches a whole string, which catches
    a ``{"tip_from": "@ada"}`` field but not a handle written into the middle of
    a sentence -- and a sentence is exactly where a handle would end up. So this
    matches as a substring on a word boundary, and it is a function rather than
    a block inside :func:`assert_edition_is_redacted` because the edition is not
    the only rendering of the paper: :mod:`hosting.guard` runs the same check
    over every byte it is about to publish, and running a *second* handle check
    written a second way is how the two would drift.
    """
    problems = {}
    for label, needles in (
        ("handles_printed", sorted(p.handle for p in engine.players.values() if p.handle)),
        ("player_ids_printed", sorted(engine.players)),
    ):
        hits = sorted(
            {
                needle
                for needle in needles
                for text in strings
                if re.search(
                    r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(needle), text
                )
            }
        )
        if hits:
            problems[label] = hits
    return problems


def assert_edition_is_redacted(engine, edition, rendered=None):
    """Raise unless the edition obeys #21, #22, #25 and #28.

    ``rendered`` is the markdown (and any other flat text, such as the SVG) the
    edition was rendered to. It is checked as well as the structured payload,
    because a leak that only exists in the prose is still in the paper.
    """
    payload = {"edition": edition}
    if rendered:
        payload["rendered"] = list(rendered) if isinstance(rendered, (list, tuple)) else [rendered]

    # Handles, ledger misuse, extra timers, and any node tying a non-winning
    # submission to its exporter.
    audit.assert_blind(engine, payload)
    # Anything published that config.json says to withhold (#22, #25).
    audit.assert_exposure_policy(engine, payload)

    strings = list(_all_strings(payload))
    problems = find_printed_identities(engine, strings)

    cities = [p.city for p in engine.players.values()]
    # Scoped exactly as the writers scope it, so the tripwire checks the rule the
    # edition was written under rather than a stricter one it could not have
    # obeyed without reaching into rounds that had not happened yet.
    attributed = attributed_export_texts(
        engine, through_round=None if edition.get("endgame") else edition.get("round")
    )
    for item in _declined_items(edition):
        named = cities_named_in(item, cities)
        if named:
            problems.setdefault("declined_export_names_a_city", []).append(
                {"export": item, "cities": named, "spec": "#21"}
            )
        if comparable_export(item) in attributed:
            # The filter in may_reprint_declined should have caught this. The
            # check is here as well because a department that forgot to pass the
            # attributed set would otherwise publish the leak quietly, and a
            # department is exactly the kind of thing a later milestone adds.
            problems.setdefault("declined_export_matches_an_attributed_one", []).append(
                {
                    "export": item,
                    "why": "the same text is printed elsewhere with its sending city "
                           "named, because it won a different need; reprinting it "
                           "unattributed here identifies it by matching",
                    "spec": "#21",
                }
            )

    if problems:
        raise RuleViolation(
            "identity redaction failed for edition %r: %r"
            % (edition.get("round"), problems)
        )
    return True


def _all_strings(node):
    for value in walk(node):
        if isinstance(value, str):
            yield value


def walk(node):
    """Every node in an edition payload, keys included.

    Public because it is the traversal both payload-wide rules use: this module
    asks which *strings* are in the paper (spec #21, #28), and
    :mod:`newspaper.voice` asks which *blocks* declare a player's words in it
    (spec #30b). Two checks walking two different hand-written traversals is how
    one of them ends up not seeing a department the other does.
    """
    yield node
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from walk(value)


def _declined_items(edition):
    """Every reprinted losing export in the edition, by its block role."""
    out = []
    for value in walk(edition):
        if isinstance(value, dict) and value.get("role") == DECLINED_ROLE:
            out.extend(item for item in value.get("items", []) if isinstance(item, str))
    return out
