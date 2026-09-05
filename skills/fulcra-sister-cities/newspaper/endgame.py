"""The final edition: the crown, the consequences, and a portrait of every city.

Spec #31 and #32, which between them ask for three articles when the game ends:

    The Crown         the overall cumulative-profit winner, crowned      (#31)
    Consequences      a tongue-in-cheek twist piece on the problems the
                      year's imports and exports actually caused          (#31)
    The Excess        one description and one image per city, built from
                      that city's real history, with non-chosen exports
                      treated as "excess"                                (#32)

The names are ``NAME.md``'s, written in M1 before any of this existed; the
sentences are ``content/newspaper.json``'s; the facts are
:func:`engine.views.endgame_briefing`'s. This module is only the mapping from
one to the other -- which article gets which fact, and which of the paper's
frames is true of it.

The one design decision worth reading before the code
-----------------------------------------------------
Spec #32 wants each city's non-chosen exports on the page, and spec #21 forbids
ever saying which city sent a non-chosen export. Those pull in opposite
directions until you notice they are the same pile counted from opposite ends:
every offer a city sent and nobody chose is an offer some *other* city read and
declined.

So The Excess publishes the pile from the importing end. A city's portrait
carries the offers that arrived at its own quay and were passed over -- how many,
what the seed content calls that kind of leftover, and up to
``endgame.max_excess_offers_printed_per_city`` of them reprinted with no sender,
under exactly the rule Arrivals has used all game (an offer whose own text names
a city is withheld instead, :func:`newspaper.redact.may_reprint_declined`). It
then says, in as many words, that the offers the city *sent* and nobody chose
exist, are not itemised, and are not the last edition's to open -- and the
portrait draws a shed for them with the door shut. The sender's-end account is
real, complete, and goes to that city's own mayor as
:func:`engine.views.mayor_excess_dossier`, which tells them nothing they did not
already know, since they wrote it.

``docs/m7-endgame.md`` argues this at length, including what was rejected.
"""

from engine import views
from engine.errors import ConfigError
from engine.state import EVEN_SPLIT, RAMP_UP

from . import imagery, portrait, redact, voice
from .copy import count_word, counted
from .departments import deadline_stamp, long_date
from .redact import DECLINED_ROLE, may_reprint_declined
from .wire import join_phrases

#: The order the final edition is laid out in. The crown first because it is the
#: result, the consequences second because they are the joke the result invites,
#: the portraits last because they are the long read.
ENDGAME_DEPARTMENT_ORDER = ("the_crown", "consequences", "the_excess")

#: Filenames the final edition's pictures take. Fixed rather than configurable,
#: for the reason ``hosting.build.INDEX_FILENAME`` is: which file a permanent
#: link points at is not a game parameter (spec #27).
FINALE_IMAGE = "endgame"
PORTRAIT_PREFIX = "city"

#: Ranks, as a paper writes them. Ten is the configured maximum number of
#: players (``players.max_players``), and anything past this list falls back to
#: figures -- which is also what :func:`newspaper.copy.count_word` does, and for
#: the same reason.
_ORDINALS = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
    "ninth", "tenth",
)


def ordinal_word(rank):
    return _ORDINALS[rank - 1] if 1 <= rank <= len(_ORDINALS) else "%dth" % rank


def city_image_name(city, extension="svg"):
    """A stable, flat, ASCII filename for one city's portrait.

    Flat because the published tree is flat (see
    :class:`hosting.manifest.PublicFile`), and folded to ASCII because a
    filename is a URL and "Valparaíso" is two different URLs depending on who
    encoded it. The city's real name, accents and all, is on the page.
    """
    from engine.content import normalize_city

    slug = "".join(
        char if char.isalnum() else "-" for char in normalize_city(city)
    ).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return "%s-%s.%s" % (PORTRAIT_PREFIX, slug or "city", extension)


class EndgamePolicy:
    """``config.endgame``, resolved and validated once (spec #31, #32).

    Resolved when the :class:`newspaper.edition.Paper` is built rather than when
    the last edition is written, for the reason :class:`engine.economy.Economy`
    validates its own block at construction: a game whose endgame settings are
    malformed should say so before it is played, not on the day it ends.
    """

    __slots__ = (
        "crown", "twist", "portraits", "use_excess", "twist_items",
        "max_excess_printed", "quoted_answers", "city_image", "write_dossiers",
    )

    def __init__(self, config):
        self.crown = config.require_bool("endgame.crown_cumulative_profit_winner")
        self.twist = config.require_bool("endgame.publish_twist_article")
        self.portraits = config.require_bool(
            "endgame.generate_per_city_description_and_image"
        )
        self.use_excess = config.require_bool(
            "endgame.per_city_excess_uses_non_chosen_exports"
        )
        self.twist_items = self._non_negative(config, "endgame.twist_article_items")
        self.max_excess_printed = self._non_negative(
            config, "endgame.max_excess_offers_printed_per_city"
        )
        self.quoted_answers = self._non_negative(
            config, "endgame.quote_mayor_answers_per_city"
        )
        self.city_image = (
            self._positive(config, "endgame.city_image.width"),
            self._positive(config, "endgame.city_image.height"),
        )
        self.write_dossiers = config.require_bool("endgame.write_private_excess_dossiers")

    @staticmethod
    def _non_negative(config, dotted):
        value = config.require_int(dotted)
        if value < 0:
            raise ConfigError("config %s cannot be negative, got %d" % (dotted, value))
        return value

    @staticmethod
    def _positive(config, dotted):
        value = config.require_int(dotted)
        if value < 1:
            raise ConfigError("config %s must be at least 1, got %d" % (dotted, value))
        return value

    @property
    def publishes_anything(self):
        """Whether there is a final edition at all.

        With all three articles switched off there is no last edition, rather
        than an empty one with a masthead on it: an edition that says nothing is
        worse than the absence it is standing in for.
        """
        return bool(self.crown or self.twist or self.portraits)

    def describe(self):
        return {
            "crown_cumulative_profit_winner": self.crown,
            "publish_twist_article": self.twist,
            "generate_per_city_description_and_image": self.portraits,
            "per_city_excess_uses_non_chosen_exports": self.use_excess,
            "twist_article_items": self.twist_items,
            "max_excess_offers_printed_per_city": self.max_excess_printed,
            "quote_mayor_answers_per_city": self.quoted_answers,
            "city_image": {"width": self.city_image[0], "height": self.city_image[1]},
            "private_excess_dossiers_written": self.write_dossiers,
            "spec": "#31, #32",
        }


class EndgameDepartments:
    """Writes the last edition's three articles. Holds no state between games."""

    def __init__(self, copy, chooser, tone, prose_limits, policy):
        self.copy = copy
        self.chooser = chooser
        self.tone = tone
        self.limits = prose_limits
        self.policy = policy

    # -- helpers ----------------------------------------------------------

    def _dept(self, name):
        return self.copy.department(name)

    def _line(self, frames, key, where, values=None):
        return self.chooser.line(frames, key, where, values)

    def _standfirst(self, department, name, key, values=None):
        """The department's opening line, filled from the same table as its body.

        ``values`` is the department's own substitution dict, and every caller
        passes it. A standfirst is a frame like any other -- the ``_placeholders``
        table in ``content/newspaper.json`` declares placeholders per department,
        not per family -- so rendering it against an empty dict would make one
        family in each department silently unable to use the substitutions the
        content file says it may. Which frame gets chosen depends on game state,
        so that restriction would not fail when the frame was written; it would
        fail in whichever game first happened to choose it.
        """
        return {
            "kind": "standfirst",
            "text": self._line(
                department["standfirsts"], key, "departments.%s.standfirsts" % name,
                values,
            ),
        }

    def _cite(self, family, key, values=None):
        """:func:`newspaper.voice.cite`, with this department's copy and chooser."""
        return voice.cite(self.copy, self.chooser, family, key, values)

    def _closer(self, department, name, key, values=None):
        """The editorial sign-off, or nothing when told not to be funny (#30)."""
        if not self.tone.funny:
            return []
        return [
            {
                "kind": "aside",
                "text": self._line(
                    department["closers"], key, "departments.%s.closers" % name,
                    values,
                ),
            }
        ]

    # -- The Crown (spec #31) ---------------------------------------------

    def the_crown(self, report):
        """Who won, by how much, and how -- or nothing, if config says so."""
        if not self.policy.crown:
            return None
        department = self._dept("the_crown")
        crown = report["crown"]
        world = report["world"]
        visible = crown["profit_visible"]
        winners = crown["winners"]
        lead = winners[0]
        key = ("crown", lead["city"])
        withheld = self.copy.endgame_imagery()["labels"]["no_figures"]

        values = {
            "city": lead["city"],
            "mayor": lead["mayor"],
            "profit": crown["profit"]["display"] if visible else withheld,
            "city_list": join_phrases([row["city"] for row in winners]),
            "n_winners": len(winners),
            "runner_up": (crown.get("runner_up") or {}).get("city", "nobody"),
            "margin": (crown.get("margin") or {}).get("display", "0"),
            "n_cities": crown["n_cities"],
            "n_others": crown["n_cities"] - len(winners),
            "n_needs": world["needs"],
            "rounds": world["rounds"],
            "wins": lead["wins"],
            "wins_word": count_word(lead["wins"]),
        }

        if crown["shared"]:
            family = "shared_crown" if visible else "shared_crown_no_figure"
        else:
            family = "crowned" if visible else "crowned_no_figure"
        blocks = [
            self._standfirst(department, "the_crown", key + ("sf",), values),
            {"kind": "para", "text": self._line(
                department[family], key + (family,),
                "departments.the_crown.%s" % family, values)},
        ]

        if visible:
            # A margin is a claim about two figures, so it is only made where the
            # figures are printed. "Narrowly" over an unprinted total would be
            # the paper describing arithmetic it has withheld.
            margin_family = "margin" if crown.get("margin") else "margin_none"
            blocks.append({"kind": "para", "text": self._line(
                department[margin_family], key + (margin_family,),
                "departments.the_crown.%s" % margin_family, values)})

        earned = "earned_by_winning" if lead["wins"] else "earned_nothing_chosen"
        blocks.append({"kind": "para", "text": self._line(
            department[earned], key + (earned,),
            "departments.the_crown.%s" % earned, values)})
        if lead["ramped_up"] and lead["wins"]:
            blocks.append({"kind": "para", "text": self._line(
                department["earned_by_ramp_up"], key + ("ramp",),
                "departments.the_crown.earned_by_ramp_up", values)})
        if crown["all_zero"]:
            blocks.append({"kind": "para", "text": self._line(
                department["zero_note"], key + ("zero",),
                "departments.the_crown.zero_note", values)})

        board = report.get("leaderboard")
        if board is not None:
            blocks.append(
                {
                    "kind": "table",
                    "columns": ["#", "City", "Final profit"],
                    "rows": [
                        [row["rank"], row["city"], row["profit"]["display"]]
                        for row in board
                    ],
                }
            )
        note_family = "table_note" if board is not None else "table_withheld"
        blocks.append({"kind": "note", "text": self._line(
            department[note_family], key + (note_family,),
            "departments.the_crown.%s" % note_family, values)})
        blocks.append({"kind": "para", "text": self._line(
            department["also_rans"], key + ("also",),
            "departments.the_crown.also_rans", values)})
        blocks.extend(self._closer(department, "the_crown", key + ("closer",), values))

        return {
            "id": "the_crown",
            "title": department["title"],
            "blocks": blocks,
            "provenance": {
                "winners": [row["city"] for row in winners],
                "shared": crown["shared"],
                "profit_visible": visible,
                "wins_by_the_crown": lead["wins"],
                "spec": "#31",
            },
        }

    # -- Consequences (spec #31) ------------------------------------------

    def consequences(self, report):
        """The twist article: what the year's trade actually did to everybody.

        Every item is one arrival that really happened -- the export as written,
        the city that sent it (a winner, so nameable), the city that chose it --
        followed by a consequence keyed to that need's own category. A twist
        article whose items could have been printed before the game began would
        be a comedy column with a misleading heading.
        """
        if not self.policy.twist:
            return None
        department = self._dept("consequences")
        arrivals = list(report["arrivals"])
        world = report["world"]
        excess = world["excess_total"]

        base = {
            "city": "the harbour",
            "to_city": "the harbour",
            "from_city": "somewhere",
            "export": "",
            "title": "",
            "category_label": "trade",
            "n_cities": world["cities"],
            "n_arrivals": len(arrivals),
            "excess": excess,
            "excess_word": count_word(excess),
            "flavours": join_phrases(world["excess_flavours"]) or "nothing at all",
        }
        blocks = [
            self._standfirst(department, "consequences", ("consequences", "sf"), base),
            {"kind": "para", "text": self._line(
                department["lede"], ("consequences", "lede"),
                "departments.consequences.lede", base)},
        ]

        delivered = department["delivered"]
        for index, arrival in enumerate(self._pick_arrivals(arrivals)):
            values = dict(
                base,
                to_city=arrival["to_city"],
                from_city=arrival["from_city"],
                export=arrival["export"],
                title=arrival["title"],
                category_label=arrival["category_label"],
            )
            key = ("consequences", arrival["need"])
            pool = delivered["by_category"].get(arrival["category"]) or delivered["general"]
            where = "departments.consequences.delivered"
            # A winner, so nameable (spec #18, #20) -- and printed as its mayor
            # typed it, cited to them, and exempt from the editorial register
            # (spec #30b).
            blocks.append(voice.quoted(
                arrival["export"],
                self._cite("twist_quote", key + ("cite", index),
                           {"mayor": "the Mayor of %s" % arrival["from_city"]}),
            ))
            blocks.append({"kind": "para", "text": self._line(
                delivered["attribution"], key + ("attr", index),
                where + ".attribution", values)})
            blocks.append({"kind": "para", "text": self._line(
                pool, key + ("effect",), where, values)})

        for ramp in world["ramp_ups"][:1]:
            blocks.append({"kind": "para", "text": self._line(
                department["ramped_up"], ("consequences", "ramp", ramp["city"]),
                "departments.consequences.ramped_up", dict(base, city=ramp["city"]))})
        for split in world["even_splits"][:1]:
            blocks.append({"kind": "para", "text": self._line(
                department["even_split"], ("consequences", "split", split["city"]),
                "departments.consequences.even_split",
                dict(base, city=split["city"], n_cities=split["cities"]))})

        byproducts = "byproducts" if excess else "byproducts_none"
        blocks.append({"kind": "para", "text": self._line(
            department[byproducts], ("consequences", byproducts),
            "departments.consequences.%s" % byproducts, base)})
        blocks.append({"kind": "para", "text": self._line(
            department["blame"], ("consequences", "blame"),
            "departments.consequences.blame", base)})
        blocks.extend(
            self._closer(department, "consequences", ("consequences", "closer"), base)
        )

        return {
            "id": "consequences",
            "title": department["title"],
            "blocks": blocks,
            "provenance": {
                "arrivals_available": len(arrivals),
                "arrivals_printed": len(self._pick_arrivals(arrivals)),
                "cap": self.policy.twist_items,
                "world_excess": excess,
                "excess_attributed_to_any_city": False,
                "spec": "#31, #21",
            },
        }

    def _pick_arrivals(self, arrivals):
        """Which arrivals the twist article follows up on.

        Capped by ``endgame.twist_article_items`` and spread across categories
        first: four consequences from four different kinds of need is a better
        article than four from one, and the seeded content has a consequence line
        per category to make that worth doing.
        """
        chosen = []
        seen = set()
        for arrival in arrivals:
            if arrival["category"] in seen:
                continue
            seen.add(arrival["category"])
            chosen.append(arrival)
            if len(chosen) >= self.policy.twist_items:
                return chosen
        for arrival in arrivals:
            if arrival in chosen:
                continue
            chosen.append(arrival)
            if len(chosen) >= self.policy.twist_items:
                break
        return chosen

    # -- The Excess (spec #32) --------------------------------------------

    def the_excess(self, report, cities, portraits, attributed=()):
        """One portrait per city, drawn from that city's own year.

        ``portraits`` maps a city to the image the illustrator produced for it,
        or is empty when no image was made; the description is written either
        way, because #32 asks for a description *and* an image and the two fail
        independently.

        ``attributed`` is every export text the paper names a sender for
        elsewhere (:func:`newspaper.redact.attributed_export_texts`). It matters
        more here than anywhere else in the paper: this department reprints
        declined offers from the *whole game*, and the twist article two columns
        up quotes winners by name, so a sentence that lost here and won there
        would otherwise be identifiable by matching (spec #21).
        """
        if not self.policy.portraits:
            return None
        department = self._dept("the_excess")
        # The survey's own opening and closing lines are about the world, not
        # about any one city, so they get the world-level substitution and none
        # of the per-city ones -- which is exactly what they are able to say.
        survey = {"n_cities": len(report["cities"])}
        blocks = [self._standfirst(department, "the_excess", ("excess", "sf"), survey)]
        printed = []
        for dossier in report["cities"]:
            blocks.extend(
                self._city_blocks(department, dossier, cities, portraits, attributed)
            )
            printed.append(dossier["city"])
        blocks.extend(
            self._closer(department, "the_excess", ("excess", "closer"), survey)
        )
        return {
            "id": "the_excess",
            "title": department["title"],
            "blocks": blocks,
            "provenance": {
                "cities": printed,
                "portraits": {city: portraits[city]["filename"] for city in portraits},
                "excess_material_used": self.policy.use_excess,
                "reprint_cap": self.policy.max_excess_printed,
                "sender_side_excess_itemised": False,
                "spec": "#32, #21",
            },
        }

    def _city_blocks(self, department, dossier, cities, portraits, attributed):
        city = dossier["city"]
        key = ("excess", city)
        visible = "profit" in dossier
        imports = dossier["imports"]
        kept = dossier["exports_kept"]
        excess = dossier["excess"]
        declined = excess["declined_offers"]
        withheld_label = self.copy.endgame_imagery()["labels"]["no_figures"]

        values = {
            "city": city,
            "mayor": dossier["mayor"],
            "profit": dossier["profit"]["display"] if visible else withheld_label,
            "rank": dossier.get("rank") or 0,
            "rank_word": _rank_word(dossier),
            "to_city": kept[0]["to_city"] if kept else city,
            "export": kept[0]["export"] if kept else "",
            "title": imports[0]["title"] if imports else "",
            "titles": join_phrases([record["title"] for record in imports]) or "nothing",
            "category_label": imports[0]["category_label"] if imports else "trade",
            "count": len(declined),
            "count_word": count_word(len(declined)),
            # A phrase that already agrees with its own number, so a frame does
            # not have to be written twice to avoid printing "one offers".
            "counted": counted(len(declined), "offer"),
            "flavour": join_phrases(excess["flavours"]) or "leftovers",
            "question": "",
            "answer": "",
            "n_imports": len(imports),
            "n_imports_word": count_word(len(imports)),
            "n_cities": len(report_cities(dossier)) or len(cities),
        }

        blocks = [{"kind": "heading", "level": 3, "text": city}]
        image = portraits.get(city)
        if image:
            blocks.append(
                {
                    "kind": "figure",
                    "image": image["filename"],
                    "alt": image["alt"],
                    "caption": image["cutline"],
                }
            )
        intro = "city_intro" if visible else "city_intro_no_figure"
        blocks.append({"kind": "para", "text": self._line(
            department[intro], key + (intro,), "departments.the_excess.%s" % intro,
            values)})

        imports_family = "imports_line" if imports else "imports_none"
        blocks.append({"kind": "para", "text": self._line(
            department[imports_family], key + (imports_family,),
            "departments.the_excess.%s" % imports_family, values)})

        if len(kept) > 1:
            blocks.append({"kind": "para", "text": self._line(
                department["won_more"], key + ("won_more",),
                "departments.the_excess.won_more",
                dict(values, count=len(kept), count_word=count_word(len(kept))))})
        if kept:
            best = max(kept, key=lambda entry: len(entry["export"]))
            # The sentence is the paper's and the offer quoted inside it is the
            # mayor's, so only the first of the two is the paper's to police
            # (spec #30b).
            blocks.append(voice.within(
                {"kind": "para", "text": self._line(
                    department["won_line"], key + ("won",),
                    "departments.the_excess.won_line",
                    dict(values, export=best["export"], to_city=best["to_city"]))},
                best["export"],
            ))
        else:
            blocks.append({"kind": "para", "text": self._line(
                department["won_none"], key + ("won_none",),
                "departments.the_excess.won_none", values)})

        if dossier["ramped_up_rounds"]:
            blocks.append({"kind": "para", "text": self._line(
                department["ramped_up_line"], key + ("ramp",),
                "departments.the_excess.ramped_up_line", values)})
        if dossier["even_split_rounds"]:
            split = next(
                record for record in imports if record["mode"] == EVEN_SPLIT
            )
            blocks.append({"kind": "para", "text": self._line(
                department["even_split_line"], key + ("split",),
                "departments.the_excess.even_split_line",
                dict(values, n_cities=len(split.get("split_between") or ())))})

        blocks.extend(
            self._excess_blocks(department, dossier, cities, key, values, attributed)
        )
        blocks.extend(self._answer_blocks(department, dossier, key, values))
        return blocks

    def _excess_blocks(self, department, dossier, cities, key, values, attributed):
        """The excess itself: the quay, the reprints, and the shut door (#21, #32)."""
        if not self.policy.use_excess:
            return [
                {"kind": "para", "text": self._line(
                    department["excess_suppressed"], key + ("suppressed",),
                    "departments.the_excess.excess_suppressed", values)}
            ]

        declined = [item["export"] for item in dossier["excess"]["declined_offers"]]
        blocks = []
        if declined:
            blocks.append({"kind": "para", "text": self._line(
                department["excess_intro"], key + ("excess",),
                "departments.the_excess.excess_intro", values)})
            # The cap is config's; the withholding is not. An offer that names a
            # city, or that reads exactly like one the paper attributes to a
            # sender elsewhere, is withheld at every setting -- that is spec #21
            # rather than a matter of column inches (same rule as Arrivals).
            # The two reasons are counted apart so the paper can say which
            # applied; reporting the wrong one would be this column being
            # inaccurate about its own redaction, in a column about redaction.
            printable, signed, matched = [], 0, 0
            for text in declined:
                if not may_reprint_declined(text, cities, ()):
                    signed += 1
                elif not may_reprint_declined(text, cities, attributed):
                    matched += 1
                else:
                    printable.append(text)
            printed = printable[: self.policy.max_excess_printed]
            if printed:
                blocks.append({"kind": "para", "text": self._line(
                    department["excess_reprints_intro"], key + ("reprint",),
                    "departments.the_excess.excess_reprints_intro",
                    dict(values, count=len(printed), count_word=count_word(len(printed)),
                         counted=counted(len(printed), "offer")))})
                blocks.append(
                    voice.listed(
                        printed,
                        # No substitutions in this cite family: an unchosen
                        # offer is quoted as written and credited to nobody
                        # (spec #21, #30b).
                        self._cite("excess_quote", key + ("excess_cite",)),
                        # The role is what redact.assert_edition_is_redacted keys
                        # its check off: every string here must name no city.
                        role=DECLINED_ROLE,
                    )
                )
            for count, family in ((signed, "excess_withheld_signed"),
                                  (matched, "excess_withheld_matched")):
                if not count:
                    continue
                blocks.append({"kind": "para", "text": self._line(
                    department[family], key + (family,),
                    "departments.the_excess.%s" % family,
                    dict(values, count=count, count_word=count_word(count),
                         counted=counted(count, "offer")))})
        else:
            blocks.append({"kind": "para", "text": self._line(
                department["excess_none"], key + ("none",),
                "departments.the_excess.excess_none", values)})

        blocks.append({"kind": "para", "text": self._line(
            department["excess_sealed"], key + ("sealed",),
            "departments.the_excess.excess_sealed", values)})
        return blocks

    def _answer_blocks(self, department, dossier, key, values):
        """This city's own words, if the exposure policy shares answers at all.

        ``dossier`` simply has no ``answers`` key when
        ``facilitator_questions.answers_shared_in_newspaper`` is false -- that
        decision is taken in :func:`engine.views.endgame_briefing`, so this
        department does not read the flag and cannot disagree with it.
        """
        answers = dossier.get("answers") or []
        blocks = []
        for index, answer in enumerate(answers[: self.policy.quoted_answers]):
            blocks.append(voice.within(
                {"kind": "para", "text": self._line(
                    department["answer_line"], key + ("answer", index),
                    "departments.the_excess.answer_line",
                    dict(values, question=answer["question"], answer=answer["answer"]))},
                # A mayor's own reply, quoted inside the paper's sentence
                # (spec #30b).
                answer["answer"],
            ))
        return blocks


def report_cities(dossier):
    """The cities named in one dossier's own even-split records.

    A tiny helper with a real job: the even-split line needs the number of cities
    that were paid, and that number is a property of the need rather than of the
    game.
    """
    return [
        city
        for record in dossier["imports"]
        for city in (record.get("split_between") or ())
    ]


def _rank_word(dossier):
    rank = dossier.get("rank")
    if not rank:
        return "unplaced"
    word = ordinal_word(rank)
    return "joint %s" % word if dossier.get("tied") else word


# -- the pictures ---------------------------------------------------------

def finale_scene(paper, report, edition):
    """Everything the finale illustration may draw (spec #29's policy, #31)."""
    crown = report["crown"]
    world = report["world"]
    board = report.get("leaderboard")
    crowned = [row["city"] for row in crown["winners"]]
    endgame_art = paper.copy.endgame_imagery()
    labels = endgame_art["labels"]

    outcome = "uncrowned" if not crown["profit_visible"] else (
        "shared" if crown["shared"] else "crowned"
    )
    cutline = paper.chooser.line(
        endgame_art["finale_cutlines"][outcome], ("finale", outcome),
        "imagery.endgame.finale_cutlines.%s" % outcome,
        {
            "city": join_phrases(crowned) or "nobody",
            "count": world["offers_chosen"],
            "profit": (crown.get("profit") or {}).get("display", labels["no_figures"]),
            "excess": world["excess_total"],
            "n_cities": world["cities"],
        },
    )

    scene = {
        "kind": "endgame_finale",
        "publication": edition["publication"],
        "edition_line": edition["edition_line"],
        "dateline": edition["dateline"],
        "identity_note": edition["standing_line"],
        # The palette follows the last category the world asked about, so the
        # final edition does not look like a reprint of round one.
        "category": _last_category(report),
        "crowned_cities": crowned,
        "crown_shared": crown["shared"],
        "excess_total": world["excess_total"],
        "n_cities": world["cities"],
        "leaderboard": (
            None if board is None
            else [
                {
                    "city": row["city"],
                    "profit": row["profit"]["approx"],
                    "profit_display": row["profit"]["display"],
                }
                for row in board
            ]
        ),
        "cutline": cutline,
    }
    scene["alt"] = _finale_alt(scene, labels)
    return scene


def city_scene(paper, report, dossier, edition):
    """Everything one city's portrait may draw (spec #32).

    Public facts only, and one deliberate absence: the shed stands for the
    offers this city sent that nobody chose, and it carries no number, because a
    number is what would make the pile attributable (spec #21).
    """
    endgame_art = paper.copy.endgame_imagery()
    labels = endgame_art["labels"]
    imports = dossier["imports"]
    visible = "profit" in dossier
    board = report.get("leaderboard")
    top = (
        max([row["profit"]["approx"] for row in board] + [0]) if board is not None else 0
    )
    declined = (
        dossier["excess"]["declined_on_own_quay"] if paper.endgame.use_excess else 0
    )

    cutline = paper.chooser.line(
        endgame_art["city_cutlines"], ("portrait", dossier["city"]),
        "imagery.endgame.city_cutlines",
        {
            "city": dossier["city"],
            "count": declined,
            "profit": dossier["profit"]["display"] if visible else labels["no_figures"],
            "excess": declined,
            "n_cities": report["world"]["cities"],
        },
    )

    scene = {
        "kind": "city_portrait",
        "publication": edition["publication"],
        "edition_line": edition["edition_line"],
        "dateline": edition["dateline"],
        "identity_note": edition["standing_line"],
        "city": dossier["city"],
        "category": imports[0]["category"] if imports else None,
        "notices": [
            {"category_label": record["category_label"], "title": record["title"]}
            for record in imports
        ],
        "kept": len(dossier["exports_kept"]),
        "declined_on_quay": declined,
        # Drawn whenever unchosen offers are part of the portrait at all: the
        # door is the statement, and it is the same statement for every city.
        "sealed_shed": paper.endgame.use_excess,
        "profit_share": (
            None if not visible or not top
            else min(dossier["profit"]["approx"] / top, 1.0)
        ),
        "profit_display": dossier["profit"]["display"] if visible else None,
        "standing_line": (
            "%s on %s" % (_rank_word(dossier), dossier["profit"]["display"])
            if visible else labels["no_figures"]
        ),
        "cutline": cutline,
    }
    scene["alt"] = _city_alt(scene, labels)
    return scene


def _last_category(report):
    for dossier in reversed(report["cities"]):
        if dossier["imports"]:
            return dossier["imports"][-1]["category"]
    return None


def _finale_alt(scene, labels):
    parts = ["The Daily Manifest's closing illustration"]
    if scene["leaderboard"]:
        parts.append(
            "a skyline of %d city towers at their final heights" % len(scene["leaderboard"])
        )
        parts.append(
            "a crown over %s" % join_phrases(scene["crowned_cities"])
            if scene["crowned_cities"] else "no crown at all"
        )
    else:
        parts.append("a fog bank where the final standings would be")
        if scene["crowned_cities"]:
            parts.append("and the crown named beneath it: %s"
                         % join_phrases(scene["crowned_cities"]))
    if scene["excess_total"]:
        parts.append(
            "%d unlabelled crates stacked on the quay, one per offer the world sent "
            "and nobody chose" % scene["excess_total"]
        )
    else:
        parts.append("an empty quay")
    return ", ".join(parts) + "."


def _city_alt(scene, labels):
    parts = ["A portrait of %s in the Daily Manifest's colours" % scene["city"]]
    if scene["notices"]:
        parts.append(
            "rubber stamps for the %d notice%s it opened"
            % (len(scene["notices"]), "" if len(scene["notices"]) == 1 else "s")
        )
    else:
        parts.append("no stamps, because it never opened a notice")
    if scene["kept"]:
        parts.append("%d ribboned crates for the offers the world kept" % scene["kept"])
    if scene["declined_on_quay"]:
        parts.append(
            "%d plain crates for the offers it declined, none of them marked with a "
            "sender" % scene["declined_on_quay"]
        )
    if scene["sealed_shed"]:
        parts.append("and a shed with the door shut, for the offers it sent that "
                     "nobody chose and that this paper does not count")
    return ", ".join(parts) + "."


# -- the edition ----------------------------------------------------------

def build_final_edition(paper):
    """The last edition of the paper, or ``None`` if this game publishes none.

    ``None`` happens two ways and both are honest: the game has not ended (there
    is nothing to write yet), or ``config.endgame`` has all three articles
    switched off (see :attr:`EndgamePolicy.publishes_anything`).
    """
    from engine.game import ENDED

    engine = paper.engine
    policy = paper.endgame
    if engine.phase != ENDED or not policy.publishes_anything:
        return None

    report = views.endgame_briefing(engine)
    cities = [player.city for player in engine.players.values()]
    round_index = report["ended_round"]
    last = views.round_briefing(engine, round_index)
    masthead = paper.masthead

    edition = {
        "publication": masthead["publication"],
        "game": masthead["game"],
        "round": round_index,
        "endgame": True,
        "edition_line": masthead["final_edition_line"].replace(
            "{round}", str(round_index)
        ),
        "motto": masthead["motto"],
        "standing_line": masthead["final_standing_line"],
        "dateline": long_date(last["starts_at"]),
        "closes": deadline_stamp(last["ends_at"]),
        "foot_line": masthead["final_foot"].replace(
            "{publication}", masthead["publication"]
        ),
        "price_line": paper.chooser.line(
            masthead["price_lines"], ("final", "price"), "masthead.price_lines"
        ),
        "weather_line": paper.chooser.line(
            masthead["weather_lines"], ("final", "weather"), "masthead.weather_lines"
        ),
    }

    # The finale is the edition's own image, so it follows
    # newspaper.image_per_edition (spec #29). The portraits are #32's own
    # requirement and follow endgame.generate_per_city_description_and_image --
    # two requirements, two switches, deliberately not one.
    if paper.image_per_edition:
        scene = finale_scene(paper, report, edition)
        edition["image"] = imagery.make_image(
            paper.config, paper.copy, paper.tone, scene,
            illustrator=portrait.render_finale,
            labels=paper.copy.endgame_imagery()["labels"],
        )
        edition["image"]["filename"] = "%s.%s" % (
            FINALE_IMAGE, edition["image"]["extension"],
        )
    else:
        edition["image"] = {
            "omitted": True,
            "reason": "config.newspaper.image_per_edition is false",
            "spec": "#29",
        }

    portraits = {}
    if policy.portraits:
        for dossier in report["cities"]:
            scene = city_scene(paper, report, dossier, edition)
            image = imagery.make_image(
                paper.config, paper.copy, paper.tone, scene,
                illustrator=portrait.render_city,
                labels=paper.copy.endgame_imagery()["labels"],
                size=policy.city_image,
            )
            image["filename"] = city_image_name(dossier["city"], image["extension"])
            image["city"] = dossier["city"]
            portraits[dossier["city"]] = image
    edition["city_images"] = [portraits[dossier["city"]] for dossier in report["cities"]
                              if dossier["city"] in portraits]

    written = {
        "the_crown": paper.endgame_departments.the_crown(report),
        "consequences": paper.endgame_departments.consequences(report),
        "the_excess": paper.endgame_departments.the_excess(
            report, cities, portraits, redact.attributed_export_texts(engine),
        ),
    }
    edition["departments"] = [
        written[name] for name in ENDGAME_DEPARTMENT_ORDER if written[name]
    ]
    edition["provenance"] = {
        "renderer": paper.renderer,
        "endgame_policy": policy.describe(),
        "identity_style": {"value": paper.identity_style, **paper.identity_rules},
        "tone_policy": paper.tone.describe(),
        "ended_round": round_index,
        "excess_policy": report["excess_policy"],
        "spec": "#28, #29, #30, #31, #32",
    }
    return edition
