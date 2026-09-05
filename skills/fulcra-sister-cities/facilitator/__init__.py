"""The facilitator's desk: what happens the moment a round finishes (spec #26).

Everything else in this repository is a thing that *can* be done to a game --
render an edition, publish an archive, build the site. This package is the thing
that is done *without being asked*, which is the difference spec #26 turns on:

    "Automatically renders and publishes exactly one redacted edition after
    every completed round (not batched), then notifies the group it is
    available. ... A manually callable renderer alone does not satisfy this
    requirement."

So the trigger is not a command. :class:`~facilitator.transaction.Facilitator`
attaches to a game's round-completed hook (:meth:`engine.GameEngine.
on_round_completed`) and runs one transaction every time a round ends, whether
that is because the facilitator's agent ticked the clock, because a mayor's
check-in advanced it, or because the game just ended::

    from engine import GameEngine
    from facilitator import Facilitator

    game = GameEngine()
    desk = Facilitator.attach(game)     # nothing else to remember
    ...
    game.tick()                         # -> round 3 ends, round 3's paper is out
    print(desk.notices[-1].text)        # ... and this is what the group is told

The transaction is four steps, declared in ``config.facilitator.
completed_round_transaction`` and run in that order:

1. **render** the edition for the round that just finished
   (:class:`newspaper.edition.Paper`), which is also where it is checked: a
   redaction failure or a tone failure raises here and the round does not
   publish (spec #21, #28, #30);
2. **publish** it to ``editions/`` beside every earlier edition -- one new
   edition per completed round, never a rewrite of an old one (spec #27);
3. **build** the site at the paper's own unguessable address, so the whole
   archive is browsable there (:func:`hosting.build_site`, spec #26, #27);
4. **notify** the group that it is up, in the paper's own voice
   (``content/newspaper.json``'s ``bulletin`` block).

Why here and not in the engine
------------------------------
The engine knows when a round is over; it does not know what a newspaper is,
and it must stay that way -- an engine that imported the paper could not be
tested without one, and the layering that keeps redaction in one place
(:mod:`engine.views`) would be the first casualty. So the engine raises a hook
and this package is what the facilitator hangs on it.

The notice and the address
--------------------------
A notice contains the paper's URL, and that URL is the only credential the
paper has (:mod:`hosting.identity`). So :class:`~facilitator.transaction.Notice`
is a small object rather than a string: ``text`` is what goes to the players and
``describe()`` is what may be written into a receipt, a log or a committed
artifact. The transaction record uses the second one, everywhere.
"""

from .transaction import Facilitator, Notice, RoundTransaction, TRANSACTION_STEPS

__all__ = ["Facilitator", "Notice", "RoundTransaction", "TRANSACTION_STEPS"]
