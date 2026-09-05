"""Sister Cities -- the round-flow engine.

Implements the join rules and duplicate-city reassignment (spec #2, #3, see
:mod:`engine.join`), the round timer and lockstep (spec #9-#12), the city order
queue and its two rotations (#4, #5, #12), the importing mayor's own choice of
what their city imports and the trade policy that choice must satisfy (#13,
#13a, see :mod:`engine.trade`), the import/export/winner cycle with
all three fallback paths (#15-#19), the import repetition rule (#14),
blind-voting data handling (#18, #21), the economy -- profit rolls, the
cumulative per-city leaderboard, and the exposure policy around both (#20-#22,
see :mod:`engine.economy`) -- and the facilitator question mechanic: the
two-slot check-in, the framing rules, and the arithmetic behind the newspaper's
aggregate phrasing (#23-#25, see :mod:`engine.aggregate`).

Not here, by design: the paper's prose, images and aggregate wording, which are
:mod:`newspaper`; where it is published, which is :mod:`hosting`; what happens
when a round finishes, which is :mod:`facilitator`; and the endgame articles.

Typical use::

    from engine import GameEngine
    game = GameEngine()                       # reads config.json + content/
    game.city_suggestions()                   # what to offer a joining mayor
    game.join("p1", "@ada", "Reykjavík", is_facilitator=True)
    game.join("p2", "@bo", "Valparaíso")      # -> reassigned if it collides
    game.join("p3", "@cy", "Hobart")
    game.import_choice_offer("p1")            # what Reykjavík may order
    game.choose_import("p1", need_id="need-candy-01")
    game.start()                              # ... and that is what round 1 opens
    game.checkin("p2")                        # -> two slots
    game.submit_export("p2", "Salted liquorice, forty cases, wrappers and all.")
    game.tick(later)                          # the one timer moves the game
"""

from .aggregate import Ladder
from .config import Config
from .content import Content
from .economy import Economy
from .errors import GameError
from .game import LOCKSTEP_OPS, GameEngine
from .join import CityRegistrar, CityRepickRequired

__all__ = [
    "GameEngine", "Config", "Content", "Economy", "Ladder", "GameError", "LOCKSTEP_OPS",
    "CityRegistrar", "CityRepickRequired",
]
