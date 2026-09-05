"""The city order queue and the two-rotation walk (spec #4, #5, #12).

Three rules govern the queue, and they interlock:

* **#4 -- facilitator first.** The facilitator's city always occupies position 1,
  so round 1 has an import need to open and nobody sits through a dead round.
* **#5 -- earn your place.** Every *other* player is appended to the queue only
  once their first export is accepted. They may export before that (and that is
  exactly how they get queued); they are not assigned an import need until they
  are in the queue.
* **#12 -- two rotations.** Players queued before rotation 1 closed get 2 import
  turns; players queued after it closed get 1.

#4 and #5 are what make each other work: the facilitator opens the first need,
everyone else answers it, and answering it is what puts them in the queue. The
queue therefore starts with exactly one entry and grows during rotation 1.

On reading #12: its prose says "players who join during/after rotation 1 get
only 1 import turn", but under #5 *every* non-facilitator player necessarily
joins the queue during rotation 1 -- which would give the whole table 1 turn and
make "players present from rotation 1 get 2" unreachable. The spec's own
Evaluation Criteria disambiguate it: "rotation-count assignment (2 imports vs 1)
matches whether they joined before or after rotation 1 **closed**". That is the
reading implemented here. See ``docs/m2-engine.md``.
"""


class CityQueue:
    """FIFO city order with a rotation-aware cursor."""

    def __init__(self, rotations_target):
        if rotations_target < 1:
            raise ValueError("rotations_target must be >= 1, got %r" % (rotations_target,))
        self.rotations_target = rotations_target
        self.order = []                 # player ids, queue position = index + 1
        self.rotation = 1
        self._cursor = 0                # next index to consider in this rotation
        self.rotation_closed_rounds = {}  # rotation number -> round it closed in
        self.exhausted = False          # every allotted import turn has been served
        #: The player whose turn is due but who is not ready for it -- since
        #: spec #13 a city's need is the one its mayor filed, so a mayor who has
        #: filed nothing has a turn the queue holds rather than fills. Set by
        #: :meth:`next_importer`, cleared by it or by :meth:`pass_over`.
        self.waiting_on = None
        #: Turns that were held past their grace and given up (see
        #: :meth:`pass_over`), as ``(player_id, round)``.
        self.passed_over = []

    # -- membership -------------------------------------------------------

    def seat_facilitator(self, player_id):
        """Put the facilitator at position 1 (spec #4)."""
        if self.order:
            raise ValueError(
                "the facilitator must be seated before anyone else so their city "
                "holds position 1 (spec #4); queue already holds %r" % (self.order,)
            )
        self.order.append(player_id)
        return 1

    def append(self, player_id):
        """Append a player who has just had their first export accepted (spec #5)."""
        if player_id in self.order:
            raise ValueError("player %r is already in the city order queue" % player_id)
        if not self.order:
            raise ValueError(
                "the facilitator holds position 1 (spec #4); seat them before appending"
            )
        self.order.append(player_id)
        return len(self.order)

    def position(self, player_id):
        return self.order.index(player_id) + 1 if player_id in self.order else None

    def allotment_for_new_entrant(self):
        """Import turns a player joining the queue *right now* is owed (spec #12).

        Rotation 1 still open -> the full ``rotations_target``. Otherwise a
        single turn, in the rotation they arrived in.
        """
        return self.rotations_target if self.rotation == 1 else 1

    # -- the walk ---------------------------------------------------------

    def next_importer(self, players, current_round, ready=None):
        """The player whose import need opens now, or ``None`` if the game is out.

        Walks the queue in order within the current rotation; when the cursor
        runs off the end, that rotation closes and the next begins. A player is
        due a turn while they have served fewer than their allotment, and the
        single pass per rotation is what limits them to one turn per rotation.

        ``ready(player_id)`` is spec #13's addition: since the importing mayor
        chooses their own import, a due mayor who has filed no order has nothing
        to open. The queue then **holds its place** -- returns ``None`` with
        :attr:`waiting_on` set, cursor untouched -- rather than moving on or
        substituting something. Whoever called decides how long to wait; see
        :meth:`pass_over` for giving up on the turn.
        """
        self.waiting_on = None
        while not self.exhausted:
            while self._cursor < len(self.order):
                player_id = self.order[self._cursor]
                player = players[player_id]
                if player.import_turns_served < player.import_turns_allotted:
                    if ready is not None and not ready(player_id):
                        self.waiting_on = player_id
                        return None
                    self._cursor += 1
                    return player_id
                self._cursor += 1
            # Cursor ran off the end: this rotation is over.
            self.rotation_closed_rounds.setdefault(self.rotation, current_round)
            if self.rotation >= self.rotations_target:
                self.exhausted = True
                return None
            self.rotation += 1
            self._cursor = 0
        return None

    def pass_over(self, player_id, current_round):
        """Give up on the held turn and let the queue move on (spec #13, #16).

        The mayor keeps their place for the next rotation and pays no penalty --
        the turn simply does not happen, which is the import-side reading of
        spec #16's "no penalty, no substitution". Called only after the caller's
        configured grace has run out, because the alternative to waiting is a
        game that never ends when one mayor stops answering.
        """
        if self.waiting_on != player_id:
            raise ValueError(
                "the queue is not waiting on %r (it is waiting on %r)"
                % (player_id, self.waiting_on)
            )
        self._cursor += 1
        self.waiting_on = None
        self.passed_over.append((player_id, current_round))
        return player_id

    def upcoming(self, players, limit=None):
        """Whose turns open next, in order, without moving the cursor.

        ``upcoming(...)[0]`` is the city whose need opens at the start of the
        next round, ``[1]`` the round after that, and so on -- which is what
        lets a check-in tell a mayor "your turn is two rounds away, file your
        order" (spec #13). Simulated on copies of the walk's state so asking
        the question cannot change the answer.
        """
        if self.exhausted:
            return []
        rotation, cursor, out = self.rotation, self._cursor, []
        served = {pid: players[pid].import_turns_served for pid in self.order}
        while True:
            while cursor < len(self.order):
                player_id = self.order[cursor]
                cursor += 1
                if served[player_id] < players[player_id].import_turns_allotted:
                    served[player_id] += 1
                    out.append(player_id)
                    if limit is not None and len(out) >= limit:
                        return out
            if rotation >= self.rotations_target:
                return out
            rotation += 1
            cursor = 0

    def turns_left_in_rotation(self, players):
        """How many turns the rotation now running still has to open.

        The first that many entries of :meth:`upcoming` are this rotation's;
        everything after them belongs to a later one. The distinction is what
        separates a *certain* distance from an *estimated* one: a player enters
        the queue by being appended to the end of ``order`` (spec #5), which
        lands ahead of every later-rotation turn and behind every turn left in
        this one. So a turn inside this rotation cannot be pushed back by a
        mayor who has not exported yet, and a turn past it can.
        See ``GameEngine._rounds_until_unfiled_turn``.
        """
        if self.exhausted:
            return 0
        return sum(
            1
            for player_id in self.order[self._cursor:]
            if players[player_id].import_turns_served
            < players[player_id].import_turns_allotted
        )

    def rounds_until_turn(self, players, player_id):
        """How many rounds until this mayor's need opens, or ``None``.

        1 means "at the start of the next round" -- this round's need has
        already opened by the time anybody asks.
        """
        upcoming = self.upcoming(players)
        return upcoming.index(player_id) + 1 if player_id in upcoming else None

    @property
    def rotation_1_closed(self):
        return 1 in self.rotation_closed_rounds

    def describe(self):
        return {
            "order": list(self.order),
            "rotation": self.rotation,
            "rotations_target": self.rotations_target,
            "rotation_closed_rounds": dict(self.rotation_closed_rounds),
            "exhausted": self.exhausted,
            "waiting_on": self.waiting_on,
            "passed_over": [
                {"player": player_id, "round": round_index}
                for player_id, round_index in self.passed_over
            ],
        }
