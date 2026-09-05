"""The Daily Manifest -- Sister Cities' newspaper (spec #25-#30).

This package turns the engine's facts into an edition. It is deliberately a
separate package from :mod:`engine`, and it only ever reads the engine through
:mod:`engine.views`, because that is where the redaction rules live: a paper
that reached into game state directly would be a second place those rules have
to be remembered.

    from engine import GameEngine
    from newspaper import build_edition, to_markdown

    edition = build_edition(game, round_index=3)
    print(to_markdown(edition))

What M5 covers
--------------
* the standing departments (:mod:`newspaper.departments`), written from
  ``content/newspaper.json``'s frames and the round's actual facts
* the mayoral question item (:mod:`newspaper.wire`), which may use no wording
  the aggregate in :mod:`engine.aggregate` has not licensed for that
  distribution (spec #25)
* identity redaction -- city and office only, never a handle, and never a
  losing export's origin (:mod:`newspaper.redact`, spec #21, #28)
* the mechanical half of the tone bar (:mod:`newspaper.tone`, spec #30)
* one image per edition, raster if a provider is available and a deterministic
  game-state-informed SVG otherwise, with the modality actually used recorded in
  the edition (:mod:`newspaper.imagery`, :mod:`newspaper.svg`, spec #29)

What M7 adds
------------
* the last edition (:mod:`newspaper.endgame`): the crown, the twist article, and
  a description and portrait of every city built from that city's own history,
  with unchosen offers treated as excess (spec #31, #32)
* the two illustrations that edition needs (:mod:`newspaper.portrait`), drawn
  through the same modality policy as every other picture (spec #29, #32)

What M9 adds
------------
* :func:`newspaper.publish.publish_round`, the per-round door: one completed
  round's edition written beside every earlier one, for the facilitator's
  completed-round transaction (spec #26, #27)
* the ``bulletin`` block in ``content/newspaper.json``
  (:meth:`newspaper.copy.NewspaperCopy.bulletin`) -- what the group is told when
  an edition lands, which is the paper's voice and so is the paper's content,
  even though it is the one piece of it that is never printed in an edition

What M11 adds
-------------
* :mod:`newspaper.voice`: which passages in an edition a *player* wrote. Their
  wording prints as typed, cited to the mayor who wrote it (or to nobody, when
  spec #21 says the sender is not the paper's to name), and the editorial
  register grades the desk's own copy rather than a mayor's (spec #30b)

What it does not cover: serving the archive at an unguessable, noindex URL
(spec #26, #27), which is the :mod:`hosting` package, and *when* any of this
happens, which is :mod:`facilitator`. This package renders and writes; it is
never the thing that decides it is time.
"""

from .edition import Paper, build_archive, build_edition, build_final_edition
from .publish import publish_game, publish_round
from .render import to_markdown

__all__ = [
    "build_edition", "build_archive", "build_final_edition", "to_markdown",
    "publish_game", "publish_round", "Paper",
]
