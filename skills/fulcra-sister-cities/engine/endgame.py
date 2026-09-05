"""What a finished game amounts to (spec #31, #32).

The endgame's three articles -- the crown, the twist piece, one portrait per
city -- are prose, and prose is the :mod:`newspaper` package's job. This module
is the other half: the *facts* those articles are written from, assembled once,
from a game that has actually ended.

Two payloads, and the difference between them is the whole design:

* :func:`endgame_report` is **publishable**. Every winner it names won; every
  unchosen offer it carries is one that *arrived* at the city being described,
  reprinted with no sender, exactly as :mod:`newspaper.departments` already
  reprints declined offers round by round. Nothing in it pairs a non-winning
  offer with the city that sent it.
* :func:`mayor_excess_dossier` is **not publishable, ever**, and says so in the
  payload. It is one mayor's own account of what their city sent and what came
  home again -- which is the same information seen from the sender's end, and
  therefore precisely what spec #21 forbids printing. It is marked
  ``audience: facilitator`` so that :mod:`hosting.guard` refuses it structurally
  if anybody ever wires it into a page.

Why spec #32 needs both
-----------------------
Requirement #32 asks for a per-city description and image "treating each city's
non-chosen exports as 'excess'". Read one way that is the offers a city *sent*
and nobody chose; read the other way it is the offers that reached its own quay
and it declined. The second reading is publishable and the first is not -- and
the readings are the same pile counted from opposite ends, because every offer
one city sent and nobody chose is an offer some other city read and passed over.

So the world's excess is published in full, once, from the importing side, where
attribution is already public: which city declined it is a fact the paper has
printed all game (the notice was theirs), and which city *sent* it has never
been anywhere. Each city's portrait carries the pile on its own quay, the flavour
of what it declined, and an explicit statement that its own unchosen exports
exist, are somewhere in that city, and are nobody's business. The sender's-end
view exists, is complete, and goes to that city's own mayor as a dossier -- which
tells them nothing they did not already know, since they wrote it.

See ``docs/m7-endgame.md`` for the same argument at length.
"""

from fractions import Fraction

from . import money
from .errors import ContentError, PhaseError
from .state import (
    EVEN_SPLIT,
    RAMP_UP,
    READ_ENDGAME_EXCESS,
    READ_WINNER_REVEAL,
    RESOLVED,
    WINNER_PICK,
)

#: The reason a sender's-end excess list is not a newspaper payload. Quoted into
#: the dossier itself and into the published portraits, because a rule the
#: artifact states is a rule a reader can check.
SENDER_EXCESS_IS_PRIVATE = (
    "spec #21: a non-winning offer's origin city is never exposed, so the offers "
    "a city sent and nobody chose are not itemised in the paper -- not during the "
    "game and not in the last edition"
)


def _require_ended(engine, what):
    from .game import ENDED

    if engine.phase != ENDED:
        raise PhaseError(
            "%s is only defined for a finished game; this one is %s (spec #31 -- "
            "'at game end')" % (what, engine.phase)
        )


def _winner_city(engine, submission):
    """The city behind a *winning* submission. Winners may be named (#18, #20)."""
    return engine.ledger.city_for(submission.submission_id, READ_WINNER_REVEAL)


def _need_content(engine, need):
    """The seeded document behind a need, for its endgame excess flavour (#32)."""
    try:
        return engine.content.need_by_id(need.content_need_id)
    except ContentError:  # pragma: no cover - a need whose document was replaced
        return {}


def _excess_flavour(engine, need):
    """What an unchosen offer of this kind piles up as, per the seeded content.

    ``excess_flavor`` was written into ``content/import_needs.json`` for exactly
    this article and is keyed to the *need*, never to a sender. A need that has
    none (a player suggestion, say) falls back to naming its category, which is
    also public.
    """
    document = _need_content(engine, need)
    flavour = document.get("excess_flavor")
    if flavour:
        return flavour
    category = engine.content.categories.get(need.category) or {}
    return "%s, unclaimed" % category.get("label", need.category).lower()


def _import_record(engine, need):
    """One need this city opened, as the last edition may print it."""
    submissions = engine.submissions_for(need.need_key)
    resolution = dict(need.resolution or {})
    mode = resolution.get("mode")
    winners = [s for s in submissions if s.is_winner]
    declined = [s for s in submissions if not s.is_winner]
    document = _need_content(engine, need)

    record = {
        "need": need.need_key,
        "title": need.rendered["title"],
        "need_brief": need.rendered["need_brief"],
        "category": need.category,
        "category_label": (engine.content.categories.get(need.category) or {}).get(
            "label", need.category
        ),
        "opened_round": need.opened_round,
        "resolved_round": need.resolved_round,
        "rotation": need.rotation,
        "mode": mode,
        "offers_received": len(submissions),
        # Winners only. A declined offer is carried as text with no origin field
        # of any kind -- not None, not withheld, absent (see engine.views).
        "chosen": [
            {"export": s.text, "from_city": _winner_city(engine, s)} for s in winners
        ],
        "declined": [{"export": s.text} for s in declined],
        "excess_flavour": _excess_flavour(engine, need),
        "tags": list(document.get("tags") or ()),
    }
    if resolution.get("awards"):
        record["profit_awarded"] = resolution["awards"]
    if mode == RAMP_UP:
        record["ramped_up"] = True
    if mode == EVEN_SPLIT:
        record["split_between"] = [award["city"] for award in resolution["awards"]]
    return record


def _kept_exports(engine, city):
    """Everything this city sent that somebody chose. All of it public (#18)."""
    kept = []
    for need in engine.needs.values():
        if need.status != RESOLVED:  # pragma: no cover - a finished game has none
            continue
        for submission in engine.submissions_for(need.need_key):
            if not submission.is_winner:
                continue
            if _winner_city(engine, submission) != city:
                continue
            award = next(
                (a for a in (need.resolution or {}).get("awards", []) if a["city"] == city),
                None,
            )
            kept.append(
                {
                    "export": submission.text,
                    "to_city": need.importing_city,
                    "need_title": need.rendered["title"],
                    "category_label": (
                        engine.content.categories.get(need.category) or {}
                    ).get("label", need.category),
                    "round": need.resolved_round,
                    "mode": (need.resolution or {}).get("mode"),
                    "profit": award["profit"] if award else None,
                }
            )
    kept.sort(key=lambda entry: (entry["round"], entry["to_city"]))
    return kept


def _answers_for(engine, city):
    """This city's own answers to the mayoral questions, round by round.

    Individual answers are already newspaper material (:mod:`newspaper.wire`
    quotes them by city), so this is the same exposure decision, taken in the
    same place: :func:`engine.views.endgame_briefing` is what decides whether
    this list is included at all.
    """
    out = []
    for index in sorted(engine.rounds):
        record = engine.rounds[index]
        if record.question_id is None:
            continue
        answer = engine.answers_by_city(index).get(city)
        if not answer:
            continue
        question = engine.content.question_by_id(record.question_id)
        out.append(
            {
                "round": index,
                "question_id": record.question_id,
                "question": question["text"],
                "answer": answer,
            }
        )
    return out


def _city_dossier(engine, player, standing, include_leaderboard, include_answers):
    """One city at the end of the game, as the paper may draw it (spec #32)."""
    city = player.city
    imports = [
        _import_record(engine, need)
        for need in sorted(engine.needs.values(), key=lambda n: n.opened_round)
        if need.importing_city == city
    ]
    declined_received = [item for record in imports for item in record["declined"]]
    flavours = [record["excess_flavour"] for record in imports if record["declined"]]

    dossier = {
        "city": city,
        "mayor": player.mayor,
        "is_facilitator": player.is_facilitator,
        "joined_round": player.joined_round,
        "queued_round": player.queued_round,
        "import_turns_allotted": player.import_turns_allotted,
        "import_turns_served": player.import_turns_served,
        "imports": imports,
        "exports_kept": _kept_exports(engine, city),
        "ramped_up_rounds": [
            record["resolved_round"] for record in imports if record["mode"] == RAMP_UP
        ],
        "even_split_rounds": [
            record["resolved_round"] for record in imports if record["mode"] == EVEN_SPLIT
        ],
        "excess": {
            "declined_on_own_quay": len(declined_received),
            "declined_offers": declined_received,
            "flavours": flavours,
            "sent_and_not_chosen": {
                "itemised": False,
                "reason": SENDER_EXCESS_IS_PRIVATE,
                "available_to": "that city's own mayor, via "
                                "engine.endgame.mayor_excess_dossier",
                "spec": "#21, #32",
            },
        },
    }
    if include_answers:
        dossier["answers"] = _answers_for(engine, city)
    if include_leaderboard and standing is not None:
        dossier["rank"] = standing["rank"]
        dossier["tied"] = standing["tied"]
        dossier["profit"] = standing["profit"]
    return dossier


def _crown(board, decimals, include_leaderboard, wins_by_city, ramped_up_cities):
    """Who won on cumulative profit, and by how much (spec #31).

    The crown is named whether or not the standings were ever printed. Spec #22
    makes *the running table* an exposure decision; spec #31 makes the crowning a
    requirement, so a game that kept its leaderboard private still crowns a
    winner -- it simply does it without quoting the figure. ``profit_visible``
    says which of those happened, and the figure is absent rather than blanked
    when it is false.
    """
    top = board[0]["profit"]["exact"]
    winners = [row for row in board if row["profit"]["exact"] == top]
    others = [row for row in board if row["profit"]["exact"] != top]
    runner_up = others[0] if others else None

    crown = {
        "shared": len(winners) > 1,
        "n_cities": len(board),
        "profit_visible": include_leaderboard,
        "all_zero": board[0]["profit"]["approx"] == 0,
        "winners": [
            {
                "city": row["city"],
                "mayor": row["mayor"],
                "wins": wins_by_city.get(row["city"], 0),
                "ramped_up": row["city"] in ramped_up_cities,
                **({"profit": row["profit"]} if include_leaderboard else {}),
            }
            for row in winners
        ],
        "spec": "#31",
    }
    if include_leaderboard:
        crown["profit"] = board[0]["profit"]
        if runner_up is not None:
            margin = Fraction(board[0]["profit"]["exact"]) - Fraction(
                runner_up["profit"]["exact"]
            )
            crown["runner_up"] = {"city": runner_up["city"], "profit": runner_up["profit"]}
            crown["margin"] = money.to_json(margin, decimals)
    return crown


def endgame_report(engine, include_leaderboard=True, include_answers=True):
    """Everything the final edition may print, and nothing it may not.

    ``include_leaderboard`` and ``include_answers`` are the two exposure
    decisions (#22, #25). They are *parameters* rather than config reads because
    those decisions are taken in one place for the whole game --
    :func:`engine.views.newspaper_leaderboard` and
    :func:`engine.views.newspaper_mayor_question` -- and a second module reading
    the same keys is a second module that can disagree with the first.
    """
    _require_ended(engine, "the endgame report")
    decimals = engine.economy.decimals
    board = engine.leaderboard()
    standings = {row["city"]: row for row in board}

    arrivals = []
    ramp_ups = []
    even_splits = []
    modes = {WINNER_PICK: 0, RAMP_UP: 0, EVEN_SPLIT: 0}
    offers_sent = 0
    offers_chosen = 0
    excess_flavours = []
    categories = []
    wins_by_city = {}
    ramped_up_cities = set()

    for need in sorted(engine.needs.values(), key=lambda n: n.opened_round):
        resolution = need.resolution or {}
        mode = resolution.get("mode")
        if mode in modes:
            modes[mode] += 1
        category_label = (engine.content.categories.get(need.category) or {}).get(
            "label", need.category
        )
        if category_label not in categories:
            categories.append(category_label)
        submissions = engine.submissions_for(need.need_key)
        offers_sent += len(submissions)
        declined = 0
        for submission in submissions:
            if submission.is_winner:
                offers_chosen += 1
                city = _winner_city(engine, submission)
                wins_by_city[city] = wins_by_city.get(city, 0) + 1
                arrivals.append(
                    {
                        "need": need.need_key,
                        "title": need.rendered["title"],
                        "category": need.category,
                        "category_label": category_label,
                        "to_city": need.importing_city,
                        "from_city": city,
                        "export": submission.text,
                        "round": need.resolved_round,
                        "mode": mode,
                    }
                )
            else:
                declined += 1
        if declined:
            flavour = _excess_flavour(engine, need)
            if flavour not in excess_flavours:
                excess_flavours.append(flavour)
        if mode == RAMP_UP:
            ramped_up_cities.add(need.importing_city)
            ramp_ups.append(
                {
                    "city": need.importing_city,
                    "round": need.resolved_round,
                    "title": need.rendered["title"],
                    "category_label": category_label,
                }
            )
        elif mode == EVEN_SPLIT:
            even_splits.append(
                {
                    "city": need.importing_city,
                    "round": need.resolved_round,
                    "cities": len(resolution.get("awards") or ()),
                    "title": need.rendered["title"],
                }
            )

    questions_asked = [
        index for index in sorted(engine.rounds) if engine.rounds[index].question_id
    ]
    world = {
        "cities": len(engine.players),
        "needs": len(engine.needs),
        "rounds": len(engine.rounds),
        "rotations_reached": max(
            [need.rotation for need in engine.needs.values()] or [0]
        ),
        "offers_sent": offers_sent,
        "offers_chosen": offers_chosen,
        # The world's excess, in aggregate and with no city attached to any part
        # of it -- the one place the whole pile is counted (spec #21, #32).
        "excess_total": offers_sent - offers_chosen,
        "excess_flavours": excess_flavours,
        "modes": modes,
        "ramp_ups": ramp_ups,
        "even_splits": even_splits,
        "categories_asked": categories,
        "questions_asked": len(questions_asked),
    }
    if include_answers:
        world["answers_received"] = sum(
            len(engine.rounds[index].answers) for index in questions_asked
        )
    if include_leaderboard:
        world["total_profit"] = money.to_json(
            sum(player.cumulative_profit for player in engine.players.values()), decimals
        )

    report = {
        # No game or publication name here: those are the masthead's, they live in
        # content/newspaper.json, and the engine has never claimed to know them.
        "ended_round": engine.ended_round,
        "phase": engine.phase,
        "spec": "#31, #32",
        "crown": _crown(
            board, decimals, include_leaderboard, wins_by_city, ramped_up_cities
        ),
        "cities": [
            _city_dossier(
                engine, player, standings.get(player.city),
                include_leaderboard, include_answers,
            )
            for player in sorted(engine.players.values(), key=lambda p: p.city)
        ],
        "arrivals": arrivals,
        "world": world,
        "excess_policy": {
            "published_from": "the importing side -- an offer that arrived and was "
                              "declined, reprinted with no sender",
            "never_published": SENDER_EXCESS_IS_PRIVATE,
            "spec": "#21, #32",
        },
    }
    if include_leaderboard:
        # Named ``leaderboard`` on purpose: engine.audit gates that key against
        # economy.leaderboard_visible_in_newspaper, so calling it what it is puts
        # this payload under the same tripwire every other newspaper payload is
        # under, rather than beside it.
        report["leaderboard"] = board
    return report


def mayor_excess_dossier(engine, player_id):
    """One mayor's own account of what their city sent (spec #32) -- **private**.

    This is the sender's end of the excess, and it is the payload spec #21 exists
    to keep out of the newspaper: every entry pairs an offer with the city that
    sent it, including the ones nobody chose. It is legitimate for exactly one
    reader -- the mayor who wrote those offers, who is told nothing they do not
    already know -- and it is marked ``audience: facilitator`` so that publishing
    it is refused structurally by :mod:`hosting.guard` rather than caught by
    review.
    """
    _require_ended(engine, "a mayor's excess dossier")
    player = engine.players.get(player_id)
    if player is None:
        raise PhaseError("no such mayor %r" % (player_id,))

    sent = []
    for need in sorted(engine.needs.values(), key=lambda n: n.opened_round):
        for submission in engine.submissions_for(need.need_key):
            owner = engine.ledger.player_for(submission.submission_id, READ_ENDGAME_EXCESS)
            if owner != player_id:
                continue
            sent.append(
                {
                    "export": submission.text,
                    "need": need.need_key,
                    "need_title": need.rendered["title"],
                    "to_city": need.importing_city,
                    "round": submission.submitted_round,
                    "chosen": bool(submission.is_winner),
                }
            )
    excess = [entry for entry in sent if not entry["chosen"]]
    return {
        "audience": "facilitator",
        "for_player": player_id,
        "city": player.city,
        "mayor": player.mayor,
        "sent": sent,
        "chosen": [entry for entry in sent if entry["chosen"]],
        "excess": excess,
        "excess_count": len(excess),
        "publishable": False,
        "why_not": SENDER_EXCESS_IS_PRIVATE,
        "spec": "#21, #32",
    }
