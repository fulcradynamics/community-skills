"""The Sister Cities round-flow engine.

Implements spec #4, #5, #9-#12, #14-#19, #21 and #23-#25. Newspaper prose,
generated images and the *wording* of the mayor-question items belong to later
milestones; where this engine would need them it emits a clearly marked stub
instead (see ``resolution["newspaper"]``).

The lockstep (spec #9)
----------------------
The game has one timer. Every round performs exactly three operations, in this
order, and nothing else:

    OPEN     a new import need for the next city in the queue
    CLOSE    the export window of the need opened in the previous round
    RESOLVE  the winner of the need opened two rounds ago

which gives each need this life:

    round r      OPEN     -> collecting   (its export window *is* round r)
    round r + 1  CLOSE    -> picking      (the importer's own full window, #18)
    round r + 2  RESOLVE  -> resolved     (pick applied, or a fallback fires)

Exports for a need are collected during the round it opens; the importing mayor
picks during the following round, which is what spec #18 means by "the round
AFTER exports were collected". Because the last need still needs its collecting
and picking rounds, the final two rounds of a game OPEN nothing -- they close and
resolve the tail. Those two drain rounds are logged with the same three ops (with
``need: null`` on OPEN), so the lockstep invariant holds for every round of the
game without exception.

Who chooses the import (spec #13)
---------------------------------
OPEN does not draw. Since the user decision of 2026-08-31 an importing mayor
files their city's next import order themselves -- from a slate of eligible
seeds, or freehand -- and OPEN opens whatever is at the front of that city's
programme. There is no other way for a need to exist, which is the strong form
of "a city cannot receive an import nobody chose": not a promise, an absence.

A mayor with an unfiled turn is offered the order in their check-in as the round
of their turn approaches (``imports.choice_offered_rounds_ahead``); they may also
file earlier, and most do, at the table before the game starts. If a due mayor
has still filed nothing, the queue *holds* their turn for
``imports.unchosen_turn_grace_rounds`` rounds -- the round opens nothing rather
than opening something they did not ask for -- and then passes over it. A missed
import turn costs the mayor the turn and nothing else, which is spec #16's
no-penalty-no-substitution rule applied to the other side of the trade.
"""

import random
from datetime import timedelta

from . import aggregate, ballot
from .aggregate import Ladder
from .clock import ManualClock, RoundTimer, SystemClock, ensure_aware
from .config import Config
from .content import Content, normalize_city
from .economy import Economy
from .errors import (
    CheckInExhausted,
    ConfigError,
    ContentError,
    DuplicateCity,
    ImportChoiceRejected,
    PhaseError,
    PickRejected,
    RosterError,
    RuleViolation,
    SubmissionRejected,
)
from .join import CityRegistrar, join_player
from .rotation import CityQueue
from .state import (
    COLLECTING,
    EVEN_SPLIT,
    PICKING,
    RAMP_UP,
    READ_AWARD,
    RESOLVED,
    WINNER_PICK,
    ExporterLedger,
    ImportNeed,
    Player,
    RoundRecord,
    Submission,
)

_UNSET = object()

LOBBY = "lobby"
RUNNING = "running"
ENDED = "ended"

OP_OPEN = "OPEN"
OP_CLOSE = "CLOSE"
OP_RESOLVE = "RESOLVE"
#: The three lockstep operations, in the order spec #9 lists them. Every round
#: logs exactly this sequence.
LOCKSTEP_OPS = (OP_OPEN, OP_CLOSE, OP_RESOLVE)

SLOT_IMPORT_PICK = "import_pick"
SLOT_IMPORT_CHOICE = "import_choice"
SLOT_EXPORT = "export"
SLOT_QUESTION = "mayor_question"

#: How many slots one check-in has (spec #11, #23). Not configurable: two is
#: the requirement, not a preference.
CHECKIN_SLOTS = 2

#: The order the check-in fills its two slots with pending game actions.
#: A lapsed pick costs the whole table a winner (spec #19's even split), an
#: unfiled order costs its city the import turn (spec #13), and a missed export
#: costs one offer -- so they queue in that order, and the question fills what
#: is left over (spec #23).
GAME_ACTION_PRIORITY = (SLOT_IMPORT_PICK, SLOT_IMPORT_CHOICE, SLOT_EXPORT)

#: What gets held back when more game actions apply than the check-in has slots
#: for (spec #11a, user decision of 2026-09-03). Only the import-order choice is
#: deferrable, and deferring it is not a penalty: the order is for a turn that
#: has not come round yet, the round after this one will ask again, and the
#: queue holds an unfiled turn open besides (spec #13). An export cannot be
#: deferred in the same way -- the need it answers closes at the end of *this*
#: round -- so the trade in front of the mayor outranks the paperwork for the
#: one behind it. Priority above still decides which two of the survivors are
#: offered; this decides who leaves the room first.
DEFERRABLE_GAME_ACTIONS = (SLOT_IMPORT_CHOICE,)


class GameEngine:
    """One game of Sister Cities."""

    def __init__(self, config=None, content=None, clock=None, rng_seed=_UNSET):
        self.config = config if config is not None else Config.load()
        self.content = content if content is not None else Content.load(self.config)
        # Built here, before a round exists, so a malformed dice expression or
        # split mode is a startup error rather than a round-3 crash (spec #20).
        self.economy = Economy(self.config)
        # Same reason: the phrasing ladder spec #25's aggregate is selected from
        # is content, and a malformed one must not surface as a broken newspaper
        # item three rounds in. Building it here also means every game validates
        # its question bank, however its Content was constructed.
        self.content.check_question_policy(self.config)
        self.phrasing_ladder = Ladder.from_config(self.config, self.content)
        # And again: an unknown duplicate-pick resolution mode is a startup
        # error, not something the fifth player to join finds out about.
        self.registrar = CityRegistrar(self.config, self.content)
        # Same reason once more, for spec #13's three parameters. Two of them
        # are only consulted on a path a cooperative table never takes -- the
        # lookahead when somebody has not ordered yet, the grace when nobody
        # does -- so a typo in either would lie dormant until the first absent
        # mayor, which is the worst moment to discover it.
        self._validate_import_rules()
        self.clock = clock if clock is not None else SystemClock()
        self._seed = (
            self.config.require_nullable_int("engine.rng_seed")
            if rng_seed is _UNSET
            else rng_seed
        )

        self.players = {}
        self.needs = {}
        self.submissions = {}
        self.ledger = ExporterLedger()
        self.rounds = {}

        self.phase = LOBBY
        self.current_round = 0
        self.ended_round = None
        self.timer = None
        self.queue = CityQueue(self.config.require_int("rounds.rotations_target"))

        self._city_keys = {}
        self._checkin_used = {}
        # The set of game actions a round asks of a mayor, fixed the first time
        # the round is asked and reused after -- see :meth:`_pending_game_actions`.
        self._checkin_asks = {}
        self._asked_question_ids = []
        self._need_counter = 0
        self._submission_counter = 0
        self._freeform_counter = 0
        # Consecutive rounds the queue has held a turn open waiting for its
        # mayor to file an order (spec #13); cleared when they file or lose it.
        self._waited = {}
        # What runs when a round finishes -- see :meth:`on_round_completed`.
        # Empty here on purpose: the engine states that a round is complete and
        # the facilitator's desk decides that this means publishing a paper
        # (spec #26). An engine that imported the newspaper would be an engine
        # that could not be tested without one.
        self._round_completed_hooks = []
        # Transiently identifies a round whose standing has frozen and whose
        # required publication transaction is in progress.  It is deliberately
        # not durable: a failed transaction leaves ``completed`` false in the
        # canonical snapshot and is retried after a restart.
        self._completing_round = None

    # -- construction helpers ---------------------------------------------

    @classmethod
    def for_test(cls, start_at, rng_seed=1, config=None, content=None):
        """A game on a hand-advanced clock. Used by the test suite."""
        config = config if config is not None else Config.load()
        content = content if content is not None else Content.load(config)
        return cls(config=config, content=content, clock=ManualClock(start_at), rng_seed=rng_seed)

    def _validate_import_rules(self):
        """Spec #13's parameters, checked before a game exists (config.imports)."""
        suggestions = self.config.require_int("imports.suggestions_offered_to_importer")
        if suggestions < 1:
            raise ConfigError(
                "config.imports.suggestions_offered_to_importer must be at least 1; "
                "spec #13 requires a small set of eligible suggestions, got %d"
                % suggestions
            )
        ahead = self.config.require_int("imports.choice_offered_rounds_ahead")
        if ahead < 0:
            raise ConfigError(
                "config.imports.choice_offered_rounds_ahead must be 0 or more (0 asks "
                "only once the queue is already holding the turn open), got %d" % ahead
            )
        grace = self.config.require_int("imports.unchosen_turn_grace_rounds")
        if grace < 0:
            raise ConfigError(
                "config.imports.unchosen_turn_grace_rounds must be >= 0 (0 gives up "
                "on an unfiled turn at once), got %d" % grace
            )
        return {"suggestions": suggestions, "ahead": ahead, "grace": grace}

    def _rng(self, purpose, key=""):
        """A stream per (purpose, key), so adding a draw elsewhere cannot shift
        an unrelated one -- a game replayed from the same seed stays identical."""
        if self._seed is None:
            return random.Random()
        return random.Random("%s|%s|%s" % (self._seed, purpose, key))

    def __getstate__(self):
        """Persist game state, never a session-local facilitator hook.

        A ``Facilitator`` owns output directories, an address and an in-memory
        transaction receipt.  It is attached anew by the owning process after
        each snapshot load, rather than being carried into the next process and
        accidentally running old and new publication hooks together.
        """
        state = dict(self.__dict__)
        state["_round_completed_hooks"] = []
        state["_completing_round"] = None
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        # Also makes snapshots made before these fields existed safe to load
        # during the package's evolution.  ``_checkin_asks`` became durable
        # state when asks were fixed per round, so older snapshots correctly
        # start with no cached asks.
        self._round_completed_hooks = []
        self._completing_round = None
        self._checkin_asks = getattr(self, "_checkin_asks", {})

    # -- roster -----------------------------------------------------------

    def register_player(self, player_id, handle, city, is_facilitator=False):
        """Seat a player. Legal in the lobby and mid-game alike (spec #3)."""
        if self.phase == ENDED:
            raise RosterError("the game is over")
        if player_id in self.players:
            raise RosterError("player %r is already registered" % player_id)

        max_players = self.config.require_int("players.max_players")
        if len(self.players) >= max_players:
            raise RosterError(
                "this game is full at %d players (config.players.max_players)" % max_players
            )

        key = normalize_city(city)
        if self.config.require_bool("cities.enforce_unique_city_names") and key in self._city_keys:
            # Refused, never silently allowed to collide (spec #2). Resolving the
            # collision is the join/city-assignment milestone's job; the
            # candidates it needs travel with the error.
            raise DuplicateCity(city, key, self._city_keys[key], self.content.nearby_names(city))

        if is_facilitator:
            if self.facilitator is not None:
                raise RosterError(
                    "the facilitator is fixed for the whole game and does not rotate (spec #6)"
                )
            if self.phase != LOBBY:
                raise RosterError(
                    "the facilitator must be seated before the game starts -- their city holds "
                    "queue position 1 so round 1 has an import need to open (spec #4)"
                )

        player = Player(player_id, handle, city, is_facilitator, joined_round=self.current_round)
        self.players[player_id] = player
        self._city_keys[key] = player_id

        if is_facilitator:
            # Spec #4: position 1, and queued on arrival rather than on first
            # export -- that exemption is the whole point of the rule.
            self.queue.seat_facilitator(player_id)
            player.queued_round = self.current_round
            player.import_turns_allotted = self.queue.allotment_for_new_entrant()
        return player

    def join(self, player_id, handle, city, is_facilitator=False, rng=None):
        """Seat a player and resolve a duplicate city pick (spec #2).

        The door a facilitator's agent uses. :meth:`register_player` is the
        lower level: it refuses a collision and hands back the candidates, which
        is the right behaviour for something that must never seat two mayors on
        one city by accident, and the wrong behaviour for the only caller a
        joining player ever sees. See :mod:`engine.join`.
        """
        return join_player(self, player_id, handle, city, is_facilitator, rng=rng)

    def city_suggestions(self, rng=None):
        """Cities to offer a joining player, minus the ones already taken (#2)."""
        return {
            "cities": self.registrar.suggestions(self.claimed_cities(), rng=rng),
            "note": self.registrar.suggestion_note(),
            "spec": "#2",
        }

    def claimed_cities(self):
        """Every city this game currently holds, as the mayors spell them."""
        return [player.city for player in self.players.values()]

    @property
    def facilitator(self):
        for player in self.players.values():
            if player.is_facilitator:
                return player
        return None

    def player_for_city(self, city):
        player_id = self._city_keys.get(normalize_city(city))
        return self.players.get(player_id) if player_id else None

    def _player(self, player_id):
        try:
            return self.players[player_id]
        except KeyError:
            raise RosterError("unknown player %r" % player_id)

    # -- lifecycle --------------------------------------------------------

    def start(self, at=None):
        """Begin round 1."""
        if self.phase != LOBBY:
            raise PhaseError("this game has already started")
        min_players = self.config.require_int("players.min_players")
        if len(self.players) < min_players:
            raise RosterError(
                "need at least %d players to start (config.players.min_players), have %d"
                % (min_players, len(self.players))
            )
        if self.facilitator is None:
            raise RosterError(
                "a facilitator must be seated before the game starts (spec #4, #6)"
            )
        if not self.facilitator.import_programme:
            # Spec #4 puts the facilitator's city at position 1 precisely so
            # round 1 has a need to open; spec #13 says that need is the one
            # their mayor ordered. Both hold only if the order exists before the
            # timer starts, so this is a startup error rather than a dead round 1.
            raise ImportChoiceRejected(
                "%s opens round 1 (spec #4), and a city imports what its mayor "
                "ordered (spec #13) -- file the facilitator's first import order "
                "before starting the game: game.import_choice_offer(%r) then "
                "game.choose_import(%r, need_id=...)"
                % (self.facilitator.city, self.facilitator.player_id,
                   self.facilitator.player_id)
            )
        epoch = ensure_aware(at if at is not None else self.clock.now())
        window = timedelta(hours=self.config.require_number("rounds.round_window_hours"))
        self.timer = RoundTimer(epoch, window)
        self.phase = RUNNING
        return self._begin_round(1)

    def timers(self):
        """Every timer in the game. Spec #9 allows exactly one; this proves it."""
        return {"round": self.timer.describe()} if self.timer is not None else {}

    def advance_round(self):
        """Run the lockstep once. The only way rounds move."""
        if self.phase != RUNNING:
            raise PhaseError("cannot advance a game that is %s" % self.phase)
        current = self.rounds.get(self.current_round)
        if current is not None and not current.completed and self._game_is_over():
            # A caller may use the explicit advance API rather than waiting for
            # tick after final publication failed.  Retry that terminal round;
            # do not manufacture a successor after the game is already over.
            self.phase = ENDED
            self.ended_round = self.current_round
            try:
                self._complete_round(self.current_round)
            except Exception:
                self.phase = RUNNING
                self.ended_round = None
                raise
            return current
        return self._begin_round(self.current_round + 1)

    def tick(self, now=None):
        """Advance as many rounds as the one round timer says have elapsed."""
        if self.phase != RUNNING:
            return []
        now = ensure_aware(now if now is not None else self.clock.now())
        advanced = []
        # A final-round publication can fail after its lockstep operations have
        # made the game otherwise complete.  There is no later timer boundary to
        # enter _begin_round and retry it, so retry that same terminal round at
        # the next tick before considering a new round.
        current = self.rounds.get(self.current_round)
        if current is not None and not current.completed and self._game_is_over():
            self.phase = ENDED
            self.ended_round = self.current_round
            try:
                self._complete_round(self.current_round)
            except Exception:
                self.phase = RUNNING
                self.ended_round = None
                raise
            return advanced
        while self.phase == RUNNING and self.timer.round_index_at(now) > self.current_round:
            advanced.append(self._begin_round(self.current_round + 1))
        return advanced

    def _begin_round(self, index):
        # The previous round is over the instant this one starts, so this is
        # where it is completed -- its standing fixed, its edition published --
        # after every check-in it was going to get, including a mayor who joined
        # part-way through it.
        self._complete_round(index - 1)
        record = RoundRecord(index, self.timer.round_start(index), self.timer.round_end(index))
        self.rounds[index] = record
        self.current_round = index

        # Spec #9's three operations, in spec #9's order. Nothing else belongs
        # in this block -- the lockstep tests read `record.ops` literally.
        self._op_open(record)
        self._op_close(record)
        self._op_resolve(record)

        self._select_question(record)
        if self._game_is_over():
            # The final edition needs an ended game to render, but publication is
            # still part of completing this round.  Make that terminal state
            # provisional: if its completed-round transaction fails, restore the
            # running game so the same final round can be retried rather than
            # becoming an ended, unpublished game.
            self.phase = ENDED
            self.ended_round = index
            try:
                # No round follows this one, so nothing else will complete it --
                # and the last round's edition is also the one the endgame is
                # published with (spec #31), so it must not be skipped.
                self._complete_round(index)
            except Exception:
                self.phase = RUNNING
                self.ended_round = None
                raise
        return record

    def on_round_completed(self, hook):
        """Run ``hook(game, round_index)`` the moment a round finishes.

        This is spec #26's hinge. "Publishes exactly one redacted edition after
        every completed round ... a manually callable renderer alone does not
        satisfy this requirement" means something has to fire without anybody
        remembering to call it, and a round ending is the only honest trigger:
        it is the same instant the round's standing freezes, so an edition can
        never be printed from a round that is still moving.

        The engine holds the trigger and not the newspaper. It knows when a
        round is over; what to do about it -- render, publish, build the site,
        tell the group -- is the facilitator's completed-round transaction, in
        :mod:`facilitator`, which is where the newspaper and the hosting live.
        A hook that raises stops the game rather than letting a round pass
        unpublished, which is the right way round: an edition that could not be
        published (a redaction failure, a tone failure) is an emergency.
        """
        if not callable(hook):
            raise TypeError("a round-completed hook must be callable, got %r" % (hook,))
        self._round_completed_hooks.append(hook)
        return hook

    def _complete_round(self, index):
        """Finish one round, once: freeze its standing, then run the hooks."""
        record = self.rounds.get(index)
        if record is None or record.completed:
            return None
        self._close_standings(index)
        self._completing_round = index
        try:
            for hook in list(self._round_completed_hooks):
                hook(self, index)
        except Exception:
            # Do not let a failed rendering/publishing/notification transaction
            # turn into a silently skipped historical round.  Keeping completed
            # false makes the next tick (or a restarted facilitator) retry this
            # same transaction before a new round can begin.
            raise
        else:
            record.completed = True
        finally:
            self._completing_round = None
        return record

    def completed_rounds(self):
        return [index for index in sorted(self.rounds) if self.rounds[index].completed]

    def _close_standings(self, index):
        """Freeze one round's cumulative leaderboard, once (see RoundRecord).

        An edition is a historical document: the paper for round 3 must go on
        saying what round 3's table was, whatever happens afterwards (spec #26,
        #27). Without this, an archive of twelve editions prints the final table
        twelve times.
        """
        record = self.rounds.get(index)
        if record is not None and record.standings is None:
            record.standings = self.leaderboard()

    def _game_is_over(self):
        if not self.needs:
            return False
        return self.queue.exhausted and all(
            need.status == RESOLVED for need in self.needs.values()
        )

    # -- lockstep operations ----------------------------------------------

    def _op_open(self, record):
        """One new import need opens -- the one its mayor ordered (spec #9, #13).

        Nothing is drawn here. The queue says whose turn it is, and that city's
        own programme says what opens; a due mayor who has filed nothing has
        their turn held, and eventually passed over, rather than filled.
        """
        grace = self._validate_import_rules()["grace"]
        forfeited = []
        while True:
            importer_id = self.queue.next_importer(
                self.players, record.index, ready=self._has_filed_import_order
            )
            if importer_id is not None:
                break
            waiting_id = self.queue.waiting_on
            if waiting_id is None:
                record.log(
                    OP_OPEN,
                    need=None,
                    reason="no import turns remain; draining the last needs",
                    **({"forfeited": forfeited} if forfeited else {})
                )
                return None
            waiting = self.players[waiting_id]
            waited = self._waited.get(waiting_id, 0) + 1
            self._waited[waiting_id] = waited
            if waited <= grace:
                # Spec #13: no need opens rather than one this mayor did not
                # order. The round still runs its other two operations.
                record.log(
                    OP_OPEN,
                    need=None,
                    city=waiting.city,
                    reason="%s's import turn is held: its mayor has not filed an "
                           "order yet (spec #13)" % waiting.city,
                    rounds_held=waited,
                    grace_rounds=grace,
                    **({"forfeited": forfeited} if forfeited else {})
                )
                return None
            self.queue.pass_over(waiting_id, record.index)
            waiting.import_turns_forfeited += 1
            self._waited.pop(waiting_id, None)
            forfeited.append(waiting.city)

        player = self.players[importer_id]
        self._waited.pop(importer_id, None)
        order = player.import_programme.pop(0)
        need_doc = order["need"]

        self._need_counter += 1
        need = ImportNeed(
            need_key="in-%03d" % self._need_counter,
            content_need_id=need_doc["id"],
            category=need_doc["category"],
            importing_player_id=importer_id,
            importing_city=player.city,
            rendered=self.content.render_need(need_doc, player.city),
            opened_round=record.index,
            rotation=self.queue.rotation,
            order={
                "filed_by": player.mayor,
                "request_source": order["request_source"],
                "trade_family": need_doc.get("trade_family"),
                "filed_in_round": order["filed_in_round"],
                "spec": "#13, #13a",
            },
        )
        self.needs[need.need_key] = need
        player.import_turns_served += 1
        record.log(
            OP_OPEN,
            need=need.need_key,
            city=player.city,
            category=need.category,
            rotation=need.rotation,
            request_source=order["request_source"],
            **({"forfeited": forfeited} if forfeited else {})
        )
        return need

    def _has_filed_import_order(self, player_id):
        return bool(self.players[player_id].import_programme)

    def _op_close(self, record):
        """One export-collection window closes (spec #9)."""
        need = self._need_opened_in(record.index - 1)
        if need is None or need.status != COLLECTING:
            record.log(OP_CLOSE, need=None)
            return None
        submissions = self.submissions_for(need.need_key)
        # Refs are assigned here, at close, and in shuffled order -- so nothing
        # about ballot position can be read back as submission order (spec #18).
        ballot.assign_refs(self._rng("ballot", need.need_key), submissions)
        need.status = PICKING
        need.closed_round = record.index
        record.log(
            OP_CLOSE, need=need.need_key, submissions=len(submissions), city=need.importing_city
        )
        return need

    def _op_resolve(self, record):
        """One earlier round's winner gets picked (spec #9)."""
        need = self._need_opened_in(record.index - 2)
        if need is None or need.status != PICKING:
            record.log(OP_RESOLVE, need=None)
            return None
        resolution = self._resolve(need, record.index)
        record.log(
            OP_RESOLVE,
            need=need.need_key,
            mode=resolution["mode"],
            city=need.importing_city,
        )
        return need

    def _resolve(self, need, round_index):
        submissions = self.submissions_for(need.need_key)
        economy = self.economy
        rng = self._rng("profit", need.need_key)

        if not submissions:
            # Spec #17: nobody exported, so the importing city ramps up its own
            # industry and the importing mayor still takes the rolled profit.
            roll = economy.roll(rng)
            awards = economy.whole(need.importing_city, roll)
            mode = RAMP_UP
            winners = []
        elif need.pick is not None:
            # Spec #18/#20: the importer chose; the winning city takes the roll.
            roll = economy.roll(rng)
            winner = ballot.resolve_ref(submissions, need.pick["ballot_ref"])
            winner.is_winner = True
            winners = [winner]
            awards = economy.whole(
                self.ledger.city_for(winner.submission_id, READ_AWARD), roll
            )
            mode = WINNER_PICK
        else:
            # Spec #19: the picking window lapsed, so every submission wins and
            # the profit is split evenly among their cities.
            roll = economy.roll(rng)
            for submission in submissions:
                submission.is_winner = True
            winners = list(submissions)
            # Among their *cities*, not among their submissions. The two differ
            # only when config raises the #15 cap above one submission per
            # player -- and then splitting per submission would pay a city that
            # submitted twice a double share, making export spam profitable.
            # That is the incentive the cap exists to remove, so the split is
            # per distinct city, in first-submission order.
            cities = []
            for submission in winners:
                city = self.ledger.city_for(submission.submission_id, READ_AWARD)
                if city not in cities:
                    cities.append(city)
            awards = economy.split(cities, roll)
            mode = EVEN_SPLIT

        for city, amount in awards:
            earner = self.player_for_city(city)
            if earner is None:  # pragma: no cover - cities are registered players
                raise RuleViolation("cannot credit profit to unknown city %r" % city)
            economy.credit(earner, amount)

        need.status = RESOLVED
        need.resolved_round = round_index
        need.resolution = {
            "mode": mode,
            "roll": roll.to_dict(),
            "awards": economy.render_awards(awards),
            "submission_count": len(submissions),
            "winning_ballot_refs": [s.ballot_ref for s in winners],
            "spec": {
                WINNER_PICK: "#18, #20",
                RAMP_UP: "#17",
                EVEN_SPLIT: "#19",
            }[mode],
            # Prose, headline and image belong to the :mod:`newspaper` package;
            # the engine states the fact and the framing it needs, and stops.
            "newspaper": {
                "framing_hint": {
                    WINNER_PICK: "winner_chosen_by_importing_mayor",
                    RAMP_UP: "import_city_ramped_up_its_own_industry",
                    EVEN_SPLIT: "no_pick_by_deadline_every_submission_wins",
                }[mode],
                "written_by": "newspaper.departments.arrivals",
            },
        }
        return need.resolution

    # -- the importing mayor's own order (spec #13, #13a, #14) --------------

    def _import_allotment(self, player):
        """Import turns this mayor is owed, including one they have not earned yet.

        A player who has not exported yet is not in the queue and has no
        allotment (spec #5). They may still file an order: filing is not being
        assigned a need, the need opens only when their turn comes, and asking a
        joining mayor what their city needs is the natural first question to ask
        them. So an unqueued player is quoted the allotment they would take if
        they exported now.
        """
        if player.import_turns_allotted is not None:
            return player.import_turns_allotted
        return self.queue.allotment_for_new_entrant()

    def unfiled_import_turns(self, player_id):
        """Import turns this mayor has neither filed an order for nor lost."""
        player = self._player(player_id)
        return max(
            0,
            self._import_allotment(player)
            - player.import_turns_served
            - player.import_turns_forfeited
            - len(player.import_programme),
        )

    def _eligibility_rules(self, player):
        """What this city may still order, per spec #14 and config.imports.

        Orders already filed count exactly as opened needs do. Without that, two
        mayors could file the same seed on the same evening and the repetition
        rule would be enforced only against whoever happened to open first --
        which is the same rule holding by luck rather than by construction.
        """
        opened = list(self.needs.values())
        filed = [
            order for other in self.players.values() for order in other.import_programme
        ]
        return {
            "used_need_ids": (
                {need.content_need_id for need in opened}
                | {order["need"]["id"] for order in filed}
            ),
            "categories_used_by_city": (
                {n.category for n in opened if n.importing_player_id == player.player_id}
                | {order["need"]["category"] for order in player.import_programme}
            ),
            "categories_used_anywhere": (
                {need.category for need in opened}
                | {order["need"]["category"] for order in filed}
            ),
            "allow_repeat_for_same_city": self.config.require_bool(
                "imports.allow_repeat_category_for_same_city"
            ),
            "allow_repeat_across_cities": self.config.require_bool(
                "imports.allow_repeat_category_across_cities"
            ),
            "allow_need_reuse": self.config.require_bool(
                "imports.reuse_same_need_within_game"
            ),
        }

    def _rounds_until_unfiled_turn(self, player):
        """Rounds until the turn this mayor's next order would fill, or ``None``.

        Counted against the *unfiled* turn rather than the next one: a mayor who
        has already filed for their next turn is being asked about the one after
        it, and telling them it is one round away would be a lie in the
        direction that makes them hurry.

        A turn past the end of the rotation now running is quoted
        *pessimistically*, by one round for every registered mayor who has not
        taken their place in the queue yet. Those mayors are appended when their
        first export lands (spec #5), which puts them ahead of every
        later-rotation turn, so the queue as it stands is a floor and not a
        fact. Quoting the floor is what asks the facilitator in round 1 -- when
        theirs is the only city in the queue -- to order for a turn that will
        not open until round 5, which is precisely spec #13's "not prematurely".
        Erring the other way is recoverable and erring this way is not: a turn
        asked for a round late is held rather than lost (#13's grace), while a
        turn asked for four rounds early has already cost the mayor a slot.
        """
        if not player.is_queued:
            return None
        upcoming = self.queue.upcoming(self.players)
        positions = [i for i, pid in enumerate(upcoming) if pid == player.player_id]
        filed = len(player.import_programme)
        if filed >= len(positions):
            return None
        index = positions[filed]
        if index < self.queue.turns_left_in_rotation(self.players):
            return index + 1
        return index + 1 + sum(
            1 for other in self.players.values() if not other.is_queued
        )

    def import_choice_offer(self, player_id):
        """What this mayor may order for their city's next import turn (#13).

        ``None`` when they have no turn left to file for. Otherwise: a small
        slate of eligible seeds, every one of which they may take; the standing
        permission to write their own order instead; and how many rounds they
        have before the turn comes round. The slate is a suggestion and not a
        menu -- any eligible seed may be named, whether or not it was shown.
        """
        player = self._player(player_id)
        if self.phase == ENDED:
            return None
        if self.unfiled_import_turns(player_id) < 1:
            return None
        rules = self._eligibility_rules(player)
        count = self._validate_import_rules()["suggestions"]
        turn = player.import_turns_served + len(player.import_programme) + 1
        suggestions = self.content.suggest_needs(
            self._rng("slate", "%s|%d" % (player.city, turn)), player.city, count, **rules
        )
        return {
            "player_id": player_id,
            "city": player.city,
            "mayor": player.mayor,
            "turn": turn,
            "of": self._import_allotment(player),
            "opens_in_rounds": self._rounds_until_unfiled_turn(player),
            "queued": player.is_queued,
            "suggestions": [self._suggestion(need, player.city) for need in suggestions],
            "eligible_seeds": len(self.content.eligible_needs(**rules)),
            "freeform": self.content.trade.describe(),
            "note": "Take one of these, name any other eligible seed, or file your "
                    "own order. Whatever you choose is what your city imports when "
                    "its turn comes -- nothing is drawn for you (spec #13).",
            "spec": "#13, #13a, #14",
        }

    def _suggestion(self, need, city):
        category = self.content.categories.get(need["category"]) or {}
        rendered = self.content.render_need(need, city)
        return {
            "need_id": need["id"],
            "category": need["category"],
            "category_label": category.get("label", need["category"]),
            "trade_family": need.get("trade_family"),
            "title": rendered["title"],
            "need_brief": rendered["need_brief"],
            "exporter_prompt": rendered["exporter_prompt"],
            "source": need.get("source", "seed"),
        }

    def choose_import(self, player_id, need_id=None, request=None):
        """File this city's next import order (spec #13).

        Exactly one of ``need_id`` (an eligible seed, on the slate or not) and
        ``request`` (the mayor's own words, checked against spec #13a's trade
        policy). The order joins the city's programme and is what OPEN opens
        when the queue reaches them.

        The slot accounting is deliberately asymmetric. When the turn is close
        enough that the check-in is *asking* for the order, filing one uses that
        slot like any other game action (spec #11, #23). When it is not -- a
        mayor filing at the table before the game starts, or volunteering their
        second order early -- it costs nothing, because a mayor who says what
        their city wants before being asked has not taken a second turn at the
        round.
        """
        player = self._player(player_id)
        if self.phase == ENDED:
            raise PhaseError("the game is over")
        if (need_id is None) == (request is None):
            raise ImportChoiceRejected(
                "file exactly one of a seeded need id or a freeform request "
                "(spec #13 offers both, one at a time)"
            )
        if self.unfiled_import_turns(player_id) < 1:
            raise ImportChoiceRejected(
                "%s has no import turn left to file an order for (%d of %d served, "
                "%d already filed)"
                % (player.city, player.import_turns_served,
                   self._import_allotment(player), len(player.import_programme))
            )

        rules = self._eligibility_rules(player)
        if need_id is not None:
            try:
                need = self.content.need_by_id(need_id)
            except ContentError:
                raise ImportChoiceRejected(
                    "there is no import need %r to order; call import_choice_offer() "
                    "for what %s may take" % (need_id, player.city)
                )
            eligible = {candidate["id"] for candidate in self.content.eligible_needs(**rules)}
            if need_id not in eligible:
                raise ImportChoiceRejected(
                    "%s may not order %r: it is either already taken this game or in a "
                    "category %s has imported before (spec #14 / config.imports)"
                    % (player.city, need_id, player.city)
                )
            source = "seed"
        else:
            self._freeform_counter += 1
            need = self.content.trade.freeform_need(
                request,
                self.content.trade.freeform_id(self._freeform_counter),
                proposed_by_city=player.city,
            )
            self._assert_category_is_free(player, need["category"], rules)
            # Freeform orders join the pool (spec #33: the list players extend is
            # the list mayors order from), which also means the repetition rule
            # sees them without a second bookkeeping path.
            self.content.add_need(need)
            source = "freeform"

        # Guarded before anything is written down, so a refused check-in leaves
        # no half-filed order behind. "Asked" means the slot was actually
        # offered, not merely due: an order deferred under spec #11a was not
        # asked for, so filing it anyway costs no slot -- the same rule as
        # filing before being asked.
        asked_this_round = self.phase == RUNNING and self._import_choice_is_offered(player)
        if asked_this_round:
            self._guard_checkin(player_id, SLOT_IMPORT_CHOICE)

        order = {
            "need": need,
            "request_source": source,
            "filed_in_round": self.current_round,
            "filed_in_check_in": asked_this_round,
        }
        player.import_programme.append(order)
        self._waited.pop(player_id, None)
        if asked_this_round:
            self._mark_checkin(player_id, SLOT_IMPORT_CHOICE)
        return self.import_programme_for(player_id)[-1]

    def _assert_category_is_free(self, player, category, rules):
        if category not in self.content.categories:
            raise ImportChoiceRejected(
                "%r is not one of this game's import categories: %s"
                % (category, sorted(self.content.categories))
            )
        if not rules["allow_repeat_for_same_city"] and (
            category in rules["categories_used_by_city"]
        ):
            raise ImportChoiceRejected(
                "%s has already imported from %r and config.imports."
                "allow_repeat_category_for_same_city is false (spec #14)"
                % (player.city, category)
            )
        if not rules["allow_repeat_across_cities"] and (
            category in rules["categories_used_anywhere"]
        ):
            raise ImportChoiceRejected(
                "%r has been imported already this game and config.imports."
                "allow_repeat_category_across_cities is false (spec #14)" % category
            )

    def import_programme_for(self, player_id):
        """The orders this city has filed and the game has not opened yet."""
        player = self._player(player_id)
        return [
            {
                "need_id": order["need"]["id"],
                "category": order["need"]["category"],
                "trade_family": order["need"].get("trade_family"),
                "title": order["need"].get("title"),
                "request_source": order["request_source"],
                "filed_in_round": order["filed_in_round"],
                "filed_in_check_in": order["filed_in_check_in"],
            }
            for order in player.import_programme
        ]

    def _import_choice_is_due(self, player):
        """Whether this round's check-in should be asking this mayor to file.

        True when the turn is within ``imports.choice_offered_rounds_ahead``
        rounds, and true immediately when the queue is already holding the turn
        open for them -- at that point it is the most urgent thing the game
        wants from anybody.
        """
        if self.unfiled_import_turns(player.player_id) < 1:
            return False
        if self.queue.waiting_on == player.player_id:
            return True
        distance = self._rounds_until_unfiled_turn(player)
        if distance is None:
            return False
        return distance <= self._validate_import_rules()["ahead"]

    def _import_choice_is_offered(self, player):
        """Whether this round's check-in actually put the order in front of them.

        Due (:meth:`_import_choice_is_due`) and offered differ by exactly one
        thing: an order that was due but deferred to keep a mayor in the current
        trade (spec #11a).
        """
        offered, _ = self._pending_game_actions(player)
        return any(kind == SLOT_IMPORT_CHOICE for kind, _ in offered)

    # -- the round's mayor question ----------------------------------------

    def _select_question(self, record):
        """Draw this round's getting-to-know-you question (spec #23, #24).

        One question per round, asked of every mayor who checks in -- not a
        different question each. That is what makes spec #25's aggregate phrasing
        ("the world", "some countries") mean anything: it can only describe a
        distribution if everyone was asked the same thing.

        This is not a fourth lockstep operation and carries no timer of its own;
        it is bookkeeping attached to the round the check-ins belong to.
        """
        if not self.config.require_bool("facilitator_questions.enabled"):
            return None
        cadence = self.config.require_int("facilitator_questions.ask_every_n_rounds")
        if cadence < 1:
            raise ConfigError(
                "facilitator_questions.ask_every_n_rounds must be at least 1 (use "
                "enabled: false to stop asking), got %d" % cadence
            )
        if (record.index - 1) % cadence != 0:
            return None
        question = self.content.draw_question(
            self._rng("question", str(record.index)), self._asked_question_ids
        )
        if question is None:
            # The bank ran dry. Silence is the right failure here: a repeated
            # question would corrupt the aggregate it feeds.
            return None
        record.question_id = question["id"]
        self._asked_question_ids.append(question["id"])
        return question

    def asked_question_ids(self):
        return list(self._asked_question_ids)

    def _round_record(self, round_index):
        try:
            return self.rounds[round_index]
        except KeyError:
            raise RuleViolation("round %r has not happened" % (round_index,))

    def answers_by_city(self, round_index):
        """A round's answers keyed by city -- never by handle (spec #28).

        The city is the identity the newspaper and the aggregate both use; the
        player id and handle exist only so the facilitator's agent can route a
        check-in, and neither leaves the engine through this door.
        """
        record = self._round_record(round_index)
        return {
            self.players[player_id].city: answer
            for player_id, answer in record.answers.items()
        }

    def mayors_asked(self, round_index):
        """How many mayors this round's question was put to.

        Every mayor seated by that round. Deliberately the wider count: it is the
        denominator for the integrity rule that says an aggregate over some of
        the mayors must admit as much ("of the nine who replied..."), so counting
        a mayor whose two game actions crowded the question out errs toward
        disclosure rather than away from it.
        """
        record = self._round_record(round_index)
        return sum(1 for p in self.players.values() if p.joined_round <= record.index)

    def record_answer_buckets(self, round_index, buckets_by_city, source="facilitator"):
        """Cluster a round's answers, as ``{city: bucket label}`` (spec #25).

        The engine cannot do this itself and does not pretend to: deciding that
        "the fish counter" and "the market" are the same answer is a judgement.
        What it *can* do is refuse a clustering that would corrupt the aggregate
        -- one that drops a respondent or invents one -- and then do the
        arithmetic exactly, which is what
        :meth:`mayor_question_report` returns.

        Re-clustering is allowed while the game runs; whether an already
        published edition may be revised is the newspaper's rule (see the
        questions file's asking_rules on late answers), not this method's.
        """
        record = self._round_record(round_index)
        if record.question_id is None:
            raise RuleViolation("no mayor question was asked in round %d" % round_index)
        answers = self.answers_by_city(round_index)
        if not answers:
            raise RuleViolation(
                "nobody answered round %d's question, so there is nothing to cluster"
                % round_index
            )
        record.answer_buckets = aggregate.validate_bucketing(
            answers, self._resolve_bucket_cities(buckets_by_city)
        )
        record.bucket_source = source
        return dict(record.answer_buckets)

    def _resolve_bucket_cities(self, buckets_by_city):
        """Key a supplied clustering by the city names the game actually holds.

        "Reykjavik" and "Reykjavík" are the same city everywhere else in this
        engine (see :func:`engine.content.normalize_city`), so a clustering that
        spells one of them differently is accepted rather than reported as a
        mayor who both failed to answer and answered twice. Two spellings of the
        *same* city are refused, though -- collapsing them silently would drop
        one of the labels and change the distribution.
        """
        if not isinstance(buckets_by_city, dict):
            return buckets_by_city  # validate_bucketing owns this complaint
        resolved = {}
        for city, label in buckets_by_city.items():
            key = city
            if isinstance(city, str) and city.strip():
                player = self.player_for_city(city)
                if player is not None:
                    key = player.city
            if key in resolved:
                raise RuleViolation(
                    "%r and another key both name %s; a city gets one bucket" % (city, key)
                )
            resolved[key] = label
        return resolved

    def mayor_question_report(self, round_index):
        """One round's question, its answers, and what they add up to (spec #25).

        The facilitator's own view: always complete, whatever
        ``facilitator_questions.answers_shared_in_newspaper`` says. The gated,
        newspaper-facing version is
        :func:`engine.views.newspaper_mayor_question`, and that one function is
        where the exposure decision is taken.

        Returns ``None`` when the round asked no question at all.
        """
        record = self._round_record(round_index)
        if record.question_id is None:
            return None
        return aggregate.summarize(
            self.phrasing_ladder,
            round_index,
            self.content.question_by_id(record.question_id),
            self.answers_by_city(round_index),
            record.answer_buckets,
            self.mayors_asked(round_index),
            bucket_source=record.bucket_source,
        )

    # -- lookups ----------------------------------------------------------

    def _need_opened_in(self, round_index):
        if round_index < 1:
            return None
        for need in self.needs.values():
            if need.opened_round == round_index:
                return need
        return None

    def collecting_need(self):
        """The need whose export window is open right now (at most one, #9)."""
        for need in self.needs.values():
            if need.status == COLLECTING:
                return need
        return None

    def picking_need_for(self, player_id):
        """The need this player must pick a winner for this round, if any."""
        for need in self.needs.values():
            if need.status == PICKING and need.importing_player_id == player_id:
                return need
        return None

    def submissions_for(self, need_key):
        return [s for s in self.submissions.values() if s.need_id == need_key]

    # -- check-in ---------------------------------------------------------

    def checkin(self, player_id):
        """This player's one check-in for the current round (spec #11, #23).

        Two slots. Slot 1 is a pending game action if one exists. Slot 2 is a
        second pending game action if one exists, and otherwise a
        getting-to-know-you question for the mayor -- which is exactly spec #23's
        "if a second game action isn't pending, a question fills that slot".

        "Pending" means pending *for the round*, not "still undone right now".
        The distinction matters: if it meant the latter, a mayor who submitted
        their export first would then be offered a question, and answering it
        would eat the slot their still-outstanding winner pick needed. The set of
        slots a round offers is fixed when the round opens; ``slots`` below just
        omits the ones already filled.

        When more than two game actions apply, the surplus is deferred rather
        than truncated away -- see :meth:`_pending_game_actions` and spec #11a.
        What was held back is reported under ``deferred``, as a note and not as
        a slate: a mayor is told their order can wait, not asked for it.
        """
        player = self._player(player_id)
        if self.phase != RUNNING:
            raise PhaseError("no check-ins while the game is %s" % self.phase)
        used = self._checkin_used.get((player_id, self.current_round), {})
        deadline = self.rounds[self.current_round].ends_at

        applicable, deferred = self._pending_game_actions(player)

        outstanding = [
            self._game_action_slot(player, kind, need, deadline)
            for kind, need in applicable
            if used.get(kind, 0) < self._slot_allowance(kind)
        ]
        slots = [
            outstanding[index] if index < len(outstanding) else None
            for index in range(CHECKIN_SLOTS)
        ]

        gate = self.config.require_bool(
            "facilitator_questions.fill_second_slot_only_if_no_second_game_action_pending"
        )
        second_game_action_pending = len(applicable) > 1
        if not (gate and second_game_action_pending):
            question_slot = self._question_slot(player_id, used, deadline)
            if question_slot is not None:
                if slots[1] is None:
                    slots[1] = question_slot
                else:
                    # Only reachable with the gate switched off in config, which
                    # is what switching it off means.
                    slots.append(question_slot)

        return {
            "round": self.current_round,
            "player_id": player_id,
            "city": player.city,
            "mayor": player.mayor,
            "queued": player.is_queued,
            "deadline": deadline.isoformat(),
            "slots": slots,
            "pending_game_actions": len(applicable),
            "deferred": [self._deferral_notice(player, kind) for kind, _ in deferred],
            "already_used": dict(used),
        }

    def _pending_game_actions(self, player):
        """What this round asks of this mayor: ``(offered, deferred)``.

        Every game action that applies to them this round, in
        ``GAME_ACTION_PRIORITY`` order -- regardless of what they have already
        done, because the set is fixed for the round -- split at the two-slot
        budget (spec #11, #23).

        Fixed, and therefore worked out once and remembered. Most of what makes
        an action apply cannot move mid-round anyway (needs open, close and
        resolve at round boundaries, spec #9), but one thing can: an import
        order falls due the moment its mayor's first export puts them in the
        queue (spec #5), and stops being due the moment they file it. Recomputed
        each time, that turns one check-in into two different check-ins -- a
        mayor offered an export and a question, who exports and is then told no
        question was ever pending; a mayor offered a pick and an order, who
        files the order and finds a question in the freed slot, taking three
        actions in a two-action round. Both are the budget leaking through a
        recomputation, so the answer is not to recompute.

        Which one leaves when three apply is spec #11a, and it is not the same
        question as which one comes first. Priority ranks the three by what
        missing them costs: a lapsed pick costs the table a winner, an unfiled
        order costs a city its import turn, a missed export costs one offer. But
        cost is not the whole story once something has to go, because the three
        do not have the same deadline. An export answers a need that closes at
        the end of *this* round; an import order is for a turn that has not come
        round yet, will be asked for again next round, and is held open by the
        queue if it still is not filed. So the order defers and the export
        stands -- "an eligible export to the currently open import need must
        never be displaced by a prompt to file a future import order" (spec
        #11a). Truncating the priority list instead is what made a mayor with a
        pick and an order sit out a trade they were eligible for.
        """
        key = (player.player_id, self.current_round)
        if key not in self._checkin_asks:
            applicable = []
            pick_need = self.picking_need_for(player.player_id)
            if pick_need is not None and self.submissions_for(pick_need.need_key):
                applicable.append((SLOT_IMPORT_PICK, pick_need))
            if self._import_choice_is_due(player):
                applicable.append((SLOT_IMPORT_CHOICE, None))
            open_need = self.collecting_need()
            if open_need is not None and self._export_slot_applies(player, open_need):
                applicable.append((SLOT_EXPORT, open_need))
            # Ordered by the table above rather than by the order they were
            # appended in, so the priority is a fact of GAME_ACTION_PRIORITY and
            # not of how this function happens to be written.
            applicable.sort(key=lambda item: GAME_ACTION_PRIORITY.index(item[0]))
            self._checkin_asks[key] = applicable
        applicable = self._checkin_asks[key]

        offered, deferred = list(applicable), []
        while len(offered) > CHECKIN_SLOTS:
            surplus = [item for item in offered if item[0] in DEFERRABLE_GAME_ACTIONS]
            if not surplus:
                # Unreachable while the deferrable set covers every way three
                # actions can co-apply; if that ever stops being true the budget
                # still holds, by dropping the lowest-priority action.
                surplus = [offered[-1]]
            offered.remove(surplus[-1])
            deferred.append(surplus[-1])
        return offered, deferred

    def _deferral_notice(self, player, kind):
        """A held-back action, told as a note rather than offered as a slot.

        Deliberately not the slate :meth:`import_choice_offer` builds: the point
        of deferring is that the check-in is *not* asking this round (spec #11a),
        and a mayor who volunteers an order anyway may still file one -- it costs
        no slot, exactly as filing before being asked never has.
        """
        if kind != SLOT_IMPORT_CHOICE:
            return {"kind": kind, "deferred_to": "a later round", "spec": "#11a"}
        return {
            "kind": SLOT_IMPORT_CHOICE,
            "opens_in_rounds": self._rounds_until_unfiled_turn(player),
            "reason": "your city's next import order can wait a round; this "
                      "round's trade cannot (spec #11a). You will be asked "
                      "again, and you may file one now if you like -- it costs "
                      "you nothing.",
            "spec": "#11a, #13",
        }

    def _slot_allowance(self, kind):
        """How many times a slot kind may be used in one round.

        One for a pick and one for a question; for exports it is the configured
        per-need cap, so raising ``max_submissions_per_player_per_import_per_round``
        actually raises it rather than being silently overruled by a
        one-use-per-slot assumption baked into the check-in.
        """
        if kind == SLOT_EXPORT:
            return self.config.require_int(
                "exports.max_submissions_per_player_per_import_per_round"
            )
        return 1

    def _game_action_slot(self, player, kind, need, deadline):
        if kind == SLOT_IMPORT_CHOICE:
            # Spec #13's slot: the whole offer, in the check-in, because a mayor
            # being asked to order needs the slate in front of them and not a
            # pointer to a second call they might not make.
            return dict(
                self.import_choice_offer(player.player_id) or {},
                kind=SLOT_IMPORT_CHOICE,
                deadline=deadline.isoformat(),
                note="File your city's next import: take one of these, name any "
                     "other eligible seed, or write your own order. Nothing is "
                     "drawn for you, and an unfiled turn is held and then lost "
                     "(spec #13).",
            )
        if kind == SLOT_IMPORT_PICK:
            return {
                "kind": SLOT_IMPORT_PICK,
                "need": need.need_key,
                "need_brief": need.rendered["need_brief"],
                "ballot": ballot.build(self.submissions_for(need.need_key)),
                "deadline": deadline.isoformat(),
                "note": "Pick by ballot ref. Which city sent which export is not on "
                        "this ballot and will not be revealed for the ones you "
                        "don't pick (spec #18, #21).",
            }
        return {
            "kind": SLOT_EXPORT,
            "need": need.need_key,
            "importing_city": need.importing_city,
            "importing_mayor": self.players[need.importing_player_id].mayor,
            "need_brief": need.rendered["need_brief"],
            "exporter_prompt": need.rendered["exporter_prompt"],
            "deadline": deadline.isoformat(),
        }

    def _export_slot_applies(self, player, need):
        """Whether this round asks this player for an export at all.

        Deliberately independent of the per-round submission cap: the cap says
        whether the slot is *already filled*, not whether it exists.
        """
        if need.importing_player_id == player.player_id:
            return self.config.require_bool("exports.importer_may_export_to_own_need")
        return True

    def _question_slot(self, player_id, used, deadline):
        record = self.rounds[self.current_round]
        if record.question_id is None or used.get(SLOT_QUESTION, 0):
            return None
        if player_id in record.answers:
            return None
        cap = self.config.require_int("facilitator_questions.max_per_player_per_round")
        if cap < 1:
            return None
        if cap > 1:
            raise ConfigError(
                "facilitator_questions.max_per_player_per_round is %d, but spec #23 gives "
                "a mayor a two-slot check-in of which at most one slot can be a question; "
                "use 0 to suppress questions or 1 to ask one" % cap
            )
        question = self.content.question_by_id(record.question_id)
        return {
            "kind": SLOT_QUESTION,
            "question_id": question["id"],
            "text": question["text"],
            # Present on every question in the bank, and checked against
            # config.facilitator_questions.framing at load rather than defaulted
            # here (spec #24).
            "framing": question["framing"],
            "answer_shape": question.get("answer_shape"),
            # The same round deadline the game-action slots carry: a question is
            # part of the one check-in, not a phase with a clock of its own (#9).
            "deadline": deadline.isoformat(),
            "optional": True,
            "note": "Answering is optional; a mayor who skips leaves the "
                    "denominator rather than counting as a null answer. What the "
                    "answers add up to is decided in engine.aggregate; "
                    "newspaper.wire writes the sentence from that.",
        }

    def _guard_checkin(self, player_id, kind):
        """One check-in per round, one use per slot kind (spec #11).

        There is no separate "at most two actions" counter, and there must not
        be: the two-slot budget is already enforced by what ``checkin`` offers --
        there are only two game-action kinds, each usable once, and the question
        is offered only when a second game action is not pending. A numeric
        counter on top of that would double-count and could block a legitimate
        pending pick.
        """
        used = self._checkin_used.setdefault((player_id, self.current_round), {})
        allowance = self._slot_allowance(kind)
        if used.get(kind, 0) >= allowance:
            raise CheckInExhausted(
                "%s already used their %s slot %d time(s) in round %d (spec #11: each "
                "player checks in and acts at most once per round)"
                % (player_id, kind, allowance, self.current_round)
            )
        return used

    def _mark_checkin(self, player_id, kind):
        used = self._checkin_used.setdefault((player_id, self.current_round), {})
        used[kind] = used.get(kind, 0) + 1

    def checkin_used(self, player_id, round_index=None):
        """Slot kinds this player has already used this round (with counts)."""
        round_index = round_index if round_index is not None else self.current_round
        return dict(self._checkin_used.get((player_id, round_index), {}))

    # -- player actions ---------------------------------------------------

    def submit_export(self, player_id, text, need_key=None):
        """Submit a freeform export (spec #15).

        Accepting a player's *first* export is also what puts them in the city
        order queue (spec #5) -- exports are allowed before being queued, and
        are the way in.
        """
        if self.phase != RUNNING:
            raise PhaseError("no exports while the game is %s" % self.phase)
        player = self._player(player_id)

        need = self.collecting_need() if need_key is None else self.needs.get(need_key)
        if need is None:
            raise SubmissionRejected("no import need is collecting exports right now")
        if need.status != COLLECTING:
            raise SubmissionRejected(
                "the export window for %s closed in round %s; it is %s now"
                % (need.need_key, need.closed_round, need.status)
            )
        if need.importing_player_id == player_id and not self.config.require_bool(
            "exports.importer_may_export_to_own_need"
        ):
            raise SubmissionRejected(
                "%s opened this import need; a mayor does not export to themselves"
                % player.city
            )
        if not isinstance(text, str) or not text.strip():
            raise SubmissionRejected("an export is freeform text and must say something (spec #15)")

        cap = self.config.require_int("exports.max_submissions_per_player_per_import_per_round")
        mine = self.ledger.submissions_by(
            player_id, need.need_key, self.submissions_for(need.need_key)
        )
        if len([s for s in mine if s.submitted_round == self.current_round]) >= cap:
            raise SubmissionRejected(
                "%s already submitted %d export(s) for %s this round (cap is "
                "config.exports.max_submissions_per_player_per_import_per_round=%d)"
                % (player.city, len(mine), need.need_key, cap)
            )

        self._guard_checkin(player_id, SLOT_EXPORT)

        self._submission_counter += 1
        submission = Submission(
            submission_id="ex-%04d" % self._submission_counter,
            need_id=need.need_key,
            text=text.strip(),
            submitted_round=self.current_round,
        )
        self.submissions[submission.submission_id] = submission
        # The only place the exporter's identity is written down.
        self.ledger.record(submission.submission_id, player_id, player.city)

        if not player.is_queued:
            self.queue.append(player_id)
            player.queued_round = self.current_round
            player.import_turns_allotted = self.queue.allotment_for_new_entrant()

        self._mark_checkin(player_id, SLOT_EXPORT)
        return submission

    def pick_winner(self, player_id, ballot_ref, need_key=None):
        """The importing mayor picks a winner by ballot ref (spec #18).

        There is no overload that takes a city: the importer cannot name an
        exporter because the API gives them no way to.
        """
        if self.phase != RUNNING:
            raise PhaseError("no winner picks while the game is %s" % self.phase)
        self._player(player_id)
        need = self.picking_need_for(player_id) if need_key is None else self.needs.get(need_key)
        if need is None:
            raise PickRejected("you have no import need awaiting a winner this round")
        if need.importing_player_id != player_id:
            raise PickRejected(
                "only the importing mayor of %s picks that winner (spec #18)"
                % need.importing_city
            )
        if need.status != PICKING:
            raise PickRejected(
                "%s is %s, not awaiting a pick" % (need.need_key, need.status)
            )
        if need.closed_round != self.current_round:
            raise PickRejected(
                "the picking window for %s was round %s; it is round %d"
                % (need.need_key, need.closed_round, self.current_round)
            )
        if need.pick is not None:
            raise PickRejected("a winner for %s has already been picked" % need.need_key)

        submissions = self.submissions_for(need.need_key)
        if not submissions:
            raise PickRejected(
                "nothing was submitted for %s, so there is nothing to pick; %s ramps up "
                "its own industry instead (spec #17)" % (need.need_key, need.importing_city)
            )
        submission = ballot.resolve_ref(submissions, ballot_ref)

        self._guard_checkin(player_id, SLOT_IMPORT_PICK)
        need.pick = {
            "ballot_ref": ballot_ref,
            "submission_id": submission.submission_id,
            "picked_round": self.current_round,
        }
        self._mark_checkin(player_id, SLOT_IMPORT_PICK)
        return need.pick

    def answer_question(self, player_id, answer):
        """Record a mayor's answer. Phrasing and aggregation are M5/M6's job."""
        if self.phase != RUNNING:
            raise PhaseError("no answers while the game is %s" % self.phase)
        self._player(player_id)
        record = self.rounds[self.current_round]
        if record.question_id is None:
            raise RuleViolation(
                "no mayor question was asked in round %d (config.facilitator_questions)"
                % self.current_round
            )
        if player_id in record.answers:
            raise CheckInExhausted(
                "%s already answered round %d's question (spec #11)"
                % (player_id, self.current_round)
            )
        offered = self.checkin(player_id)["slots"]
        if not any(slot and slot["kind"] == SLOT_QUESTION for slot in offered):
            raise RuleViolation(
                "round %d offered %s no question slot -- a second game action was "
                "pending (spec #23)" % (self.current_round, player_id)
            )
        if not isinstance(answer, str) or not answer.strip():
            raise RuleViolation("an answer must say something, or be skipped entirely")
        self._guard_checkin(player_id, SLOT_QUESTION)
        record.answers[player_id] = answer.strip()
        self._mark_checkin(player_id, SLOT_QUESTION)
        return record.answers[player_id]

    def suggest_import_need(self, player_id, need):
        """Add a player-suggested import need to the pool (spec #13)."""
        self._player(player_id)
        if not self.config.require_bool("content.allow_player_suggested_import_needs"):
            raise RuleViolation(
                "player-suggested import needs are disabled "
                "(config.content.allow_player_suggested_import_needs)"
            )
        return self.content.add_player_need(need)

    # -- reporting --------------------------------------------------------

    def leaderboard(self):
        """Cumulative per-city profit (spec #20).

        Whether the *newspaper* shows this is a separate, config-driven exposure
        decision (spec #22) taken in one place: ``views.newspaper_leaderboard``.
        This method is the facilitator's own view and is always populated --
        gating it here too would mean a hidden leaderboard also stops the engine
        from being able to crown a winner at the end (#31).
        """
        return self.economy.leaderboard(self.players.values())

    def describe(self):
        return {
            "phase": self.phase,
            "current_round": self.current_round,
            "ended_round": self.ended_round,
            "timers": self.timers(),
            "queue": self.queue.describe(),
            "players": {
                pid: {
                    "city": p.city,
                    "is_facilitator": p.is_facilitator,
                    "joined_round": p.joined_round,
                    "queued_round": p.queued_round,
                    "queue_position": self.queue.position(pid),
                    "import_turns_allotted": p.import_turns_allotted,
                    "import_turns_served": p.import_turns_served,
                    "import_turns_forfeited": p.import_turns_forfeited,
                    "import_orders_filed": self.import_programme_for(pid),
                }
                for pid, p in self.players.items()
            },
            "needs": {
                key: {
                    "city": need.importing_city,
                    "category": need.category,
                    "request_source": need.order.get("request_source"),
                    "opened_round": need.opened_round,
                    "closed_round": need.closed_round,
                    "resolved_round": need.resolved_round,
                    "rotation": need.rotation,
                    "status": need.status,
                    "resolution_mode": (need.resolution or {}).get("mode"),
                }
                for key, need in self.needs.items()
            },
            "rounds": {
                index: {"ops": record.ops, "events": record.events,
                        "question_id": record.question_id,
                        "answer_count": len(record.answers),
                        "completed": record.completed,
                        "answers_clustered": record.answer_buckets is not None}
                for index, record in self.rounds.items()
            },
        }
