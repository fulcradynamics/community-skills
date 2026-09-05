"""The economy: profit rolls, per-city accumulation, and the leaderboard.

Spec #20-#22. Three rules, and the third is the one worth reading twice.

1. **#20 -- the roll.** A winning export earns one roll of the configured dice
   expression (``economy.profit_roll``, "2d6" by default), and that value is
   added to the winning city's running cumulative total. Nothing else moves a
   city's total: every credit in the game goes through :meth:`Economy.credit`.
2. **#22 -- what the paper shows.** Whether the newspaper prints the
   leaderboard is a *config* decision
   (``economy.leaderboard_visible_in_newspaper``), because the spec explicitly
   wants exposure policy iterable rather than baked into code.
3. **#21 -- what the paper never shows.** Whether a *non-winning* export's
   origin city is shown is **not** a config decision. It is off, always. See
   :data:`NON_WINNER_ORIGIN_EXPOSURE`.

Why this is a module and not four lines inside ``game._resolve``
---------------------------------------------------------------
Two reasons, both about failing in the right place.

*Config is validated when the Economy is built, not at the first roll.* A game
whose ``economy.profit_roll`` says "2dd6" should refuse to start, not resolve
two rounds and then blow up with a need already on the record and profit already
credited to somebody. Building the ``Economy`` in ``GameEngine.__init__`` turns
a mid-game crash into a startup error.

*The distinction between rules 2 and 3 above needs somewhere to live.* "This
one is a knob, that one is not, and here is why" is a rule about the code's
shape, and the only way to keep it true is to write it where the knobs are read
and let a test assert it (see ``tests/test_economy.py``).
"""

from fractions import Fraction

from . import dice, money
from .errors import ConfigError, RuleViolation

#: Spec #21: "Non-winning suggestions' origin city must never be exposed."
#:
#: Deliberately a module constant and not a config key. Spec #22 makes exposure
#: policy generally configurable, and this is the documented exception to that:
#: blind voting (#18) is only as good as its weakest reveal, and a knob that
#: turns it off is a knob that will one day be on in a live game. Any future
#: caller that wants the origin of a losing export has to edit this line and
#: fail ``tests/test_economy.NonWinnerOriginIsNotAKnobTest`` to do it.
NON_WINNER_ORIGIN_EXPOSURE = False

#: The exposure decisions the economy *does* take from config (spec #22). If
#: this list grows, it grows here and in config.json together.
CONFIGURABLE_EXPOSURE_KEYS = ("economy.leaderboard_visible_in_newspaper",)

# -- spotting a knob that must not exist -----------------------------------
#
# A list of forbidden key *names* does not work: "reveal_non_winning_origins"
# and "reveal_non_winner_origin" mean the same thing and no literal list catches
# both. So the check is compositional -- a name that pairs something the game
# keeps private with something that would let it out.

#: Verbs that would turn a privacy fact into a setting.
EXPOSURE_VERBS = (
    "reveal", "expose", "show", "publish", "disclose", "unmask", "leak",
    "enable", "disable", "allow", "permit", "toggle",
)

#: The things spec #18/#21 keep private.
ANONYMITY_NOUNS = (
    "origin", "exporter", "submitter", "non_winner", "non_winning", "nonwinner",
    "loser", "losing", "identity", "anonymity", "anonymous", "blind_voting",
    "blind_vote",
)

#: Words that need no second half to be a problem.
ALWAYS_FORBIDDEN_WORDS = (
    "unblind", "deanonymise", "deanonymize", "de_anonymise", "de_anonymize",
)


def exposure_knob_match(name):
    """Terms that make ``name`` look like a knob over exporter anonymity (#21).

    Returns a sorted list of matched terms, empty if the name is fine. A single
    noun is not enough -- ``newspaper.player_identity_style`` is a legitimate
    #28 setting -- so a name is flagged when it either says outright that it
    unblinds something, pairs a privacy noun with a verb that would expose it, or
    pairs two privacy nouns (``non_winner_origin_policy`` names no verb but is
    unmistakably about the one thing #21 forbids).
    """
    lowered = str(name).lower()
    matched = {word for word in ALWAYS_FORBIDDEN_WORDS if word in lowered}
    nouns = {word for word in ANONYMITY_NOUNS if word in lowered}
    verbs = {word for word in EXPOSURE_VERBS if word in lowered}
    if len(nouns) >= 2 or (nouns and verbs):
        matched |= nouns | verbs
    return sorted(matched)


class Economy:
    """The rules of money for one game, resolved from config.json once."""

    def __init__(self, config):
        self.expression = config.require_str("economy.profit_roll")
        # Parsed here, at construction, so "2dd6" is a startup error.
        self.dice_count, self.dice_sides = dice.parse_dice(self.expression)

        self.split_mode = config.require_str("economy.even_split_mode")
        if self.split_mode not in money.SPLIT_MODES:
            raise ConfigError(
                "economy.even_split_mode must be one of %s, got %r"
                % (list(money.SPLIT_MODES), self.split_mode)
            )

        self.decimals = config.require_int("economy.profit_display_decimals")
        if self.decimals < 0:
            raise ConfigError(
                "economy.profit_display_decimals cannot be negative, got %d" % self.decimals
            )

        # Spec #22. The only exposure knob the economy honours; #21 is not one.
        self.leaderboard_visible = config.require_bool(
            "economy.leaderboard_visible_in_newspaper"
        )

    # -- the roll (#20) ---------------------------------------------------

    @property
    def min_roll(self):
        """The smallest value the configured dice can produce (all ones)."""
        return self.dice_count

    @property
    def max_roll(self):
        return self.dice_count * self.dice_sides

    def roll(self, rng):
        """One profit roll. ``rng`` is the caller's seeded, per-need stream."""
        return dice.roll(rng, self.expression)

    def in_range(self, total):
        return self.min_roll <= total <= self.max_roll

    # -- turning a roll into awards ---------------------------------------

    def whole(self, city, roll):
        """The whole roll to one city -- a picked winner (#20) or a ramp-up (#17)."""
        return [(city, Fraction(roll.total))]

    def split(self, cities, roll):
        """The roll split evenly among ``cities`` -- the #19 fallback.

        Among *cities*, not among submissions: the caller de-duplicates first,
        because paying a city twice for two exports would make export spam
        profitable. ``economy.even_split_mode`` decides what "evenly" means
        when the roll does not divide cleanly.
        """
        if not cities:
            raise RuleViolation("an even split needs at least one city to pay (spec #19)")
        shares = money.even_split(roll.total, len(cities), self.split_mode)
        return list(zip(cities, shares))

    # -- accumulation (#20) -----------------------------------------------

    def credit(self, player, amount):
        """Add ``amount`` to a city's cumulative total. The only way it moves.

        Refuses a negative credit: the game has no losses, so a negative award
        means a caller computed a share wrongly, and a leaderboard is the last
        place that should be discovered.
        """
        amount = Fraction(amount)
        if amount < 0:
            raise RuleViolation(
                "profit is never negative; refusing to credit %s to %s (spec #20)"
                % (amount, player.city)
            )
        player.cumulative_profit += amount
        return player.cumulative_profit

    def render_awards(self, awards):
        """``[(city, Fraction)]`` -> the JSON form the newspaper reads.

        Rendered once, at resolution time, so no downstream consumer has to
        decide how to display a rational and none of them disagree.
        """
        return [
            {"city": city, "profit": money.to_json(amount, self.decimals)}
            for city, amount in awards
        ]

    # -- the leaderboard (#20, exposed per #22) ---------------------------

    def leaderboard(self, players):
        """Cumulative per-city profit, richest first.

        Ties break alphabetically by city so the ordering is deterministic
        rather than dependent on registration order, and every row in a tie
        carries ``tied: true`` -- the endgame's crowning (#31) needs to know
        that a tie happened, which a bare sequential rank hides.

        Every registered city appears, including one that never earned
        anything: "which cities scored nothing" is part of the standing.
        """
        ranked = sorted(players, key=lambda p: (-p.cumulative_profit, p.city))
        counts = {}
        for player in ranked:
            counts[player.cumulative_profit] = counts.get(player.cumulative_profit, 0) + 1
        return [
            {
                "rank": index + 1,
                "city": player.city,
                "mayor": player.mayor,
                "profit": money.to_json(player.cumulative_profit, self.decimals),
                "tied": counts[player.cumulative_profit] > 1,
            }
            for index, player in enumerate(ranked)
        ]

    # -- introspection ----------------------------------------------------

    def describe(self):
        """The economy's own settings, for the paper's masthead and for tests."""
        return {
            "profit_roll": self.expression,
            "roll_range": [self.min_roll, self.max_roll],
            "even_split_mode": self.split_mode,
            "profit_display_decimals": self.decimals,
            "leaderboard_visible_in_newspaper": self.leaderboard_visible,
            "configurable_exposure_keys": list(CONFIGURABLE_EXPOSURE_KEYS),
            "non_winner_origin_exposure": NON_WINNER_ORIGIN_EXPOSURE,
            "non_winner_origin_exposure_configurable": False,
            "spec": "#20, #21, #22",
        }
