"""The Daily Manifest's standing departments.

One writer per department, each taking the round's briefing from
:func:`engine.views.round_briefing` and returning printable blocks. The
departments and what they carry are declared in ``NAME.md``; the sentences are
in ``content/newspaper.json``; the mapping from a round's facts to which
sentence gets printed is here.

    Wanted                      the import need that opened   (lockstep OPEN)
    Sealed Bids                 the export window that closed (lockstep CLOSE)
    Arrivals                    the winner, or the fallback   (lockstep RESOLVE)
    The Wire                    the mayoral question item     (see newspaper.wire)
    The Ledger                  cumulative profit, if config exposes it
    Corrections & Clarifications the paper's own errors, at full volume

Three rules run through all of them:

* **A department that has nothing true to say says nothing.** The Ledger is
  absent when ``economy.leaderboard_visible_in_newspaper`` is false; The Wire is
  absent when there is no publishable item; Wanted prints a written-out
  explanation on the drain rounds when the rotation has no city left to ask.
  None of them improvises.
* **Sealed Bids is written to have nothing to leak.** It reports a count and a
  desk. Naming who sent what there would end blind voting before the vote
  (spec #18), so the department never receives that information in the first
  place -- :func:`engine.views.need_briefing` does not put it in the briefing
  while a need is unresolved.
* **Arrivals reprints losing exports and never attributes them.** A losing
  export whose own text names a city is withheld rather than reprinted, because
  reproducing it would expose the origin as surely as printing a field would
  (spec #21, see :func:`newspaper.redact.may_reprint_declined`).
* **An offer is printed as the mayor typed it, and cited to them.** Both the
  winning quotation and the declined reprints are marked as player voice
  (:mod:`newspaper.voice`), which is what carries them past the editorial
  register unaltered and what puts a line on the page saying whose words they
  are -- or, for a declined offer, saying that the paper is not telling
  (spec #30b, #21).
"""

from datetime import datetime

from engine.state import EVEN_SPLIT, RAMP_UP, WINNER_PICK

from . import voice, wire
from .copy import count_word, counted
from .redact import DECLINED_ROLE, attributed_export_texts, may_reprint_declined
from .wire import join_phrases


def long_date(iso):
    """``2026-09-03T12:00:00+00:00`` -> ``Thursday, 3 September 2026``."""
    when = datetime.fromisoformat(iso)
    return "%s, %d %s" % (when.strftime("%A"), when.day, when.strftime("%B %Y"))


def deadline_stamp(iso):
    """``2026-09-04T12:00:00+00:00`` -> ``4 September, 12:00 UTC``."""
    when = datetime.fromisoformat(iso)
    return "%d %s, %s UTC" % (when.day, when.strftime("%B"), when.strftime("%H:%M"))


class Departments:
    """Writes one edition's departments. Holds no state between editions."""

    def __init__(self, copy, chooser, tone, prose_limits):
        self.copy = copy
        self.chooser = chooser
        self.tone = tone
        self.limits = prose_limits

    # -- helpers ----------------------------------------------------------

    def _dept(self, name):
        return self.copy.department(name)

    def _line(self, frames, key, where, values=None):
        return self.chooser.line(frames, key, where, values)

    def _cite(self, family, key, values=None):
        """:func:`newspaper.voice.cite`, with this department's copy and chooser."""
        return voice.cite(self.copy, self.chooser, family, key, values)

    def _standfirst(self, department, name, key, values=None):
        """The department's opening line, filled from the same table as its body.

        A standfirst is a frame like any other: ``_placeholders`` in
        ``content/newspaper.json`` declares substitutions per department, not per
        family, so a standfirst rendered against an empty dict could not use the
        substitutions the content file says it may -- and because which frame is
        chosen depends on game state, the mismatch would surface not when the
        frame was written but in whichever edition first happened to choose it.
        """
        return {
            "kind": "standfirst",
            "text": self._line(
                department["standfirsts"], key, "departments.%s.standfirsts" % name,
                values,
            ),
        }

    # -- Wanted (lockstep OPEN) -------------------------------------------

    def wanted(self, briefing):
        department = self._dept("wanted")
        opened = briefing["opened"]
        round_index = briefing["round"]

        if opened is None:
            # A drain round: the rotation has run out of cities to ask. Spec #9's
            # lockstep still ran; there was simply nothing to open.
            absent = department["nothing_opened"]
            return {
                "id": "wanted",
                "title": department["title"],
                "blocks": [
                    {
                        "kind": "standfirst",
                        "text": self._line(
                            absent["standfirsts"], (round_index, "no_open"),
                            "departments.wanted.nothing_opened.standfirsts",
                        ),
                    },
                    {
                        "kind": "para",
                        "text": self._line(
                            absent["lines"], (round_index, "no_open_line"),
                            "departments.wanted.nothing_opened.lines",
                        ),
                    },
                ],
                "provenance": {"opened": None, "spec": "#9"},
            }

        key = (round_index, opened["need"])
        values = {
            "city": opened["importing_city"],
            "mayor": opened["importing_mayor"],
            "title": opened["title"],
            "category_label": opened["category_label"],
            "brief": opened["need_brief"],
            "prompt": opened["exporter_prompt"],
            "deadline": deadline_stamp(briefing["ends_at"]),
        }
        blocks = [
            self._standfirst(department, "wanted", key + ("standfirst",), values),
            {"kind": "heading", "level": 3, "text": opened["title"]},
            {
                "kind": "para",
                "text": self._line(
                    department["notice_frames"], key + ("notice",),
                    "departments.wanted.notice_frames", values,
                ),
            },
            # The brief is the seeded content's own prose, printed as written.
            # The paper frames it; it does not rewrite it.
            {"kind": "para", "text": opened["need_brief"]},
            {
                "kind": "para",
                "text": self._line(
                    department["prompt_frames"], key + ("prompt",),
                    "departments.wanted.prompt_frames", values,
                ),
            },
            {
                "kind": "para",
                "text": self._line(
                    department["rules_frames"], key + ("rules",),
                    "departments.wanted.rules_frames", values,
                ),
            },
        ]
        blocks.extend(self._asides(department, opened, key))
        return {
            "id": "wanted",
            "title": department["title"],
            "blocks": blocks,
            "provenance": {
                "need": opened["need"],
                "category": opened["category"],
                "rotation": opened["rotation"],
                "spec": "#9, #13, #14",
            },
        }

    def _asides(self, department, opened, key):
        """The editorial aside, or nothing at all when told not to be funny.

        ``newspaper.tone.funny`` false does not mean "joke more quietly" -- it
        means the paper reports and stops. Attempting a lower-key joke would be
        the paper ignoring its instructions (spec #30, config-driven).
        """
        if not self.tone.funny or self.limits["asides"] < 1:
            return []
        asides = department["asides"]
        pool = list(asides["by_category"].get(opened["category"], []))
        pool.extend(asides["general"])
        lines = self.chooser.lines(
            pool, key + ("aside",), "departments.wanted.asides",
            count=self.limits["asides"],
        )
        return [{"kind": "aside", "text": line} for line in lines]

    # -- Sealed Bids (lockstep CLOSE) -------------------------------------

    def sealed_bids(self, briefing):
        department = self._dept("sealed_bids")
        closed = briefing["closed"]
        round_index = briefing["round"]

        if closed is None:
            return {
                "id": "sealed_bids",
                "title": department["title"],
                "blocks": [
                    {
                        "kind": "para",
                        "text": self._line(
                            department["nothing_closed"]["lines"],
                            (round_index, "no_close"),
                            "departments.sealed_bids.nothing_closed.lines",
                        ),
                    }
                ],
                "provenance": {"closed": None, "spec": "#9"},
            }

        frames = department["frames"]
        count = closed["submission_count"]
        key = (round_index, closed["need"])
        # The mayor is looked up from the briefing's own opened/closed record, so
        # this department never touches the roster or the submissions.
        values = {
            "city": closed["importing_city"],
            "mayor": "the Mayor of %s" % closed["importing_city"],
            "count": count,
            "count_word": count_word(count),
        }
        family = "none" if count == 0 else ("one" if count == 1 else "many")
        blocks = [
            {
                "kind": "para",
                "text": self._line(
                    frames[family], key + (family,),
                    "departments.sealed_bids.frames.%s" % family, values,
                ),
            }
        ]
        if count:
            blocks.append(
                {
                    "kind": "para",
                    "text": self._line(
                        frames["blindness_note"], key + ("blind",),
                        "departments.sealed_bids.frames.blindness_note", values,
                    ),
                }
            )
            blocks.append(
                {
                    "kind": "para",
                    "text": self._line(
                        frames["deadline_note"], key + ("deadline",),
                        "departments.sealed_bids.frames.deadline_note", values,
                    ),
                }
            )
        return {
            "id": "sealed_bids",
            "title": department["title"],
            "blocks": blocks,
            "provenance": {
                "need": closed["need"],
                "offers": count,
                "origins_available_to_this_department": False,
                "spec": "#9, #18",
            },
        }

    # -- Arrivals (lockstep RESOLVE) --------------------------------------

    def arrivals(self, briefing, cities, attributed=()):
        """This round's resolution, with the losing offers reprinted unattributed.

        ``attributed`` is every export text the paper names a sender for
        anywhere in the game (:func:`newspaper.redact.attributed_export_texts`).
        A declined offer that reads exactly like one of those is withheld rather
        than reprinted: the same words can win one need and lose another, and
        the reader who saw the winning one credited does not need this one
        credited to know whose it is (spec #21).
        """
        department = self._dept("arrivals")
        resolved = briefing["resolved"]
        round_index = briefing["round"]

        if resolved is None:
            return {
                "id": "arrivals",
                "title": department["title"],
                "blocks": [
                    {
                        "kind": "para",
                        "text": self._line(
                            department["nothing_resolved"]["lines"],
                            (round_index, "no_resolve"),
                            "departments.arrivals.nothing_resolved.lines",
                        ),
                    }
                ],
                "provenance": {"resolved": None, "spec": "#9"},
            }

        resolution = resolved["resolution"]
        mode = resolution["mode"]
        awards = resolved["profit_awarded"]
        roll = resolution["roll"]
        key = (round_index, resolved["need"], mode)
        values = {
            "city": resolved["importing_city"],
            "mayor": resolved["importing_mayor"],
            "count": resolution["submission_count"],
            "count_word": count_word(resolution["submission_count"]),
            "dice": join_phrases([str(die) for die in roll["dice"]]),
            "roll_expression": roll["expression"],
        }

        writer = {
            WINNER_PICK: self._arrivals_winner,
            RAMP_UP: self._arrivals_ramp_up,
            EVEN_SPLIT: self._arrivals_even_split,
        }[mode]
        blocks, extra = writer(
            department[mode], resolved, awards, values, key, cities, attributed,
        )
        provenance = {
            "need": resolved["need"],
            "mode": mode,
            "spec": resolution["spec"],
            "roll": roll,
            "awarded": [(award["city"], award["profit"]["display"]) for award in awards],
        }
        provenance.update(extra)
        return {
            "id": "arrivals",
            "title": department["title"],
            "blocks": blocks,
            "provenance": provenance,
        }

    def _arrivals_winner(self, frames, resolved, awards, values, key, cities, attributed):
        winner = next(s for s in resolved["submissions"] if s["won"])
        values = dict(
            values,
            export=winner["export"],
            winner_city=winner["origin_city"],
            winner_mayor="the Mayor of %s" % winner["origin_city"],
            profit=awards[0]["profit"]["display"],
        )
        blocks = [
            {"kind": "para", "text": self._line(
                frames["headlines"], key + ("head",), "arrivals.winner_pick.headlines", values)},
            {"kind": "para", "text": self._line(
                frames["lead"], key + ("lead",), "arrivals.winner_pick.lead", values)},
            # The one string in the paper that is not the paper's: a winning
            # offer as its mayor typed it, cited to them and exempt from the
            # editorial register (spec #30b, #18).
            voice.quoted(
                winner["export"],
                self._cite("winner_quote", key + ("cite",),
                           {"mayor": values["winner_mayor"]}),
            ),
            {"kind": "para", "text": self._line(
                frames["attribution"], key + ("attr",),
                "arrivals.winner_pick.attribution", values)},
        ]
        blocks.extend(self._declined(frames, resolved, values, key, cities, attributed))
        return blocks, {"winner_city": winner["origin_city"]}

    def _declined(self, frames, resolved, values, key, cities, attributed):
        """The losing exports: reprinted, unattributed, and some withheld.

        The cap comes from ``newspaper.prose.max_declined_exports_printed``. The
        withholding does not: an export naming a city is withheld at every
        setting, because that is spec #21 rather than a matter of column inches.
        """
        declined = [s for s in resolved["submissions"] if not s["won"]]
        if not declined:
            return [
                {"kind": "para", "text": self._line(
                    frames["no_others"], key + ("none",),
                    "arrivals.winner_pick.no_others", values)}
            ]

        # Two reasons to withhold, counted apart so the paper can say which
        # applied: the text names a city, or the text is one already printed
        # elsewhere with its sender credited (spec #21, see
        # newspaper.redact.attributed_export_texts).
        printable, signed, matched = [], 0, 0
        for submission in declined:
            text = submission["export"]
            if not may_reprint_declined(text, cities, ()):
                signed += 1
            elif not may_reprint_declined(text, cities, attributed):
                matched += 1
            else:
                printable.append(text)
        printed = printable[: self.limits["declined"]]

        blocks = []
        if printed:
            blocks.append(
                {"kind": "para", "text": self._line(
                    frames["declined_intro"], key + ("declined",),
                    "arrivals.winner_pick.declined_intro", values)}
            )
            blocks.append(
                voice.listed(
                    printed,
                    # No substitutions: the cite for a declined offer must not be
                    # able to name anybody (spec #21, #30b).
                    self._cite("declined_quote", key + ("declined_cite",)),
                    # The role is what :func:`newspaper.redact.assert_edition_is_redacted`
                    # keys its check off: every string in this block must name no city.
                    role=DECLINED_ROLE,
                )
            )
            blocks.append(
                {"kind": "para", "text": self._line(
                    frames["declined_footer"], key + ("footer",),
                    "arrivals.winner_pick.declined_footer", values)}
            )
        for count, family in ((signed, "declined_withheld_signed"),
                              (matched, "declined_withheld_matched")):
            if not count:
                continue
            blocks.append(
                {"kind": "para", "text": self._line(
                    frames[family], key + (family,),
                    "arrivals.winner_pick.%s" % family,
                    dict(values, count=count, count_word=count_word(count),
                         counted=counted(count, "offer")))}
            )
        return blocks

    def _arrivals_ramp_up(self, frames, resolved, awards, values, key, cities, attributed):
        values = dict(values, profit=awards[0]["profit"]["display"])
        blocks = [
            {"kind": "para", "text": self._line(
                frames["headlines"], key + ("head",), "arrivals.ramp_up.headlines", values)},
            {"kind": "para", "text": self._line(
                frames["lead"], key + ("lead",), "arrivals.ramp_up.lead", values)},
        ]
        if self.tone.funny:
            blocks.append(
                {"kind": "para", "text": self._line(
                    frames["colour"], key + ("colour",), "arrivals.ramp_up.colour", values)}
            )
        blocks.append(
            {"kind": "para", "text": self._line(
                frames["profit"], key + ("profit",), "arrivals.ramp_up.profit", values)}
        )
        return blocks, {"ramped_up": resolved["importing_city"]}

    def _arrivals_even_split(self, frames, resolved, awards, values, key, cities,
                             attributed):
        values = dict(
            values,
            profit=str(resolved["resolution"]["roll"]["total"]),
            share=awards[0]["profit"]["display"],
            n_cities=len(awards),
            city_list=join_phrases([award["city"] for award in awards]),
        )
        blocks = [
            {"kind": "para", "text": self._line(
                frames["headlines"], key + ("head",), "arrivals.even_split.headlines", values)},
            {"kind": "para", "text": self._line(
                frames["lead"], key + ("lead",), "arrivals.even_split.lead", values)},
            {"kind": "para", "text": self._line(
                frames["split"], key + ("split",), "arrivals.even_split.split", values)},
        ]
        if self.tone.funny:
            blocks.append(
                {"kind": "para", "text": self._line(
                    frames["closer"], key + ("closer",),
                    "arrivals.even_split.closer", values)}
            )
        return blocks, {"split_between": [award["city"] for award in awards]}

    # -- The Wire (spec #25) ----------------------------------------------

    def the_wire(self, briefing, style):
        """The mayoral question item, or nothing.

        ``briefing["mayor_question"]`` is already gated by
        ``facilitator_questions.answers_shared_in_newspaper`` in
        :func:`engine.views.newspaper_mayor_question` -- the one place that
        decision is taken. When it is empty this department is simply absent; it
        does not read the flag itself to write a note about its own absence, and
        the one case that *is* remarkable (no question went out at all) is
        reported by the corrections column from a fact that is not gated.
        """
        report = briefing["mayor_question"]
        if report is None:
            return None
        department = self._dept("the_wire")
        blocks, provenance = wire.write(
            report, style, department, self.chooser, self.limits["quotes"]
        )
        head = [
            self._standfirst(
                department, "the_wire", (briefing["round"], report["question_id"], "sf"),
                {
                    "question": report["text"],
                    "answered": report["answered"],
                    "asked_of": report["asked_of"],
                },
            )
        ]
        if self.tone.funny:
            blocks = blocks + [
                {
                    "kind": "aside",
                    "text": self._line(
                        style["closers"],
                        (briefing["round"], report["question_id"], "closer"),
                        "wire_styles.closers",
                    ),
                }
            ]
        return {
            "id": "the_wire",
            "title": department["title"],
            "blocks": head + blocks,
            "provenance": provenance,
        }

    # -- The Ledger (spec #22) --------------------------------------------

    def the_ledger(self, briefing):
        """Cumulative profit, only if config exposes it.

        ``economy.leaderboard_visible_in_newspaper`` is taken in
        :func:`engine.views.newspaper_leaderboard`, so the briefing simply has no
        ``leaderboard`` key when the answer is no -- and then this department
        does not exist, rather than existing and printing a coy note about a
        table it is not showing.
        """
        rows = briefing.get("leaderboard")
        if rows is None:
            return None
        department = self._dept("the_ledger")
        key = (briefing["round"], "ledger")
        blocks = [
            self._standfirst(department, "the_ledger", key + ("sf",), {"n": len(rows)}),
            {
                "kind": "table",
                "columns": ["#", "City", "Profit"],
                "rows": [[row["rank"], row["city"], row["profit"]["display"]] for row in rows],
            },
        ]

        leader = rows[0]
        if not leader["tied"]:
            blocks.append(
                {"kind": "para", "text": self._line(
                    department["leader_lines"], key + ("leader",),
                    "departments.the_ledger.leader_lines", {"leader_city": leader["city"]})}
            )
        else:
            tied = [row for row in rows if row["profit"] == leader["profit"]]
            blocks.append(
                {"kind": "para", "text": self._line(
                    department["tie_lines"], key + ("tie",),
                    "departments.the_ledger.tie_lines",
                    {"tied_count": len(tied), "tied_profit": leader["profit"]["display"]})}
            )
        if any(row["profit"]["approx"] == 0 for row in rows):
            blocks.append(
                {"kind": "para", "text": self._line(
                    department["zero_lines"], key + ("zero",),
                    "departments.the_ledger.zero_lines")}
            )
        blocks.append(
            # A note, not an aside: it is a statement about how the figures were
            # compiled, so it survives ``newspaper.tone.funny: false``.
            {"kind": "note", "text": self._line(
                department["footer"], key + ("footer",),
                "departments.the_ledger.footer")}
        )
        return {
            "id": "the_ledger",
            "title": department["title"],
            "blocks": blocks,
            "provenance": {"cities": len(rows), "spec": "#20, #22"},
        }

    # -- Corrections & Clarifications -------------------------------------

    def corrections(self, briefing, previous):
        """Real retractions, derived from the round, topped up with evergreens.

        Every item here is a fact of the game -- a mayor who joined, a rotation
        that turned over, a question that never went out, a deliberation that
        expired -- because a corrections column that invents its corrections is
        just a joke column with a misleading heading. When the round produced
        fewer than the minimum, the paper falls back on standing items about
        itself, which is the one subject it may always be wrong about.
        """
        department = self._dept("corrections")
        round_index = briefing["round"]
        items = []

        new_cities = briefing["roster"]["new_this_round"]
        if len(new_cities) == 1:
            items.append(
                self._line(department["new_mayor"], (round_index, "new"),
                           "departments.corrections.new_mayor", {"city": new_cities[0]})
            )
        elif len(new_cities) > 1:
            items.append(
                self._line(department["new_mayors"], (round_index, "new"),
                           "departments.corrections.new_mayors",
                           {"cities": join_phrases(new_cities)})
            )

        opened = briefing["opened"]
        previous_opened = (previous or {}).get("opened")
        if opened and previous_opened and opened["rotation"] > previous_opened["rotation"]:
            items.append(
                self._line(department["rotation"], (round_index, "rotation"),
                           "departments.corrections.rotation",
                           {"rotation": opened["rotation"]})
            )

        if not briefing["mayor_question_asked"]:
            items.append(
                self._line(department["no_question_asked"], (round_index, "noq"),
                           "departments.corrections.no_question_asked")
            )

        report = briefing["mayor_question"]
        # Only when there is an item to qualify. "This rests on 0 replies out of
        # 4" is not a correction to anything; The Wire already said the postbag
        # was empty.
        if (
            report
            and report["reportable"]
            and report["integrity"]["must_disclose_partial_response"]
        ):
            items.append(
                self._line(department["partial_wire"], (round_index, "partial"),
                           "departments.corrections.partial_wire",
                           {"answered": report["answered"], "asked_of": report["asked_of"]})
            )

        previous_resolved = (previous or {}).get("resolved")
        if previous_resolved and previous_resolved["resolution"]["mode"] == EVEN_SPLIT:
            items.append(
                self._line(department["even_split_last_round"], (round_index, "split"),
                           "departments.corrections.even_split_last_round",
                           {"city": previous_resolved["importing_city"]})
            )

        derived = len(items)
        shortfall = max(self.limits["corrections_minimum"] - derived, 0)
        if shortfall:
            items.extend(
                self.chooser.lines(
                    department["evergreen"], (round_index, "evergreen"),
                    "departments.corrections.evergreen",
                    {"publication": self.limits["publication"], "round": round_index},
                    count=shortfall,
                )
            )

        return {
            "id": "corrections",
            "title": department["title"],
            "blocks": [
                self._standfirst(
                    department, "corrections", (round_index, "sf"),
                    {"publication": self.limits["publication"], "rotation": round_index},
                ),
                {"kind": "list", "items": items},
            ],
            "provenance": {"derived_items": derived, "evergreen_items": shortfall},
        }
