"""One image per edition, and honesty about how it was made (spec #29).

Spec #29 and the user decision of 2026-08-24 set the policy: a fun, colourful
raster image from an available image-generation provider is *preferred*, and a
deterministic, game-state-informed SVG or procedural illustration is an
*explicitly permitted* fallback when no such provider is available -- one that
must still be materially informed by the edition and meet the tone bar. The same
requirement adds: record the actual modality and provider in the deliverable's
config or output.

So this module does three things and refuses to fudge any of them:

1. **Resolves the modality in the order config asks for**
   (``newspaper.image.modality_preference``). The preference is config rather
   than code because it is a policy, and because a facilitator who wants every
   edition to look the same should be able to pin it to SVG without editing
   Python.
2. **Refuses to silently downgrade.** Naming a provider in
   ``newspaper.image.raster_providers`` that is not registered here is a config
   error. A typo in a provider name must not present as "we tried raster and it
   wasn't there".
3. **Records what actually happened**, per provider considered, in the
   edition's own ``image.provenance``. This deployment has no image-generation
   provider, so every edition it renders says so in as many words rather than
   quietly shipping an SVG that looks like a choice.

Adding a raster provider is a matter of writing an adapter with ``available()``
and ``generate()``, registering it with :func:`register_raster_provider`, and
naming it in config. Nothing else changes: the SVG path stays as the last
element of the preference list, which is what makes it a fallback rather than a
default.
"""

from engine.errors import ConfigError

from . import svg

#: Modality ids ``newspaper.image.modality_preference`` may contain.
RASTER = "raster"
SVG_PROCEDURAL = "svg_procedural"
KNOWN_MODALITIES = (RASTER, SVG_PROCEDURAL)

#: The built-in illustrator. Always available, by construction -- it needs no
#: network, no key and no service, only the round it is drawing.
BUILTIN_SVG_PROVIDER = "builtin_svg"


class RasterProvider:
    """The interface a raster image-generation adapter must satisfy.

    Deliberately not subclassed here. This deployment has no provider, and a
    stub that reported itself available and then failed to generate would be
    worse than an honest absence: the edition would fail to publish at the last
    step instead of falling back cleanly at the first.
    """

    provider_id = None

    def available(self):  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self):  # pragma: no cover - interface
        return {"provider": self.provider_id, "modality": RASTER}

    def generate(self, scene, palette, size):  # pragma: no cover - interface
        """Return ``{"content": bytes, "extension": "png", "mime": ...}``."""
        raise NotImplementedError


#: Registered raster adapters, by id. Empty in this deployment; see the module
#: docstring. Tests register a stub here to prove the raster path is genuinely
#: preferred over the fallback rather than merely documented as such.
RASTER_PROVIDERS = {}


def register_raster_provider(provider):
    if not getattr(provider, "provider_id", None):
        raise ConfigError("a raster provider must declare a provider_id")
    RASTER_PROVIDERS[provider.provider_id] = provider
    return provider


def unregister_raster_provider(provider_id):
    RASTER_PROVIDERS.pop(provider_id, None)


def _require_list(config, dotted):
    value = config.require(dotted)
    if not isinstance(value, list):
        raise ConfigError("config %s must be a list, got %r" % (dotted, value))
    return value


def resolve_modality(config):
    """Which modality this edition will actually use, and every step of why.

    Returns ``{"modality", "provider", "considered", "preference", "spec"}``.
    ``considered`` is the audit trail: one entry per (modality, provider) pair
    looked at, with whether it was available and why not.
    """
    preference = _require_list(config, "newspaper.image.modality_preference")
    declared = _require_list(config, "newspaper.image.raster_providers")
    if not preference:
        raise ConfigError(
            "config.newspaper.image.modality_preference is empty; spec #29 requires an "
            "image in every edition, so there must be at least one modality to try"
        )

    considered = []
    for modality in preference:
        if modality not in KNOWN_MODALITIES:
            raise ConfigError(
                "config.newspaper.image.modality_preference names %r; this paper knows "
                "%s (spec #29)" % (modality, list(KNOWN_MODALITIES))
            )
        if modality == RASTER:
            if not declared:
                considered.append(
                    {
                        "modality": RASTER,
                        "provider": None,
                        "available": False,
                        "reason": "config.newspaper.image.raster_providers is empty: no "
                                  "image-generation provider is configured for this "
                                  "deployment",
                    }
                )
                continue
            for provider_id in declared:
                provider = RASTER_PROVIDERS.get(provider_id)
                if provider is None:
                    raise ConfigError(
                        "config.newspaper.image.raster_providers names %r, which is not "
                        "registered in newspaper.imagery (registered: %s). A provider "
                        "this paper has never heard of is a configuration mistake, not a "
                        "reason to fall back to SVG."
                        % (provider_id, sorted(RASTER_PROVIDERS))
                    )
                ok = bool(provider.available())
                considered.append(
                    {
                        "modality": RASTER,
                        "provider": provider_id,
                        "available": ok,
                        "reason": None if ok else "provider reports itself unavailable",
                    }
                )
                if ok:
                    return _chosen(RASTER, provider_id, preference, considered)
        else:
            considered.append(
                {
                    "modality": SVG_PROCEDURAL,
                    "provider": BUILTIN_SVG_PROVIDER,
                    "available": True,
                    "reason": None,
                }
            )
            return _chosen(SVG_PROCEDURAL, BUILTIN_SVG_PROVIDER, preference, considered)

    raise ConfigError(
        "no modality in config.newspaper.image.modality_preference (%s) was available, "
        "and spec #29 requires an image in every edition. The SVG fallback is always "
        "available; put %r last in the preference list rather than removing it."
        % (preference, SVG_PROCEDURAL)
    )


def _chosen(modality, provider, preference, considered):
    return {
        "modality": modality,
        "provider": provider,
        "preference": list(preference),
        "considered": considered,
        "policy": "raster preferred where a provider is available; a deterministic, "
                  "game-state-informed SVG is an explicitly permitted fallback",
        "spec": "#29",
    }


def make_image(config, copy, tone, scene, illustrator=None, labels=None, size=None):
    """One image, plus the provenance of how it came to be.

    ``scene`` is the picture's own facts (see
    :func:`newspaper.edition.build_scene`): the crates are that round's offers,
    the dice are that round's roll, the skyline is the live leaderboard. Whatever
    draws it, it is drawn from the edition -- which is the substantive half of
    spec #29's fallback clause, the deterministic half being free.

    ``illustrator``, ``labels`` and ``size`` are how the endgame's two other
    pictures (the finale and one portrait per city, spec #32) go through *this*
    function rather than around it. Spec #32 says to use #29's modality policy,
    so there is exactly one resolver and one provenance record, and a raster
    provider that appears tomorrow gets asked for all three kinds of picture
    without anything else changing. ``scene["kind"]`` is what tells such a
    provider which it is being asked for.
    """
    resolution = resolve_modality(config)
    if size is None:
        size = (
            config.require_int("newspaper.image.width"),
            config.require_int("newspaper.image.height"),
        )
    palette = copy.palette(scene.get("category"), colorful=tone.colorful)

    if resolution["modality"] == RASTER:
        provider = RASTER_PROVIDERS[resolution["provider"]]
        produced = provider.generate(scene, palette, size)
        content = produced["content"]
        extension = produced.get("extension", "png")
        mime = produced.get("mime", "image/png")
    else:
        draw = illustrator or svg.render
        content = draw(
            scene, palette, size,
            copy.imagery()["labels"] if labels is None else labels,
        )
        extension = "svg"
        mime = "image/svg+xml"

    return {
        "kind": scene.get("kind", "edition"),
        "alt": scene["alt"],
        "cutline": scene["cutline"],
        "extension": extension,
        "mime": mime,
        "content": content,
        "palette": palette,
        "colorful": tone.colorful,
        "provenance": resolution,
    }
