"""Assembling one edition, and refusing to publish a bad one.

:class:`Paper` is the whole of M5 in one object: it reads config.json once,
loads the copy, resolves the writer and the image modality, and then turns a
round's briefing into an edition. It is also the only place that can decide an
edition does not publish, and it makes that decision three ways:

* **Redaction** (:mod:`newspaper.redact`) -- a handle, a player id, a losing
  export's origin, or anything ``config.json`` says to withhold, and the edition
  raises instead of returning. Spec #21, #22, #25, #28.
* **Tone** (:mod:`newspaper.tone`) -- the mechanical floor under spec #30, run
  over the finished prose *and* the image's cutline, because the caption is as
  published as the copy. It grades the paper's own voice: a passage a mayor
  typed is declared as such (:mod:`newspaper.voice`), printed as typed, and
  exempt (spec #30b) -- but only after the edition has proved the passage really
  is a player's.
* **Filling** (:func:`newspaper.copy.fill`) -- a frame whose placeholders could
  not all be filled is a content error, so a brace never reaches the page.

The checks run on the rendered markdown, not just the structured payload. A leak
that only exists in the prose is still a leak, and the structured payload is not
what a player reads.
"""

from engine import views

from . import imagery, prose, redact, voice
from .copy import Chooser, NewspaperCopy
from .departments import Departments, deadline_stamp, long_date
from .endgame import EndgameDepartments, EndgamePolicy
from .endgame import build_final_edition as _write_final_edition
from .tone import TonePolicy
from .wire import join_phrases

#: The order the departments appear in the paper. Declared once, here, because
#: "what order is the paper in" is a layout fact and belongs in one place.
DEPARTMENT_ORDER = (
    "wanted", "sealed_bids", "arrivals", "the_wire", "the_ledger", "corrections",
)

#: ``newspaper.publish_cadence`` values this paper implements. Spec #26 requires
#: publication once per completed round and explicitly not batched, so the value
#: is checked rather than assumed: a config that asked for weekly batching would
#: otherwise be silently ignored.
CADENCES = {
    "per_round": "one edition per completed round, not batched (spec #26)",
}


class Paper:
    """The Daily Manifest, configured for one game."""

    def __init__(self, engine, copy=None):
        self.engine = engine
        self.config = engine.config
        self.copy = copy if copy is not None else NewspaperCopy.load(self.config)
        self.masthead = self.copy.masthead(self.config)
        self.style = self.copy.wire_style(self.config)
        self.tone = TonePolicy(self.config, self.copy)
        self.chooser = Chooser(allow_pointed=self.tone.allow_pointed)
        self.renderer = prose.resolve_renderer(self.config)
        self.limits = prose.prose_limits(self.config, self.masthead)
        self.identity_style, self.identity_rules = redact.resolve_identity_style(self.config)
        self.cadence = self._resolve_cadence()
        self.image_per_edition = self.config.require_bool("newspaper.image_per_edition")
        self.archive_prior = self.config.require_bool("newspaper.archive_prior_editions")
        self.departments = Departments(self.copy, self.chooser, self.tone, self.limits)
        # Resolved now rather than on the last day, for the reason every other
        # policy on this object is: a game whose endgame settings are malformed
        # should refuse to start, not refuse to finish (spec #31, #32).
        self.endgame = EndgamePolicy(self.config)
        self.endgame_departments = EndgameDepartments(
            self.copy, self.chooser, self.tone, self.limits, self.endgame,
        )

    def _resolve_cadence(self):
        cadence = self.config.require_str("newspaper.publish_cadence")
        if cadence not in CADENCES:
            from engine.errors import ConfigError

            raise ConfigError(
                "config.newspaper.publish_cadence is %r; this paper implements %s "
                "(spec #26)" % (cadence, sorted(CADENCES))
            )
        return cadence

    # -- one edition ------------------------------------------------------

    def edition(self, round_index):
        """The edition for one completed round, checked and ready to publish."""
        briefing = views.round_briefing(self.engine, round_index)
        previous = (
            views.round_briefing(self.engine, round_index - 1)
            if round_index - 1 in self.engine.rounds
            else None
        )
        cities = [player.city for player in self.engine.players.values()]

        written = {
            "wanted": self.departments.wanted(briefing),
            "sealed_bids": self.departments.sealed_bids(briefing),
            # Winners named up to and including this round -- not the whole
            # game. An edition rebuilt later must come out as it went out
            # (spec #27); see redact.attributed_export_texts.
            "arrivals": self.departments.arrivals(
                briefing, cities,
                redact.attributed_export_texts(self.engine, through_round=round_index),
            ),
            "the_wire": self.departments.the_wire(briefing, self.style),
            "the_ledger": self.departments.the_ledger(briefing),
            "corrections": self.departments.corrections(briefing, previous),
        }
        departments = [written[name] for name in DEPARTMENT_ORDER if written[name]]

        edition = {
            "publication": self.masthead["publication"],
            "game": self.masthead["game"],
            "round": round_index,
            "edition_line": self._fill_masthead("edition_line", round_index),
            "motto": self.masthead["motto"],
            "standing_line": self.masthead["standing_line"],
            "dateline": long_date(briefing["starts_at"]),
            "closes": deadline_stamp(briefing["ends_at"]),
            "price_line": self.chooser.line(
                self.masthead["price_lines"], (round_index, "price"), "masthead.price_lines"
            ),
            "weather_line": self.chooser.line(
                self.masthead["weather_lines"], (round_index, "weather"),
                "masthead.weather_lines",
            ),
            "departments": departments,
            "provenance": {
                "renderer": self.renderer,
                "cadence": {"value": self.cadence, "means": CADENCES[self.cadence]},
                "identity_style": {"value": self.identity_style, **self.identity_rules},
                "tone_policy": self.tone.describe(),
                "lockstep": briefing["lockstep"],
                "spec": "#25, #26, #28, #29, #30, #30b",
            },
        }

        if self.image_per_edition:
            scene = self.build_scene(briefing, edition)
            edition["image"] = imagery.make_image(self.config, self.copy, self.tone, scene)
            edition["image"]["filename"] = "round-%02d.%s" % (
                round_index, edition["image"]["extension"],
            )
        else:
            # Spec #29 wants an image in every edition; switching it off is a
            # config decision, and the edition says so rather than looking as
            # though the illustrator forgot.
            edition["image"] = {
                "omitted": True,
                "reason": "config.newspaper.image_per_edition is false",
                "spec": "#29",
            }

        self._check(edition)
        return edition

    # -- the last edition -------------------------------------------------

    def final_edition(self):
        """The endgame edition, or ``None`` if there is not one yet (#31, #32).

        ``None`` means one of two honest things -- the game has not ended, or
        ``config.endgame`` switches all three articles off -- and
        :func:`newspaper.endgame.build_final_edition` decides which. Whatever it
        returns goes through :meth:`_check` like any other edition: the last
        edition is the one with the most material and the most ways to leak
        (a portrait per city, every declined offer on every quay), so it is the
        last edition that most needs the tone and redaction gates, not least.
        """
        edition = _write_final_edition(self)
        if edition is None:
            return None
        self._check(edition)
        return edition

    # -- the illustration's raw material ----------------------------------

    def build_scene(self, briefing, edition):
        """Everything the illustrator may draw, and nothing else (spec #29).

        Every entry is a fact of this round. The crates and the ribbons come from
        the *resolved* need rather than the one that just closed, because those
        two are different needs -- the lockstep resolves what opened two rounds
        ago -- and a picture that mixed them would be a picture of no round in
        particular.
        """
        resolved = briefing["resolved"]
        opened = briefing["opened"]
        closed = briefing["closed"]
        report = briefing["mayor_question"]
        board = briefing.get("leaderboard")

        category = None
        category_label = None
        need_title = None
        for source in (opened, resolved):
            if source:
                category = source["category"]
                category_label = source["category_label"]
                need_title = source["title"]
                break

        offers = 0
        winner_indices = []
        winner_caption = None
        dice = []
        profit = None
        mode = None
        if resolved:
            resolution = resolved["resolution"]
            mode = resolution["mode"]
            offers = resolution["submission_count"]
            dice = resolution["roll"]["dice"]
            profit = resolution["roll"]["total"]
            # Positions on the ballot, which carry no information about who sent
            # what -- refs are assigned in a shuffle keyed to the need (spec #18).
            ordered = sorted(resolved["submissions"], key=lambda s: s["ballot_ref"] or "")
            winner_indices = [i for i, s in enumerate(ordered) if s["won"]]
            named = [award["city"] for award in resolved["profit_awarded"]]
            if mode == "winner_pick" and named:
                winner_caption = "chosen: %s" % named[0]
            elif mode == "even_split" and named:
                winner_caption = "split: %s" % join_phrases(named)
            elif mode == "ramp_up" and named:
                winner_caption = "%s ramped up its own industry" % named[0]
        elif closed:
            offers = closed["submission_count"]

        cutlines = self.copy.imagery()["cutlines"]
        if mode in cutlines:
            cutline_key = mode
        elif offers:
            # Crates on the quay that nobody has opened yet: the window closed
            # this round and the deciding mayor has until the next one.
            cutline_key = "sealed"
        else:
            cutline_key = "quiet"
        cutline = self.chooser.line(
            cutlines[cutline_key], (briefing["round"], cutline_key), "imagery.cutlines",
            {
                "city": (
                    (resolved or closed or opened or {}).get("importing_city")
                    or "the harbour"
                ),
                "count": offers,
                "profit": profit if profit is not None else 0,
                "winner_city": (
                    resolved["profit_awarded"][0]["city"] if resolved else "nobody"
                ),
            },
        )

        wire_scene = None
        if report and report["reportable"]:
            measure = report.get("measure") or {}
            wire_scene = {
                "answered": report["answered"],
                "largest": measure.get("largest_bucket_size", 0),
            }

        scene = {
            "publication": edition["publication"],
            "edition_line": edition["edition_line"],
            "dateline": edition["dateline"],
            "identity_note": self.masthead["standing_line"],
            "category": category,
            "category_label": category_label,
            "need_title": need_title,
            "offers": offers,
            "winner_indices": winner_indices,
            "winner_caption": winner_caption,
            "dice": dice,
            "profit": profit,
            "mode": mode,
            "wire": wire_scene,
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
        scene["alt"] = _alt_text(scene)
        return scene

    # -- refusal to publish -----------------------------------------------

    def _check(self, edition):
        from .render import editorial_markdown, to_markdown

        markdown = to_markdown(edition)
        # Redaction audits every published word, including player quotations.
        # Tone, below, receives the structurally selected editorial rendering.
        rendered = [markdown]
        editorial_rendered = [editorial_markdown(edition)]
        # Every picture the edition publishes, not just its own: the last edition
        # carries a portrait per city (spec #32), each of which prints a cutline,
        # a city name and a pile of crate labels. A picture is as published as the
        # prose, so it goes through the same tone and redaction check.
        for image in [edition.get("image")] + list(edition.get("city_images") or ()):
            if isinstance(image, dict) and isinstance(image.get("content"), str):
                rendered.append(image["content"])
                editorial_rendered.append(image["content"])

        # Whose words are whose, before anything grades them. The declared
        # player-voice passages are checked against what players actually typed
        # first, because they are about to be exempted from the tone gate and an
        # unverified exemption is a hole in spec #30 rather than a rule under
        # #30b.
        spans = voice.spans_in(edition)
        voice.assert_spans_are_player_text(self.engine, edition, spans)

        # Tone next: a snide line is a thing to fix in the copy, and hearing
        # about it before the redaction report is less confusing.
        where = "final edition" if edition.get("endgame") else "edition %s" % edition["round"]
        self.tone.check("\n".join(editorial_rendered), where=where)
        redact.assert_edition_is_redacted(self.engine, edition, rendered=rendered)
        return markdown

    # -- the archive ------------------------------------------------------

    def archive(self):
        """Every edition published so far, oldest first (spec #26, #27).

        Completed rounds only (:func:`engine.views.published_rounds`). The round
        in progress has no edition yet -- spec #26 says once per *completed*
        round -- and printing one would break the promise #27 makes about the
        archive, since that edition would say something different an hour later.

        ``newspaper.archive_prior_editions`` decides whether prior editions stay
        available. This is the payload :func:`hosting.build_site` publishes at
        the paper's one unguessable URL; the address itself is deliberately not
        in it, because an archive payload is a thing that gets written down and
        the address is a secret (spec #26).
        """
        rounds = views.published_rounds(self.engine)
        if not self.archive_prior:
            rounds = rounds[-1:]
        # The final edition is carried beside the round editions rather than
        # among them, and the reason is spec #26: "publishes once per completed
        # round" is a rule about `editions`, and a list that had two entries for
        # the last round would break it to make room for something that is not a
        # round edition at all. The endgame is spec #31's separate publication --
        # same paper, same address, same archive, its own permanent page.
        final = self.final_edition()
        return {
            "publication": self.masthead["publication"],
            "game": self.masthead["game"],
            "motto": self.masthead["motto"],
            "archive_prior_editions": self.archive_prior,
            "cadence": self.cadence,
            "editions": [self.edition(index) for index in rounds],
            "final": final,
            "ended": final is not None,
            "phase": self.engine.phase,
            "hosting": {
                "served_by": "hosting.build_site -- an unguessable subdomain with "
                             "robots noindex, per the fulcra-dashboard pattern",
                "address": "withheld; see hosting.identity.SiteIdentity.describe()",
                "spec": "#26, #27",
            },
        }

    def _fill_masthead(self, field, round_index):
        return self.masthead[field].replace("{round}", str(round_index))


def _alt_text(scene):
    """A description of the picture, for a reader who cannot see it.

    Built in code rather than content because it is a description of the
    drawing, not a piece of writing -- if the illustration changes, this should
    change with it, and it should not be possible to revise one without the
    other.
    """
    parts = ["A harbour scene in the Daily Manifest's colours"]
    if scene["category_label"]:
        parts.append("stamped %s" % scene["category_label"].lower())
    if scene["offers"]:
        crates = "%d crate%s on the quay" % (
            scene["offers"], "" if scene["offers"] == 1 else "s",
        )
        if scene["winner_indices"]:
            crates += ", %d of them ribboned" % len(scene["winner_indices"])
        parts.append(crates)
        parts.append("a boat at the mooring")
    else:
        parts.append("an empty quay and no boat")
    if scene["dice"]:
        parts.append(
            "dice showing %s" % join_phrases([str(die) for die in scene["dice"]])
        )
    if scene["leaderboard"]:
        parts.append("a skyline of %d city towers ranked by profit" % len(scene["leaderboard"]))
    else:
        parts.append("a fog bank where the standings would be")
    if scene["wire"]:
        parts.append("and %d pennants overhead, one per reply" % scene["wire"]["answered"])
    return ", ".join(parts) + "."


def build_edition(engine, round_index, copy=None):
    """One edition of The Daily Manifest for a completed round."""
    return Paper(engine, copy=copy).edition(round_index)


def build_final_edition(engine, copy=None):
    """The last edition of The Daily Manifest, or ``None`` if the game is live."""
    return Paper(engine, copy=copy).final_edition()


def build_archive(engine, copy=None):
    """Every edition so far, as the archive :mod:`hosting` serves (spec #27)."""
    return Paper(engine, copy=copy).archive()
