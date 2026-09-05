"""Profit arithmetic.

Spec #19's even-split fallback divides one roll among an arbitrary number of
cities, so profit cannot be a plain ``int`` and must not be a binary ``float``
(a leaderboard that reports 11.699999999999999 is a bug the newspaper would
faithfully print). Profits are :class:`fractions.Fraction` internally -- exact,
order-independent when summed -- and are rendered for display only at the edge.

The split mode itself is config-driven (``economy.even_split_mode``) because
"split evenly" has two defensible readings when the roll does not divide
cleanly, and picking one silently would be a hidden design decision.
"""

from fractions import Fraction

from .errors import ConfigError

EXACT_FRACTION = "exact_fraction"
FLOOR_REMAINDER_TO_NONE = "floor_discard_remainder"
SPLIT_MODES = (EXACT_FRACTION, FLOOR_REMAINDER_TO_NONE)


def even_split(total, shares, mode=EXACT_FRACTION):
    """Split ``total`` into ``shares`` equal parts (spec #19).

    ``exact_fraction``       -- each city gets total/n exactly; the parts sum to
                               the whole, which is what "split evenly" says.
    ``floor_discard_remainder`` -- each city gets floor(total/n); the remainder
                               is not awarded to anyone. Kept as an option for a
                               facilitator who wants integer-only ledgers.
    """
    if shares < 1:
        raise ValueError("cannot split a profit among %d cities" % shares)
    if mode == EXACT_FRACTION:
        return [Fraction(total, shares)] * shares
    if mode == FLOOR_REMAINDER_TO_NONE:
        return [Fraction(int(Fraction(total, shares)))] * shares
    raise ConfigError(
        "economy.even_split_mode must be one of %s, got %r" % (list(SPLIT_MODES), mode)
    )


def to_display(amount, decimals=2):
    """Render a profit for humans without letting float error into state."""
    quantized = round(float(amount), decimals)
    if quantized == int(quantized):
        return str(int(quantized))
    return ("%%.%df" % decimals) % quantized


def to_json(amount, decimals=2):
    """Serialise a profit both exactly and approximately.

    ``exact`` is the authoritative value; ``approx``/``display`` exist so a
    newspaper template or a JSON consumer never has to parse a rational.
    """
    frac = Fraction(amount)
    return {
        "exact": "%d/%d" % (frac.numerator, frac.denominator),
        "approx": round(float(frac), decimals),
        "display": to_display(frac, decimals),
    }
