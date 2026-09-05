"""Profit rolls (spec #20).

The dice expression is *parsed from* ``economy.profit_roll`` in config.json
("2d6") rather than hardcoded as two six-sided dice, so a facilitator can change
the economy's shape without touching code.
"""

import re

from .errors import ConfigError

_DICE_RE = re.compile(r"^\s*(\d+)\s*[dD]\s*(\d+)\s*$")


def parse_dice(expression):
    """``"2d6"`` -> ``(2, 6)``."""
    match = _DICE_RE.match(expression or "")
    if not match:
        raise ConfigError(
            "economy.profit_roll must look like 'NdS' (e.g. '2d6'), got %r" % (expression,)
        )
    count, sides = int(match.group(1)), int(match.group(2))
    if count < 1 or sides < 1:
        raise ConfigError(
            "economy.profit_roll needs at least one die of at least one side, got %r"
            % (expression,)
        )
    # A one-sided die is degenerate but legitimate: "1d1" is how a facilitator
    # says "every win is worth exactly 1", and it is how the tests pin a roll.
    return count, sides


class ProfitRoll:
    """One resolved roll, kept as data so the newspaper can narrate it later."""

    __slots__ = ("expression", "dice", "total")

    def __init__(self, expression, dice):
        self.expression = expression
        self.dice = tuple(dice)
        self.total = sum(dice)

    def __repr__(self):
        return "ProfitRoll(%s=%s -> %d)" % (self.expression, list(self.dice), self.total)

    def to_dict(self):
        return {"expression": self.expression, "dice": list(self.dice), "total": self.total}


def roll(rng, expression):
    count, sides = parse_dice(expression)
    return ProfitRoll(expression, [rng.randint(1, sides) for _ in range(count)])
