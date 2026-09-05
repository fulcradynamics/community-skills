"""The game's single round timer (spec #9, #10).

Spec #9: "Exactly one round timer for the whole game -- no independent
per-phase timers."

That requirement is met structurally rather than by convention. All timing in
the game derives from exactly two values held in one :class:`RoundTimer`:

* ``epoch``  -- when round 1 began
* ``window`` -- how long every round lasts (``rounds.round_window_hours``)

Nothing else in the engine stores a deadline. An import need's export window,
an importer's picking window and the game's own end are all *computed* from a
round index and this one timer, so there is no second timer that could drift,
be paused independently, or be configured separately. ``engine.game.GameEngine``
exposes :meth:`GameEngine.timers` returning exactly one timer, and the lockstep
tests assert that count.
"""

from datetime import datetime, timedelta, timezone


def utc(year, month, day, hour=0, minute=0, second=0):
    """Convenience constructor for aware UTC datetimes (used by tests)."""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def ensure_aware(moment):
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


class RoundTimer:
    """The one timer. Rounds are 1-based and contiguous."""

    __slots__ = ("epoch", "window")

    def __init__(self, epoch, window):
        if not isinstance(window, timedelta) or window <= timedelta(0):
            raise ValueError("round window must be a positive timedelta, got %r" % (window,))
        self.epoch = ensure_aware(epoch)
        self.window = window

    def __repr__(self):
        return "RoundTimer(epoch=%s, window=%s)" % (self.epoch.isoformat(), self.window)

    def round_start(self, index):
        if index < 1:
            raise ValueError("round index is 1-based, got %r" % (index,))
        return self.epoch + (index - 1) * self.window

    def round_end(self, index):
        """Exclusive end of a round -- i.e. the start of the next one."""
        return self.round_start(index) + self.window

    def round_index_at(self, moment):
        """Which round contains ``moment``. Anything before the epoch is round 1."""
        moment = ensure_aware(moment)
        if moment < self.epoch:
            return 1
        elapsed = (moment - self.epoch).total_seconds()
        return int(elapsed // self.window.total_seconds()) + 1

    def describe(self):
        return {
            "epoch": self.epoch.isoformat(),
            "window_hours": self.window.total_seconds() / 3600.0,
        }


class ManualClock:
    """A hand-advanced clock, so round transitions are testable without waiting."""

    def __init__(self, now):
        self._now = ensure_aware(now)

    def now(self):
        return self._now

    def advance(self, delta):
        if delta < timedelta(0):
            raise ValueError("the round timer does not run backwards")
        self._now = self._now + delta
        return self._now

    def set(self, moment):
        moment = ensure_aware(moment)
        if moment < self._now:
            raise ValueError("the round timer does not run backwards")
        self._now = moment
        return self._now


class SystemClock:
    def now(self):
        return datetime.now(timezone.utc)
