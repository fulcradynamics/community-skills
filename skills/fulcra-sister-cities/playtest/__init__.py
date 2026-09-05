"""One whole game of Sister Cities, played by agents, replayed by anyone.

This package is the integration pass (M8). It contains no game rules: the rules
are :mod:`engine`, the paper is :mod:`newspaper`, the address is
:mod:`hosting`, and everything here does is put all three in a room together
and check that they still agree once they are.

Three pieces:

* :mod:`playtest.table` -- the seating plan. Who plays, which city they asked
  for, when they arrive, and *when they are actually at their desk*. That last
  column is what "varying engagement levels" means here, and it is the only
  thing about a simulated mayor this package decides.
* :mod:`playtest.transcript` -- the recorded game. Every export, every answer,
  every winner pick, written by the mayors themselves (see
  ``docs/m8-integration.md`` for how), stored so the same game replays move for
  move forever.
* :mod:`playtest.conformance` -- spec #1 to #35 as executable checks over the
  finished game, its editions and its published site, all at once.

Run it::

    python3 -m playtest.run            # replay, publish, build, report
    python3 -m playtest.run --check    # report only; write nothing

and see ``tests/test_full_spec_integration.py`` for the same thing as a test.
"""

from .replay import replay
from .transcript import Transcript, load_transcript

__all__ = ["Transcript", "load_transcript", "replay"]
