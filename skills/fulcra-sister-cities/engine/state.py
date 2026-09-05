"""Game state objects.

The one structural decision worth reading before the rest: an export submission
does **not** know who sent it.

Spec #18 requires blind voting and spec #21 requires that a non-winning
submission's origin city is *never* exposed -- not to the importer during
voting, and not in the newspaper afterwards. Enforcing that with careful
redaction at every output site is the fragile version; one forgotten
``asdict()`` leaks the game. So :class:`Submission` carries no city and no
player id at all, and the mapping from submission to exporter lives in a
separate :class:`ExporterLedger` that records every read and the reason for it.

The consequence: leaking an exporter's identity requires deliberately asking the
ledger for it with a stated reason. It cannot happen by accident, and
``engine.audit`` can check the reasons after the fact.
"""

from fractions import Fraction

from .errors import BlindVotingViolation

# --- import-need lifecycle ------------------------------------------------
#
# A need opened in round r is COLLECTING during round r (its export window is
# that round -- the game has one timer, so the export window *is* the round),
# PICKING during round r+1 (spec #18 gives the importer a full window of their
# own), and RESOLVED at the start of round r+2.

COLLECTING = "collecting"
PICKING = "picking"
RESOLVED = "resolved"

# --- resolution modes -----------------------------------------------------

WINNER_PICK = "winner_pick"   # spec #18/#20 -- the importer chose
RAMP_UP = "ramp_up"           # spec #17 -- nobody submitted anything
EVEN_SPLIT = "even_split"     # spec #19 -- importer let the window lapse

# --- legitimate reasons to de-anonymise a submission ----------------------

READ_AWARD = "award_profit"          # a winner's city must be credited (#20)
READ_WINNER_REVEAL = "winner_reveal"  # winners may be named (#18 implies it)
READ_ENDGAME_EXCESS = "endgame_excess"  # spec #32, own-city view only
READ_CAP = "cap_enforcement"         # one submission per player per need (#15)
READ_AUDIT = "audit"                 # the leak tripwire itself
LEDGER_REASONS = frozenset(
    {READ_AWARD, READ_WINNER_REVEAL, READ_ENDGAME_EXCESS, READ_CAP, READ_AUDIT}
)


class Player:
    """A human and the city they speak for.

    ``handle`` is the real name/handle. Spec #28 says it must never appear in
    the newspaper, so no view in this package returns it; it exists only so the
    facilitator's agent can route a check-in to the right person.
    """

    __slots__ = (
        "player_id", "handle", "city", "is_facilitator", "joined_round",
        "queued_round", "import_turns_allotted", "import_turns_served",
        "import_turns_forfeited", "import_programme", "cumulative_profit",
    )

    def __init__(self, player_id, handle, city, is_facilitator, joined_round):
        self.player_id = player_id
        self.handle = handle
        self.city = city
        self.is_facilitator = is_facilitator
        self.joined_round = joined_round
        # Set when the player enters the city order queue (spec #5).
        self.queued_round = None
        self.import_turns_allotted = None
        self.import_turns_served = 0
        # Turns that came round while this mayor had filed no order and were
        # passed over rather than filled with something they did not choose
        # (spec #13, #16's no-penalty-no-substitution reading of a no-show).
        self.import_turns_forfeited = 0
        # The orders this mayor has filed and the game has not opened yet, in
        # the order they will open (spec #13). A need is only ever opened for a
        # city out of this list, which is what "cannot receive an unchosen
        # import" means structurally rather than as a promise.
        self.import_programme = []
        self.cumulative_profit = Fraction(0)

    @property
    def is_queued(self):
        return self.queued_round is not None

    @property
    def mayor(self):
        return "the Mayor of %s" % self.city

    def __repr__(self):
        return "Player(%s, %s%s)" % (
            self.player_id, self.city, ", facilitator" if self.is_facilitator else ""
        )


class Submission:
    """One freeform export (spec #15). Deliberately anonymous -- see module docs."""

    __slots__ = ("submission_id", "need_id", "text", "submitted_round", "ballot_ref", "is_winner")

    def __init__(self, submission_id, need_id, text, submitted_round):
        self.submission_id = submission_id
        self.need_id = need_id
        self.text = text
        self.submitted_round = submitted_round
        # Assigned when the export window closes, in shuffled order, so ballot
        # order carries no information about who submitted when.
        self.ballot_ref = None
        self.is_winner = False

    def __repr__(self):
        return "Submission(%s, need=%s, ref=%s)" % (
            self.submission_id, self.need_id, self.ballot_ref
        )


class ExporterLedger:
    """submission id -> exporter, with every read recorded and justified."""

    def __init__(self):
        self._by_submission = {}
        self.accesses = []

    def record(self, submission_id, player_id, city):
        self._by_submission[submission_id] = (player_id, city)

    def submissions_by(self, player_id, need_id, submissions):
        """Which of ``submissions`` came from this player -- for the #15 cap."""
        out = []
        for submission in submissions:
            owner = self._read(submission.submission_id, READ_CAP)
            if owner[0] == player_id and submission.need_id == need_id:
                out.append(submission)
        return out

    def city_for(self, submission_id, reason):
        return self._read(submission_id, reason)[1]

    def player_for(self, submission_id, reason):
        return self._read(submission_id, reason)[0]

    def _read(self, submission_id, reason):
        if reason not in LEDGER_REASONS:
            raise BlindVotingViolation(
                "refusing to de-anonymise submission %r for unrecognised reason %r; "
                "spec #21 allows only %s"
                % (submission_id, reason, sorted(LEDGER_REASONS))
            )
        if submission_id not in self._by_submission:
            raise KeyError("no exporter recorded for submission %r" % submission_id)
        self.accesses.append({"submission_id": submission_id, "reason": reason})
        return self._by_submission[submission_id]

    def all_submission_ids(self):
        return list(self._by_submission)


class ImportNeed:
    """One opened import need and everything that happened to it."""

    __slots__ = (
        "need_key", "content_need_id", "category", "importing_player_id", "importing_city",
        "rendered", "opened_round", "rotation", "closed_round", "resolved_round",
        "status", "pick", "resolution", "order",
    )

    def __init__(
        self, need_key, content_need_id, category, importing_player_id, importing_city,
        rendered, opened_round, rotation, order=None,
    ):
        self.need_key = need_key
        self.content_need_id = content_need_id
        self.category = category
        self.importing_player_id = importing_player_id
        self.importing_city = importing_city
        self.rendered = rendered
        self.opened_round = opened_round
        self.rotation = rotation
        # How this need came to be this city's: which mayor filed it, in which
        # round, from the slate or freehand (spec #13). Carried on the need
        # rather than looked up later, because "who chose this" is a fact of the
        # round it opened in and the paper prints it.
        self.order = dict(order or {})
        self.closed_round = None
        self.resolved_round = None
        self.status = COLLECTING
        # The importer's choice, recorded during the picking round as a *ballot
        # ref* -- never a city. Applied at the next lockstep RESOLVE.
        self.pick = None
        self.resolution = None

    def __repr__(self):
        return "ImportNeed(%s, %s, r%s, %s)" % (
            self.need_key, self.importing_city, self.opened_round, self.status
        )


class RoundRecord:
    """What the lockstep did in one round, in order (spec #9)."""

    __slots__ = (
        "index", "starts_at", "ends_at", "events", "question_id", "answers",
        "answer_buckets", "bucket_source", "standings", "completed",
    )

    def __init__(self, index, starts_at, ends_at):
        self.index = index
        self.starts_at = starts_at
        self.ends_at = ends_at
        self.events = []
        self.question_id = None
        self.answers = {}
        # The cumulative leaderboard as it stood when this round's lockstep
        # finished. An edition is a historical document: round 3's paper must go
        # on saying what round 3's standing was, however the game ends (spec #26,
        # #27). Taken once, at the end of the round, rather than recomputed when
        # somebody asks -- recomputing is how an archive of twelve editions ends
        # up printing the final table twelve times.
        self.standings = None
        # The clustering spec #25's aggregate is measured over, keyed by city:
        # ``None`` until somebody supplies one, because grouping freeform
        # answers is a judgement the engine will not make up (see
        # :mod:`engine.aggregate`).
        self.answer_buckets = None
        self.bucket_source = None
        # Set once, when the round finishes and the completed-round transaction
        # has run over it (spec #26). It is what stops a round being published
        # twice, and what ``engine.views.published_rounds`` means by "finished".
        self.completed = False

    def log(self, op, **detail):
        entry = {"op": op}
        entry.update(detail)
        self.events.append(entry)
        return entry

    @property
    def ops(self):
        return [event["op"] for event in self.events]
