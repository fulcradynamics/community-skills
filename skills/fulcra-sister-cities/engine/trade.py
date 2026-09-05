"""What a city is allowed to order, and what it is not (spec #13a).

Spec #13a, as the user decision of 2026-09-02 now has it, draws three lines
through the import needs rather than one. A need describes "actual, everyday
tradable things that any player can readily relate to and enjoy proposing or
exporting -- e.g. candy, soft drinks, books, snacks, music, games, clothes,
plants, pets, and small comforts", the city framing is "light social-game
flavour, not a requirement to role-play a real mayor or solve a complex
municipal problem", and a need "may not reduce to generic advice, civic
procurement, or specialist problem solving".

So there are three refusals, and they are genuinely different failures:

* **advice** -- "what should we do about the sweet shop" asks for counsel
  rather than a crate (``advice_markers``);
* **civic procurement** -- "purchase order: pumps, hose, gravel, budget line
  44-C" is a real order for real goods and still asks a player to behave like
  a council officer (``civic_markers``);
* **specialist problem solving** -- "trusses, ties, and a stamped calculation
  from somebody insured" is goods, is not procurement, and can still only be
  answered well by somebody with a professional qualification
  (``specialist_markers``).

The first was the 2026-08-31 decision's rule; the second and third are the
2026-09-02 decision's, and they are what retired schema 2's seed bank. All
three have to be enforced in three places or they are enforced nowhere:

* the **seeded list** (``content/import_needs.json``), checked when a game
  loads its content, so a seed that drifted back into advice refuses to start a
  game rather than turning up as round 7's notice;
* a **player-suggested** addition to the pool (spec #13, #33);
* an importing mayor's **freeform request** (spec #13), which is the door with
  a human on the other side of it and therefore the one that needs the clearest
  refusal message.

:class:`TradePolicy` is that one check, and its vocabulary is *content* rather
than code: the families, the supply verbs and all three marker lists live in
``content/import_needs.json``'s ``trade_policy`` block, because which phrasings
read as "send us a crate", which read as "tell us what to do" and which read as
"complete this requisition" are writing judgements, and writing judgements
belong in the content file with the writing.

The check is deliberately blunt in one direction and forgiving in the other. It
refuses on an explicit marker ("what should", "purchase order", "stamped
calculation"), and it requires an affirmative signal: a supply verb in the
exporter prompt, and a declared ``trade_family`` from a list that now enumerates
only everyday kinds of thing (sweets and drinks, snacks and bakes, reading and
listening, play, wear and comfort, plants and pets). Naming one is the closest a
machine gets to asserting "an ordinary person could enjoy filling this".

What it does not attempt is the judgement itself -- whether "the box your city
reaches for on a wet Tuesday" is relatable enough is for the Evaluator's #13a
and #33 review, and for the mayors, who will vote with their crates.
"""

import re

from .errors import ContentError, TradeRefused

#: Fields a need must carry whatever door it came through. ``exporter_prompt``
#: and ``excess_flavor`` are filled from the freeform defaults when a mayor does
#: not write their own, which is why they are not required *of the mayor* -- see
#: :meth:`TradePolicy.freeform_need`.
REQUIRED_NEED_FIELDS = ("id", "category", "trade_family", "title", "need_brief",
                        "exporter_prompt")


class TradePolicy:
    """``content/import_needs.json``'s ``trade_policy`` block, as a check."""

    def __init__(self, doc):
        if not isinstance(doc, dict) or not doc:
            raise ContentError(
                "the import-need file has no trade_policy block; spec #13a's rule "
                "about what may be ordered is content, and the engine will not "
                "invent one"
            )
        #: The block as written, so a hand-made content fixture (a test's tiny
        #: pool, say) can borrow the real policy rather than restate it and
        #: quietly drift away from the rule it is meant to be obeying.
        self.doc = dict(doc)
        self.families = dict(doc.get("families") or {})
        self.rules = list(doc.get("rules") or [])
        self.supply_verbs = [v.lower() for v in (doc.get("supply_verbs") or [])]
        self.advice_markers = [m.lower() for m in (doc.get("advice_markers") or [])]
        self.civic_markers = [m.lower() for m in (doc.get("civic_markers") or [])]
        self.specialist_markers = [
            m.lower() for m in (doc.get("specialist_markers") or [])
        ]
        self.freeform = dict(doc.get("freeform") or {})
        if not self.families:
            raise ContentError("trade_policy.families is empty (spec #13a)")
        if not self.supply_verbs:
            raise ContentError("trade_policy.supply_verbs is empty (spec #13a)")
        if not self.advice_markers:
            raise ContentError("trade_policy.advice_markers is empty (spec #13a)")
        if not self.civic_markers:
            raise ContentError(
                "trade_policy.civic_markers is empty; spec #13a (2026-09-02) "
                "refuses civic-procurement needs, and the phrases that mark one "
                "are content"
            )
        if not self.specialist_markers:
            raise ContentError(
                "trade_policy.specialist_markers is empty; spec #13a (2026-09-02) "
                "refuses needs that only a specialist could answer, and the "
                "phrases that mark one are content"
            )
        self._verb_re = re.compile(
            r"\b(?:%s)\b" % "|".join(re.escape(verb) for verb in self.supply_verbs),
            re.IGNORECASE,
        )

    # -- the check --------------------------------------------------------

    def check_need(self, need, where=None):
        """Refuse a need that is not an order for goods or services.

        Returns the need unchanged so this can be used inline. Raises
        :class:`~engine.errors.TradeRefused` with the offending phrase.
        """
        where = where or need.get("id") or "an import need"
        for field in REQUIRED_NEED_FIELDS:
            if not need.get(field):
                raise TradeRefused(
                    "%s is missing %r; every import need names a category, a trade "
                    "family and what is being bought (spec #13, #13a)" % (where, field),
                    where=where,
                )

        family = need["trade_family"]
        if family not in self.families:
            raise TradeRefused(
                "%s declares trade_family %r; spec #13a's everyday kinds of tradable "
                "thing are %s" % (where, family, sorted(self.families)),
                where=where,
                phrase=family,
            )

        wording = " ".join(
            [need.get("title", ""), need["need_brief"], need["exporter_prompt"]]
        )

        marker = self.advice_marker_in(wording)
        if marker:
            raise TradeRefused(
                "%s reads as a request for advice rather than an order for goods -- it "
                "says %r. Spec #13a: name the everyday thing the city would like sent "
                "(candy, soft drinks, books, snacks, music, games, clothes, plants, "
                "pets, a small comfort) and let the other mayors decide what to put in "
                "the crate." % (where, marker),
                where=where,
                phrase=marker,
            )

        marker = self.civic_marker_in(wording)
        if marker:
            raise TradeRefused(
                "%s reads as civic procurement rather than an ordinary order -- it says "
                "%r. Spec #13a (2026-09-02): the city is light social-game flavour, not "
                "a job. Ask for something a person would like a crate of, not something "
                "a council would raise a purchase order for." % (where, marker),
                where=where,
                phrase=marker,
            )

        marker = self.specialist_marker_in(wording)
        if marker:
            raise TradeRefused(
                "%s could only be answered well by a specialist -- it says %r. Spec #13a "
                "(2026-09-02): no player should need civic or professional expertise to "
                "make a fun offer, so order the everyday version of this instead."
                % (where, marker),
                where=where,
                phrase=marker,
            )

        if not self._verb_re.search(need["exporter_prompt"]):
            raise TradeRefused(
                "%s's exporter prompt asks for no consignment; it must use one of %s "
                "so an exporting mayor is being asked to supply something (spec #13a, "
                "#15)" % (where, self.supply_verbs),
                where=where,
            )
        return need

    def advice_marker_in(self, text):
        """The first advice marker in ``text``, or ``None`` (spec #13a)."""
        return self._marker_in(self.advice_markers, text)

    def civic_marker_in(self, text):
        """The first civic-procurement marker in ``text``, or ``None``.

        Spec #13a's 2026-09-02 half. Kept a separate method rather than folded
        into :meth:`advice_marker_in` because the two failures want different
        things said to the mayor: an advice request has to be re-filed as an
        order, whereas a procurement notice is already an order and simply has
        to stop being one a council would file.
        """
        return self._marker_in(self.civic_markers, text)

    def specialist_marker_in(self, text):
        """The first specialist-expertise marker in ``text``, or ``None``."""
        return self._marker_in(self.specialist_markers, text)

    def refusal_marker_in(self, text):
        """The first marker of any of the three kinds, as ``(kind, phrase)``.

        What a reporting pass wants: a caller checking whether a rendered prompt
        is playable does not care which list caught it until it has to say so.
        """
        for kind, markers in (
            ("advice", self.advice_markers),
            ("civic_procurement", self.civic_markers),
            ("specialist", self.specialist_markers),
        ):
            found = self._marker_in(markers, text)
            if found:
                return kind, found
        return None, None

    def _marker_in(self, markers, text):
        """The first of ``markers`` present in ``text``, or ``None``.

        ``{city}`` in a marker stands for a city name, which is either the
        unrendered placeholder or a capitalised word -- "tell {city} what" has
        to catch both the seed as written and a mayor who typed out their own
        city. It deliberately does *not* stand for any word at all: that would
        make "fix {city}" fire on "the crew who fix it in place", which is a
        sentence about a consignment and not about advice.
        """
        text = text or ""
        for marker in markers:
            if "{city}" not in marker:
                # Whole words: a brief that mentions "the decision that explains
                # the pipes" is describing its stock, not asking for an
                # explanation, and only a word-boundary match can tell the two
                # apart. The same boundary is what lets "postcard" past a
                # "post" verb and "structurally ambitious" past "structural
                # engineer".
                if re.search(r"\b%s\b" % re.escape(marker), text, re.IGNORECASE):
                    return marker
                continue
            pattern = r"\b%s" % re.escape(marker).replace(
                re.escape("{city}"), r"(?P<city>\S+)"
            )
            for found in re.finditer(pattern, text, re.IGNORECASE):
                stood_in = found.group("city")
                if stood_in.lower() == "{city}" or stood_in[:1].isupper():
                    return marker
        return None

    # -- freeform requests -------------------------------------------------

    def freeform_need(self, request, need_id, proposed_by_city=None):
        """A mayor's own order, in the same shape as a seed (spec #13).

        The mayor supplies what they are buying; this fills in the parts every
        need has -- an id, an exporter prompt, an excess flavour for the endgame
        -- from the content file's ``trade_policy.freeform`` defaults rather
        than from anything hardcoded here. The result goes through
        :meth:`check_need` like any seed, which is the whole point: a freeform
        request is a first-class import need, not a bypass.
        """
        if not isinstance(request, dict):
            raise TradeRefused(
                "a freeform import request is a mapping with %s; got %r"
                % (list(self.freeform.get("required_fields") or ()), type(request).__name__),
                where=need_id,
            )
        missing = [
            field for field in (self.freeform.get("required_fields") or ())
            if not request.get(field)
        ]
        if missing:
            raise TradeRefused(
                "this freeform import request is missing %s. %s"
                % (missing, self.freeform.get("note_to_mayor", "")),
                where=need_id,
            )
        need = {
            "id": need_id,
            "category": request["category"],
            "trade_family": request["trade_family"],
            "title": request["title"],
            "need_brief": request["need_brief"],
            "exporter_prompt": request.get("exporter_prompt")
            or self.freeform.get("default_exporter_prompt", ""),
            "excess_flavor": request.get("excess_flavor")
            or self.freeform.get("default_excess_flavor", ""),
            "tags": list(request.get("tags") or ["freeform"]),
            "source": "freeform",
        }
        if proposed_by_city:
            need["requested_by_city"] = proposed_by_city
        return self.check_need(need, where="the freeform request %s" % need_id)

    def freeform_id(self, ordinal):
        return "%s-%02d" % (self.freeform.get("id_prefix", "need-freeform"), ordinal)

    # -- reporting ---------------------------------------------------------

    def describe(self):
        """What a facilitator's agent shows a mayor who is about to order."""
        return {
            "families": {
                key: {"label": value.get("label"), "examples": list(value.get("examples") or ())}
                for key, value in self.families.items()
            },
            "rules": list(self.rules),
            "note_to_mayor": self.freeform.get("note_to_mayor"),
            "required_fields": list(self.freeform.get("required_fields") or ()),
            # Named so a facilitator's agent can say *why* an order came back,
            # in the mayor's own terms, rather than quoting a regex at them.
            "refusals": [
                "advice, opinions or ideas rather than an order",
                "civic procurement -- purchase orders, tenders, budget lines, permits",
                "anything only a specialist could answer well",
            ],
            "spec": "#13, #13a",
        }
