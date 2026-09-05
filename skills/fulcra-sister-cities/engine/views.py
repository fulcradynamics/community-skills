"""Read-only projections of game state for consumers outside the engine.

Two audiences, two functions, and the difference between them is the whole
point:

* :func:`importer_ballot` -- what the mayor who opened an import need sees while
  voting. Refs and export text. No cities (spec #18).
* :func:`round_briefing` / :func:`archive` -- the *facts* the newspaper milestone
  will write from. Winners are named; everyone else's submission appears with its
  origin withheld, permanently (spec #21).

* :func:`newspaper_mayor_question` -- the round's question item, gated by the
  configured exposure policy, carrying the aggregate as *numbers* (see
  :mod:`engine.aggregate`) rather than as a sentence.
* :func:`endgame_briefing` -- the finished game, for the last edition's crown,
  twist article and per-city portraits (#31, #32). Its private counterpart,
  :func:`mayor_excess_dossier`, is the one endgame payload that is never
  published; see :mod:`engine.endgame` for why the two exist.

These are data, not prose. Headlines, copy, images and the wording of the
aggregate item are the :mod:`newspaper` package's job (M5), and it reads this
module rather than the engine's internals -- which is what keeps the redaction
rules in one place instead of one per template.
"""

from . import ballot, endgame, money
from .economy import NON_WINNER_ORIGIN_EXPOSURE
from .errors import PickRejected
from .state import (
    COLLECTING,
    PICKING,
    RESOLVED,
    READ_WINNER_REVEAL,
)

ORIGIN_WITHHELD = "withheld"


def importer_ballot(engine, player_id, need_key=None):
    """The blind ballot for the need this mayor must resolve (spec #18)."""
    need = engine.picking_need_for(player_id) if need_key is None else engine.needs.get(need_key)
    if need is None:
        raise PickRejected("no import need is awaiting a pick from %r" % player_id)
    if need.importing_player_id != player_id:
        raise PickRejected(
            "only the importing mayor of %s sees that ballot" % need.importing_city
        )
    return {
        "need": need.need_key,
        "importing_city": need.importing_city,
        "need_brief": need.rendered["need_brief"],
        "closes_at": engine.rounds[engine.current_round].ends_at.isoformat(),
        "entries": ballot.build(engine.submissions_for(need.need_key)),
    }


def newspaper_leaderboard(engine, round_index=None):
    """The leaderboard as the newspaper may print it, or ``None`` (spec #22).

    The single place the exposure decision is taken. Every newspaper-facing
    payload asks this rather than reading the config key itself, so switching
    ``economy.leaderboard_visible_in_newspaper`` off cannot be defeated by one
    view that forgot to check.

    With a ``round_index``, it returns that round's *closing* standing rather
    than the live one, so an edition stays true after the game moves on (see
    :class:`engine.state.RoundRecord`). A round still in progress has no closing
    standing yet and reports the live table, which is the same thing to anyone
    reading it at the time.
    """
    if not engine.economy.leaderboard_visible:
        return None
    if round_index is not None:
        record = engine.rounds.get(round_index)
        if record is not None and record.standings is not None:
            return record.standings
    return engine.leaderboard()


def newspaper_mayor_question(engine, round_index):
    """The round's question item as the newspaper may print it, or ``None``.

    The one place ``facilitator_questions.answers_shared_in_newspaper`` (spec
    #25's "shared in the newspaper by default (not private)") is consulted, for
    the same reason :func:`newspaper_leaderboard` is the only place the
    leaderboard exposure decision is taken: an exposure policy enforced in two
    views is an exposure policy one of them will forget.

    The payload is the full aggregate report -- the distribution, the selected
    outcome and the wordings that outcome licenses (spec #25's data side). The
    sentence written from it is M5's. Answers are keyed by city throughout
    (spec #28), and nothing here touches the export side of the game: the
    questions channel and the blind-voting channel never cross-reference each
    other (#18, #21).
    """
    shared = engine.config.require_bool("facilitator_questions.answers_shared_in_newspaper")
    if not shared:
        return None
    return engine.mayor_question_report(round_index)


def endgame_briefing(engine):
    """The finished game's facts as the last edition may print them (#31, #32).

    The two exposure decisions this payload is subject to are taken here, and
    taken by asking the same two functions every other newspaper payload asks --
    :func:`newspaper_leaderboard` for the standings (#22) and the
    ``answers_shared_in_newspaper`` policy for the mayors' own answers (#25). The
    endgame does not read either key itself; a payload that consulted config
    directly would be a second reading of a decision that is supposed to have one
    home.

    The crown is named either way. Spec #31 requires the winner to be crowned at
    game end, and it is not one of the things #22 makes configurable -- so a game
    that kept its leaderboard private crowns its winner without quoting the
    figure, and :func:`engine.endgame.endgame_report` records which of those
    happened in ``crown.profit_visible``.
    """
    return endgame.endgame_report(
        engine,
        include_leaderboard=newspaper_leaderboard(engine) is not None,
        include_answers=engine.config.require_bool(
            "facilitator_questions.answers_shared_in_newspaper"
        ),
    )


def mayor_excess_dossier(engine, player_id):
    """One mayor's own unchosen offers -- **not** a newspaper payload (#21, #32).

    The sender's end of the excess, for the one reader it belongs to. Carried
    here beside the other facilitator-only view so that "which of these two is
    the gated one" is answered by reading one file: the published portrait's
    material is in :func:`endgame_briefing`, and this is the part of it that is
    never published. :mod:`hosting.guard` refuses anything carrying
    ``audience: facilitator``, which is how that stays true.
    """
    return endgame.mayor_excess_dossier(engine, player_id)


def facilitator_question_report(engine, round_index):
    """The facilitator's view of a round's question -- **not** a newspaper payload.

    Complete regardless of the exposure policy, for the same reason
    :func:`standings` is: the facilitator runs the game and needs to see what
    came back whether or not the paper prints it. ``newspaper_visible`` says at a
    glance that this is not the gated view -- that one is
    :func:`newspaper_mayor_question`.
    """
    report = engine.mayor_question_report(round_index)
    if report is None:
        return None
    return dict(
        report,
        audience="facilitator",
        newspaper_visible=engine.config.require_bool(
            "facilitator_questions.answers_shared_in_newspaper"
        ),
    )


def _submission_line(engine, submission, reveal):
    """One submission as the outside world may see it.

    Built from a whitelist. A winner's city is named; a non-winner has no city
    field at all -- not ``None``, not an id, absent -- so there is nothing for a
    downstream template to accidentally render.

    ``reveal`` only ever widens as far as *winners*. There is no argument, and
    no config key, that names a losing export's city: spec #21 is absolute, and
    :data:`engine.economy.NON_WINNER_ORIGIN_EXPOSURE` records that on purpose.
    """
    line = {
        "ballot_ref": submission.ballot_ref,
        "export": submission.text,
        "won": bool(submission.is_winner),
    }
    if NON_WINNER_ORIGIN_EXPOSURE:  # pragma: no cover - False, permanently (#21)
        raise AssertionError(
            "engine.economy.NON_WINNER_ORIGIN_EXPOSURE was flipped on; spec #21 "
            "does not permit a losing export's origin to be published"
        )
    if reveal and submission.is_winner:
        line["origin_city"] = engine.ledger.city_for(
            submission.submission_id, READ_WINNER_REVEAL
        )
    else:
        line["origin"] = ORIGIN_WITHHELD
    return line


def need_briefing(engine, need):
    """One import need's public record, redacted for its current status."""
    submissions = engine.submissions_for(need.need_key)
    category = engine.content.categories.get(need.category) or {}
    out = {
        "need": need.need_key,
        "importing_city": need.importing_city,
        "importing_mayor": engine.players[need.importing_player_id].mayor,
        "category": need.category,
        # The label and the exporter prompt are already public -- the prompt is
        # shown to every exporting mayor in their check-in -- and the newspaper
        # needs both to print the notice. Carried here rather than read off
        # ``need.rendered`` by the paper, so every consumer sees the same
        # redaction decisions taken in one module.
        "category_label": category.get("label", need.category),
        # Spec #13: who filed this order and whether they took a seed or wrote
        # their own. Public by construction -- the importing city and its mayor
        # are already on the notice, and nothing here touches an *exporter's*
        # identity, which is the one spec #21 protects.
        "filed_by": need.order.get("filed_by"),
        "request_source": need.order.get("request_source"),
        "trade_family": need.order.get("trade_family"),
        "exporter_prompt": need.rendered["exporter_prompt"],
        "title": need.rendered["title"],
        "need_brief": need.rendered["need_brief"],
        "opened_round": need.opened_round,
        "closed_round": need.closed_round,
        "resolved_round": need.resolved_round,
        "rotation": need.rotation,
        "status": need.status,
    }
    if need.status == COLLECTING:
        # Nothing about live submissions is public -- not even how many, which
        # would tell a watching mayor whether their export was the only one.
        out["submissions"] = []
        out["note"] = "export window open; submissions are not public until resolved"
        return out
    if need.status == PICKING:
        out["submissions"] = []
        out["note"] = "awaiting the importing mayor's pick; nothing is published yet"
        return out

    reveal = need.status == RESOLVED
    out["submissions"] = [_submission_line(engine, s, reveal) for s in submissions]
    resolution = dict(need.resolution or {})
    out["resolution"] = resolution
    if resolution.get("mode"):
        # Already rendered exactly at resolution time -- see engine.money.
        out["profit_awarded"] = resolution["awards"]
    return out


def round_briefing(engine, round_index):
    """The facts of one round -- the input to one newspaper edition (spec #26)."""
    record = engine.rounds[round_index]
    briefing = {
        "round": record.index,
        "starts_at": record.starts_at.isoformat(),
        "ends_at": record.ends_at.isoformat(),
        "lockstep": [dict(event) for event in record.events],
        "opened": None,
        "closed": None,
        "resolved": None,
        "mayor_question": None,
        # Whether a question went out at all, which is not an answer and so is
        # not gated by ``answers_shared_in_newspaper``. The paper needs the two
        # facts separately: an absent question and a withheld answer set both
        # leave ``mayor_question`` empty, and only one of them is something the
        # paper may remark on.
        "mayor_question_asked": record.question_id is not None,
        # City-only, never a handle (spec #28). The paper's corrections column
        # needs to know when the world grew, and "who is on the register" is
        # public in a way "who is behind the register" never is.
        "roster": {
            "cities": sorted(
                p.city for p in engine.players.values() if p.joined_round <= record.index
            ),
            "new_this_round": sorted(
                p.city for p in engine.players.values() if p.joined_round == record.index
            ),
            "mayors_seated": sum(
                1 for p in engine.players.values() if p.joined_round <= record.index
            ),
        },
        "newspaper": {
            "rendered_by": "newspaper.edition.build_edition(engine, %d)" % record.index,
        },
    }
    for event in record.events:
        if event.get("need") is None:
            continue
        need = engine.needs[event["need"]]
        if event["op"] == "OPEN":
            briefing["opened"] = need_briefing(engine, need)
        elif event["op"] == "CLOSE":
            briefing["closed"] = {
                "need": need.need_key,
                "importing_city": need.importing_city,
                "submission_count": event.get("submissions", 0),
            }
        elif event["op"] == "RESOLVE":
            briefing["resolved"] = need_briefing(engine, need)

    briefing["mayor_question"] = newspaper_mayor_question(engine, round_index)
    leaderboard = newspaper_leaderboard(engine, round_index)
    if leaderboard is not None:
        briefing["leaderboard"] = leaderboard
    return briefing


def published_rounds(engine):
    """The rounds that have finished, and so have an edition (spec #26).

    Spec #26 asks for publication "once per completed round", and the round the
    game is *currently* in is not one: its window is still open, mayors are
    still checking in, and an edition printed from it would be a different
    edition an hour later. That matters most to the archive, where spec #27
    promises a mayor that a link they were given keeps showing the paper they
    were shown.

    "Finished" has one definition here rather than two: a round's closing
    standing is frozen the instant the next round begins (see
    ``GameEngine._close_standings``), so a frozen standing *is* the round having
    ended, and this asks for that rather than re-deriving it from the clock.
    """
    return [
        index for index in sorted(engine.rounds)
        if engine.rounds[index].standings is not None
    ]


def archive(engine):
    """Every edition so far, oldest first (spec #27 -- an archive, not an overwrite)."""
    return {
        "game": "Sister Cities",
        "publication": "The Daily Manifest",
        "editions": [round_briefing(engine, index) for index in sorted(engine.rounds)],
        "phase": engine.phase,
        # The engine states where the paper is served; it does not know the
        # address and must not. That is `hosting.identity`'s, it is a secret
        # (the unguessable subdomain is the paper's only credential), and a
        # briefing is a payload -- payloads get written down.
        "hosting": {
            "served_by": "hosting.build_site -- an unguessable subdomain with robots "
                         "noindex, per the fulcra-dashboard pattern",
            "address": "withheld; see hosting.identity.SiteIdentity.describe()",
            "spec": "#26, #27",
        },
    }


def standings(engine):
    """The facilitator's own view of the economy -- **not** a newspaper payload.

    Always complete, regardless of ``economy.leaderboard_visible_in_newspaper``:
    the facilitator runs the game and needs the totals whether or not the paper
    prints them. It carries ``newspaper_visible`` so a caller building an
    edition can see at a glance that this is not the gated view it wants --
    that one is :func:`newspaper_leaderboard`.
    """
    economy = engine.economy
    total = sum(p.cumulative_profit for p in engine.players.values())
    return {
        "audience": "facilitator",
        "newspaper_visible": economy.leaderboard_visible,
        "leaderboard": engine.leaderboard(),
        "total_profit_awarded": money.to_json(total, economy.decimals),
        "economy": economy.describe(),
    }
