"""Which writer produces the prose (``newspaper.prose.renderer``).

There is one writer, and it is a registry entry rather than an assumption
because the choice is a real one and the spec's Generation Rules put real
choices in ``config.json``.

``deterministic_template`` assembles each edition from the frames in
``content/newspaper.json`` and the round's actual facts. That is a deliberate
design decision rather than a limitation of the environment, and the reasoning
is worth stating because the alternative is obvious:

* **The aggregate item has to be checkable.** Spec #25 is judged on whether the
  phrasing is *true of the distribution* -- "present-looking language over an
  actually-wrong aggregate is a fail". A writer whose output is a function of
  game state can be asserted against the arithmetic in
  :mod:`engine.aggregate`; a writer that produces a fresh sentence each time can
  only be spot-checked.
* **Blind voting has to hold in the prose, not just in the data.** Spec #21
  forbids ever exposing a losing export's origin. With a template writer, the
  set of strings that can reach the page is finite and enumerable, and
  :mod:`newspaper.redact` checks all of it.
* **A game must be replayable.** ``engine.rng_seed`` exists so a disputed round
  can be re-examined. A paper that reads differently on the second rendering
  would undo that.

Spec #29 already sets this precedent on the image side, where a deterministic,
game-state-informed illustration is an explicitly permitted alternative to a
generated raster when no provider is available. The same reasoning applies to
prose, and the same escape hatch is left open: a model-backed writer registers
here under its own id, is selected by config, and must satisfy the same
redaction and licensing checks the template writer does. Nothing downstream
knows which one ran.
"""

from engine.errors import ConfigError

DETERMINISTIC_TEMPLATE = "deterministic_template"

#: Writer id -> what it is, for the record kept in every edition's provenance.
RENDERERS = {
    DETERMINISTIC_TEMPLATE: {
        "id": DETERMINISTIC_TEMPLATE,
        "implementation": "newspaper.departments + newspaper.wire",
        "source_of_wording": "content/newspaper.json",
        "deterministic": True,
        "needs_network": False,
        "note": "Selects among content-authored frames using the round's own facts as "
                "the key, so the same game renders the same paper every time.",
    },
}


def resolve_renderer(config):
    """The writer ``newspaper.prose.renderer`` names, or a config error."""
    renderer_id = config.require_str("newspaper.prose.renderer")
    try:
        return RENDERERS[renderer_id]
    except KeyError:
        raise ConfigError(
            "config.newspaper.prose.renderer is %r; this paper has %s. A renderer that "
            "is not registered is a configuration mistake rather than a reason to fall "
            "back to another one -- an edition written by a different writer than the "
            "facilitator asked for is not an edition they can vouch for."
            % (renderer_id, sorted(RENDERERS))
        )


def prose_limits(config, masthead):
    """The numeric knobs the writers read, resolved once per edition."""
    return {
        "asides": config.require_int("newspaper.prose.asides_per_edition"),
        "quotes": config.require_int("newspaper.prose.max_quoted_answers_per_item"),
        "declined": config.require_int("newspaper.prose.max_declined_exports_printed"),
        # Not a config knob: the corrections column always carries at least two
        # items because a column with one line in it looks like an oversight, and
        # the paper's evergreen items about itself cost the game nothing.
        "corrections_minimum": 2,
        "publication": masthead["publication"],
    }
