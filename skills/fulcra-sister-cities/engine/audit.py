"""Tripwires for the invariants that are easy to break silently.

Spec #21 ("a non-winning suggestion's origin city must never be exposed") and
spec #9 ("exactly one round timer") are both the kind of requirement that passes
review right up until someone adds a convenience field. These checks are written
so a test can assert them over *any* payload the engine produces, rather than
enumerating known payload shapes.
"""

from . import state
from .economy import NON_WINNER_ORIGIN_EXPOSURE, exposure_knob_match
from .errors import BlindVotingViolation, ExposurePolicyViolation
from .state import READ_AUDIT, READ_WINNER_REVEAL

#: Attribute names that would mean a second timer exists (spec #9).
_TIMER_WORDS = ("deadline", "expires", "expiry", "timer", "timeout", "closes_at", "due_at")

#: State classes whose instances must not carry their own deadline.
_TIMED_CLASSES = (state.ImportNeed, state.Submission, state.Player)


def find_extra_timers():
    """Structural check for spec #9: only ``RoundTimer`` may hold a deadline.

    Every other timing value in the game is computed from a round index, so any
    deadline-shaped field on a state object is a second timer by definition.
    """
    offenders = []
    for cls in _TIMED_CLASSES:
        for slot in getattr(cls, "__slots__", ()):
            lowered = slot.lower()
            if any(word in lowered for word in _TIMER_WORDS):
                offenders.append("%s.%s" % (cls.__name__, slot))
    return offenders


# -- payload walking -------------------------------------------------------

def _walk(node, path="$"):
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, "%s.%s" % (path, key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _walk(value, "%s[%d]" % (path, index))


def _subtree_strings(node):
    found = set()
    for _, value in _walk(node):
        if isinstance(value, str):
            found.add(value)
        elif isinstance(value, dict):
            found.update(k for k in value if isinstance(k, str))
    return found


def _identifies(node, submission):
    """How this dict node is *about* a submission: ``"text"``, ``"ref"`` or None.

    Matching on the export text or submission id is unambiguous. A bare ballot
    ref is a single letter, so it only counts when it sits under a ref-ish key --
    otherwise any payload containing the string "A" would look like a match --
    and even then it is only unambiguous *within one need*, which is why the
    reason is returned rather than a bare true. See :func:`_scoped_elsewhere`.
    """
    if not isinstance(node, dict):
        return None
    for key, value in node.items():
        if not isinstance(value, str):
            continue
        if value == submission.text or value == submission.submission_id:
            return "text"
    for key, value in node.items():
        if not isinstance(value, str):
            continue
        if submission.ballot_ref and value == submission.ballot_ref and "ref" in str(key).lower():
            return "ref"
    return None


def _scoped_elsewhere(path, submission, need_ids):
    """Whether ``path`` places this node inside a need that is not this one.

    Ballot refs are letters, assigned per need and starting again at "A" for the
    next one (:func:`engine.ballot.ref_for_index`), so "C" identifies a
    submission only in company with the need it was cast in. Without this, a
    record of the pick made in need 12 -- ``{"ballot_ref": "C", "by": ...}``,
    filed under need 12 -- matches the ref-C submission of every *other* need
    too, and a whole game's worth of correct records reads as a leak. An audit
    that fires on correct data is an audit people learn to wave through, so the
    scope is honoured rather than the noise tolerated.

    Only ref matches are narrowed. An export's text and its submission id are
    unique across the game, so a node carrying either identifies it wherever it
    appears, and a leak that quotes a losing offer under somebody else's need is
    still a leak.
    """
    if not need_ids:
        return False
    segments = path.replace("[", ".").replace("]", "").split(".")
    named = {segment for segment in segments if segment in need_ids}
    return bool(named) and submission.need_id not in named


def _innermost_identifying_nodes(payload, submission, need_ids=()):
    """The most specific nodes about a submission.

    Checking every ancestor would flag the whole payload (which legitimately
    contains a leaderboard naming every city). Checking only immediate values
    would miss a nested ``{"exporter": {"city": ...}}``. So: identifying nodes
    with no identifying descendant, subtree included.
    """
    matches = []
    for path, node in _walk(payload):
        reason = _identifies(node, submission)
        if reason is None:
            continue
        if reason == "ref" and _scoped_elsewhere(path, submission, need_ids):
            continue
        matches.append((path, node))

    def has_identifying_descendant(path):
        return any(
            other != path and (other.startswith(path + ".") or other.startswith(path + "["))
            for other, _ in matches
        )

    return [(path, node) for path, node in matches if not has_identifying_descendant(path)]


def find_identity_leaks(engine, payload):
    """Any place ``payload`` ties a non-winning submission to its exporter.

    Non-winning includes every submission of a need that has not resolved yet --
    during collection and voting, *no* submission's origin may surface.
    """
    leaks = []
    need_ids = frozenset(engine.needs)
    for submission in engine.submissions.values():
        need = engine.needs[submission.need_id]
        if need.status == state.RESOLVED and submission.is_winner:
            continue  # winners may be named
        city = engine.ledger.city_for(submission.submission_id, READ_AUDIT)
        player_id = engine.ledger.player_for(submission.submission_id, READ_AUDIT)
        handle = engine.players[player_id].handle
        identity = {value for value in (city, player_id, handle) if value}
        for path, node in _innermost_identifying_nodes(payload, submission, need_ids):
            exposed = identity & _subtree_strings(node)
            if exposed:
                leaks.append(
                    {
                        "submission_id": submission.submission_id,
                        "need": submission.need_id,
                        "path": path,
                        "exposed": sorted(exposed),
                        "spec": "#21 (and #18 while the need is unresolved)",
                    }
                )
    return leaks


def find_handle_leaks(engine, payload):
    """Real names/handles must not appear in anything player-facing (spec #28)."""
    strings = _subtree_strings(payload)
    return sorted(
        {p.handle for p in engine.players.values() if p.handle and p.handle in strings}
    )


def find_ballot_leaks(engine, ballot_payload, allow_cities=()):
    """No *exporter's* city may be named anywhere on a ballot.

    Two deliberate exceptions:

    * Export text. A mayor who signs their own export has chosen to identify
      themselves; the engine neither can nor should rewrite what they wrote.
      Everything the *engine* contributes to a ballot is still checked.
    * The importing city. It is the ballot's own header -- the voter obviously
      knows which of their needs they are voting on. Any need named in the
      payload contributes its importing city to the allow list.
    """
    allowed = set(allow_cities)
    for _, node in _walk(ballot_payload):
        if isinstance(node, dict):
            need_key = node.get("need")
            if isinstance(need_key, str) and need_key in engine.needs:
                allowed.add(engine.needs[need_key].importing_city)
    cities = {p.city for p in engine.players.values()} - allowed
    offenders = []
    for path, node in _walk(ballot_payload):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if key in ("export", "text", "need_brief", "title"):
                continue
            if isinstance(value, str) and value in cities:
                offenders.append({"path": "%s.%s" % (path, key), "city": value})
    return offenders


def find_ledger_misuse(engine):
    """Every de-anonymising read must have been for a legitimate reason.

    In particular, ``winner_reveal`` must never have been used on a submission
    that did not win -- that read is the one that would put a losing city's name
    in the paper.
    """
    misuse = []
    for access in engine.ledger.accesses:
        if access["reason"] != READ_WINNER_REVEAL:
            continue
        submission = engine.submissions.get(access["submission_id"])
        if submission is not None and not submission.is_winner:
            misuse.append(access)
    return misuse


#: Payload keys that only exist to publish something, mapped to the config flag
#: that decides whether they may be published at all (spec #22, #25). Checked
#: over the payload rather than over the view that builds it, so a newspaper
#: surface added later is covered without being enumerated here.
_GATED_KEYS = {
    "leaderboard": (
        # Read through Economy, which is where that decision is already taken --
        # the audit checks the same value the views check, not a second reading
        # of the same key that could drift from it.
        lambda engine: engine.economy.leaderboard_visible,
        "economy.leaderboard_visible_in_newspaper",
        "#22",
    ),
    "answers_by_city": (
        lambda engine: engine.config.require_bool(
            "facilitator_questions.answers_shared_in_newspaper"
        ),
        "facilitator_questions.answers_shared_in_newspaper",
        "#25",
    ),
}


def find_exposure_violations(engine, payload):
    """Anything ``payload`` publishes that config.json says to withhold (#22, #25)."""
    offenders = []
    for key, (visible, dotted, spec) in _GATED_KEYS.items():
        if visible(engine):
            continue
        for path, node in _walk(payload):
            if isinstance(node, dict) and key in node:
                offenders.append(
                    {
                        "path": "%s.%s" % (path, key),
                        "reason": "%s is false" % dotted,
                        "spec": spec,
                    }
                )
    return offenders


def find_origin_exposure_knobs(config_data):
    """Config keys that would make spec #21 configurable. There must be none.

    Spec #22 says exposure policy is config-driven; spec #21 is the one carve-out
    -- a losing export's origin is never exposed, so no knob may exist that
    could turn it on. This walks the raw config document rather than the keys the
    engine happens to read, because a knob nothing reads yet is still a knob
    somebody will wire up.
    """
    offenders = []
    for path, node in _walk(config_data):
        if not isinstance(node, dict):
            continue
        for key in node:
            if not isinstance(key, str):
                continue
            matched = exposure_knob_match(key)
            if matched:
                offenders.append(
                    {"path": "%s.%s" % (path, key), "matched": matched, "spec": "#21"}
                )
    return offenders


def assert_exposure_policy(engine, payload):
    """Raise if a newspaper payload exposes something #21/#22 forbid."""
    problems = {"exposure_violations": find_exposure_violations(engine, payload)}
    if NON_WINNER_ORIGIN_EXPOSURE:  # pragma: no cover - False, permanently (#21)
        problems["non_winner_origin_exposure"] = [
            "engine.economy.NON_WINNER_ORIGIN_EXPOSURE is True; spec #21 forbids it"
        ]
    failing = {key: value for key, value in problems.items() if value}
    if failing:
        raise ExposurePolicyViolation("exposure-policy audit failed: %r" % failing)
    return True


def assert_blind(engine, payload, ballots=()):
    """Raise if any blind-voting or identity invariant is violated."""
    problems = {
        "identity_leaks": find_identity_leaks(engine, payload),
        "handle_leaks": find_handle_leaks(engine, payload),
        "ledger_misuse": find_ledger_misuse(engine),
        "extra_timers": find_extra_timers(),
    }
    for ballot_payload in ballots:
        problems.setdefault("ballot_leaks", []).extend(
            find_ballot_leaks(engine, ballot_payload)
        )
    failing = {key: value for key, value in problems.items() if value}
    if failing:
        raise BlindVotingViolation("blind-voting audit failed: %r" % failing)
    return True
