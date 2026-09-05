"""Whose words are on the page, and which of them the paper is answerable for.

Spec #30 makes the paper's own copy funny, colourful, pointed and never mean,
and :mod:`newspaper.tone` puts a mechanical floor under the last of those. Spec
#30b then draws the line that floor stops at:

    A player's freeform export is player voice, not newspaper editorial voice.
    If its exact text would trip the editorial tone gate, publication still
    proceeds: do not reject, rewrite, redact, or halt the game because of it.

That is not a softening of #30. It is a statement about *authorship*. A mayor
writes an offer (spec #15: free-form text, nothing between the mayor and the
page), the paper reprints it, and a register term inside it is the mayor's word
choice rather than the paper's editorial line. Refusing the edition over it --
which is what this deliverable did until #30b was decided -- punished the whole
table for one player's adjective, and refusing the *submission* would have made
spec #15's "free-form" mean "free-form within a word list nobody was shown".

So the edition declares which passages a player wrote, in two shapes:

``voice: "player"``
    the block is nothing but a player's own wording -- the winning offer quoted
    in Arrivals, the reprinted declined offers, the twist article's quotes. It
    carries a ``cite`` so the page says whose words they are (or, for a declined
    offer, says plainly that the paper is not saying: spec #21 outranks the
    attribution).
``player_spans: [...]``
    a paper sentence that quotes a player inside itself -- "the world kept this,
    from Bergen: *...*", an outlier's answer on The Wire. The sentence is the
    paper's and is gated; the span within it is the player's and is not.

:func:`spans_in` is what the gate subtracts, :func:`editorial_only` is the
subtraction, and :func:`assert_spans_are_player_text` is what stops the
exemption being useful to anybody but a player: every declared span must be
text some player actually submitted to this game. Without that check, a
department could mark its own snide sentence ``voice: "player"`` and walk it
straight past spec #30.
"""

from engine.errors import RuleViolation

from .redact import comparable_export, walk

#: ``block["voice"]`` for a block that is wholly a player's own words.
PLAYER = "player"

#: What a masked span leaves behind for the register to read. Deliberately not
#: an empty string: the paper's sentence either side of a quote still has to
#: scan as a sentence, and a gap that closed up could join two words into a
#: register term that neither of them is.
MASK = "[player voice]"


def cite(copy, chooser, family, key, values=None):
    """The line that says a quotation is a mayor's words and not the desk's.

    One function for every department that quotes a player, so the paper cannot
    cite a winning offer in one column and print an unattributed quotation in
    another. The frames are in ``content/newspaper.json``'s ``player_voice``
    block; the families that cite a *declined* offer take no substitutions at
    all, because a cite that could name a city is a cite that eventually will
    (spec #21).
    """
    return chooser.line(
        copy.player_voice()[family], key, "player_voice.%s" % family, values,
    )


def quoted(text, cite_line):
    """A block that is a player's wording and nothing else."""
    return {"kind": "quote", "text": text, "voice": PLAYER, "cite": cite_line}


def listed(items, cite_line, role=None):
    """A list block whose every item is a player's wording."""
    block = {"kind": "list", "items": list(items), "voice": PLAYER, "cite": cite_line}
    if role is not None:
        block["role"] = role
    return block


def within(block, *spans):
    """Declare the player-written substrings inside a block the paper wrote."""
    declared = [span for span in spans if isinstance(span, str) and span.strip()]
    if declared:
        block["player_spans"] = declared
    return block


def spans_in(edition):
    """Every passage in this edition that a player wrote, not the paper.

    Walks the payload rather than taking a list from the writers, for the same
    reason :mod:`newspaper.redact` walks it: the check has to see the paper that
    was actually assembled, including the departments a later milestone adds.
    """
    found = []
    for node in walk(edition):
        if not isinstance(node, dict):
            continue
        if node.get("voice") == PLAYER:
            if isinstance(node.get("text"), str):
                found.append(node["text"])
            found.extend(
                item for item in node.get("items") or () if isinstance(item, str)
            )
        found.extend(
            span for span in node.get("player_spans") or () if isinstance(span, str)
        )
    return found


def editorial_only(text, spans):
    """``text`` with every player-written span replaced by :data:`MASK`.

    Longest span first, so a span that contains another does not leave the
    shorter one's tail behind as though the paper had written it.

    A span is also masked line by line, because the renderers do not always
    reproduce a multi-line passage as one run of characters: a quotation is
    printed with ``> `` in front of every line (:mod:`newspaper.render`), so a
    two-line offer never appears in the rendered text as the string the payload
    holds. Matching its lines as well is what keeps a mayor who pressed return
    inside spec #30b rather than outside it.
    """
    masked = text
    for span in sorted(_maskable(spans), key=len, reverse=True):
        masked = masked.replace(span, MASK)
    return masked


def _maskable(spans):
    """Each span, plus its own lines when it has more than one."""
    out = set()
    for span in spans:
        if not isinstance(span, str) or not span.strip():
            continue
        out.add(span)
        lines = span.splitlines()
        if len(lines) > 1:
            out.update(line.strip() for line in lines if line.strip())
    return out


def player_texts(engine):
    """Everything in this game that a player wrote in their own words.

    Exports (spec #15) and answers to the mayoral questions (spec #24). Both are
    typed by a player and printed as typed, and both are therefore player voice
    under #30b. Nothing else qualifies: a city name is a pick from a gazetteer,
    an import order is a slate choice or a request the content policy vets
    (spec #13a), and neither is a passage the paper reprints as somebody's
    prose.
    """
    texts = {comparable_export(s.text) for s in engine.submissions.values()}
    for record in engine.rounds.values():
        texts.update(comparable_export(answer) for answer in record.answers.values())
    return texts


def assert_spans_are_player_text(engine, edition, spans):
    """Raise unless every span claiming #30b's exemption really is a player's.

    The exemption is the one hole in spec #30's floor, so the only thing allowed
    through it is text a player typed. A department that marked its own line as
    player voice -- by mistake or to get a joke past the register -- fails here
    rather than publishing.
    """
    written = player_texts(engine)
    unknown = [span for span in spans if comparable_export(span) not in written]
    if unknown:
        raise RuleViolation(
            "edition %r claims spec #30b's player-voice exemption for %d passage(s) "
            "no player in this game wrote: %r. The exemption covers exports and "
            "mayoral answers as typed; the paper's own copy stays inside spec #30"
            % (edition.get("round"), len(unknown), unknown)
        )
    return True
