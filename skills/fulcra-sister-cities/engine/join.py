"""Seating a mayor on a city, and resolving a duplicate pick (spec #2).

Spec #2 is three sentences that pull in different directions:

* each player picks a home city, and **the agent suggests possibilities**;
* **players may pick freely** -- in the gazetteer or out of it;
* city names are **unique per game**, and a duplicate pick is **reassigned to a
  different, geographically close city**, never silently allowed to collide.

:meth:`GameEngine.register_player` implements only the refusal: it raises
:class:`~engine.errors.DuplicateCity` carrying the candidates, and stops. This
module is what catches that and does something about it, because *resolving* a
collision is a different kind of act from *detecting* one -- it consults
geography, it can fail, and when it succeeds it owes the player an explanation.

The procedure is not invented here. It is written down in
``content/gazetteer.json`` under ``resolution_rules``, next to the data it
walks, and this module executes it step for step:

1. the player who claimed the city **first** keeps it; the later pick moves;
2. walk the claimed city's ``nearby`` list in order, take the first entry no
   other mayor holds;
3. if all of those are taken, take the nearest unclaimed gazetteer city in the
   same region, within ``config.cities.max_reassignment_search_radius_km``;
4. if that fails too, ask for a free re-pick rather than assigning something
   absurd -- :class:`CityRepickRequired`;
5. either way, **tell the player what happened**. Every outcome here carries an
   ``announcement``; none of them is silent.

Where the engine stops
----------------------
An off-gazetteer pick that collides is step 4, not step 2: this file has no
coordinates for a city it has never heard of, and the gazetteer's own
``off_gazetteer`` rule hands that case to *the agent's* geographic knowledge,
not to the engine's. Inventing a neighbour for a city we do not have would be
the same error as clustering freeform answers automatically (see
:mod:`engine.aggregate`) -- a judgement dressed up as arithmetic. So the engine
refuses, says why, and returns the claimed city's own name so the agent has
something to reason from.
"""

import math

from .content import normalize_city
from .errors import ConfigError, ContentError, DuplicateCity, RuleViolation

#: Mean Earth radius. Only ever used to rank candidates against each other and
#: against a configured radius, which is all the gazetteer's one-decimal-degree
#: coordinates can support ("they exist to break ties", says the file).
EARTH_RADIUS_KM = 6371.0

#: How a collision may be resolved. A mode this table does not know is a
#: :class:`ConfigError` rather than a silent fall-back to the only one we have --
#: the same rule :mod:`newspaper.imagery` applies to image providers and
#: :mod:`hosting.build` to publishers, for the same reason: a typo must not
#: present as a deliberate choice.
RESOLUTION_MODES = ("nearest_available_from_gazetteer",)

VIA_NEARBY_LIST = "nearby_list"
VIA_NEAREST_IN_REGION = "nearest_unclaimed_in_region"


def haversine_km(lat_a, lon_a, lat_b, lon_b):
    """Great-circle distance in kilometres."""
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    d_phi = phi_b - phi_a
    d_lambda = math.radians(lon_b - lon_a)
    h = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


class CityRepickRequired(RuleViolation):
    """A duplicate pick that the gazetteer cannot resolve on its own (spec #2).

    Raised rather than assigning something absurd, which is the gazetteer's own
    instruction. Carries what was tried, so the agent asking the player to pick
    again can say more than "that one's taken".
    """

    def __init__(self, requested, held_by, tried, suggestions, reason):
        super().__init__(
            "%s is already taken and no close alternative is available: %s"
            % (requested, reason)
        )
        self.requested = requested
        self.held_by = held_by
        self.tried = list(tried)
        self.suggestions = list(suggestions)
        self.reason = reason


class Reassignment:
    """Where a duplicate pick ended up, and how it got there.

    ``announcement`` is the sentence the facilitator's agent says out loud. It
    exists on the object rather than being composed by each caller because the
    gazetteer's rule -- "always tell the player what happened and why;
    reassignment is announced, never silent" -- is a property of the
    reassignment, not of whoever happens to be printing it.
    """

    __slots__ = ("requested", "city", "held_by", "via", "distance_km", "tried", "reason")

    def __init__(self, requested, city, held_by, via, distance_km, tried, reason):
        self.requested = requested
        self.city = city
        self.held_by = held_by
        self.via = via
        self.distance_km = distance_km
        self.tried = list(tried)
        self.reason = reason

    @property
    def announcement(self):
        return (
            "%s was already claimed, so you are the Mayor of %s instead -- %s. "
            "Say the word if you would rather pick somewhere else entirely."
            % (self.requested, self.city, self.reason)
        )

    def to_dict(self):
        return {
            "requested": self.requested,
            "city": self.city,
            "held_by": self.held_by,
            "via": self.via,
            "distance_km": self.distance_km,
            "tried": list(self.tried),
            "reason": self.reason,
            "announcement": self.announcement,
            "spec": "#2",
        }


class CityRegistrar:
    """The join-time city rules: what to suggest, and what to do about a clash.

    Holds no game state. It is handed the set of cities already claimed, so the
    one authoritative claim list stays the engine's ``_city_keys`` and this class
    cannot develop a second, drifting copy of it.
    """

    def __init__(self, config, content):
        self.config = config
        self.content = content
        # Read at construction, like the dice expression and the phrasing
        # ladder: an unknown resolution mode must refuse to start a game, not
        # surface as an exception in the middle of somebody's join.
        self.mode = self._resolve_mode()

    def _resolve_mode(self):
        mode = self.config.require_str("cities.duplicate_pick_resolution")
        if mode not in RESOLUTION_MODES:
            raise ConfigError(
                "config.cities.duplicate_pick_resolution is %r; this engine knows %s"
                % (mode, list(RESOLUTION_MODES))
            )
        return mode

    # -- suggestions ------------------------------------------------------

    def suggestions(self, claimed=(), rng=None, limit=None):
        """Cities to offer a joining player (gazetteer ``resolution_rules``).

        ``config.cities.suggestions_offered_on_join`` of them, drawn from
        entries flagged ``suggest_on_join``, spread across regions rather than
        taken in file order -- otherwise the first six suggestions this game
        ever makes are six American cities, which is a menu, not a prompt.
        """
        limit = (
            self.config.require_int("cities.suggestions_offered_on_join")
            if limit is None else limit
        )
        taken = self._claimed_keys(claimed)
        by_region = {}
        for entry in self.content.gazetteer.get("cities", []):
            if not entry.get("suggest_on_join"):
                continue
            if normalize_city(entry["name"]) in taken:
                continue
            by_region.setdefault(entry.get("region"), []).append(entry["name"])

        order = [
            region["id"]
            for region in self.content.gazetteer.get("regions", [])
            if region["id"] in by_region
        ]
        order += sorted(set(by_region) - set(order), key=str)
        if rng is not None:
            rng.shuffle(order)
            for names in by_region.values():
                rng.shuffle(names)

        # One pass per region before a second from any region, so a short list
        # is spread and a long one still exhausts the pool.
        out = []
        while len(out) < limit and any(by_region[region] for region in order):
            for region in order:
                if len(out) >= limit:
                    break
                if by_region[region]:
                    out.append(by_region[region].pop(0))
        return out

    def suggestion_note(self):
        """The sentence that has to travel with any suggestion list (spec #2)."""
        return (
            "These are suggestions, not a menu -- any city on Earth is allowed, "
            "in this list or not."
        )

    # -- collisions -------------------------------------------------------

    def resolve_duplicate(self, requested, claimed, held_by=None):
        """Find the geographically closest unclaimed city for a duplicate pick.

        ``claimed`` is every city the game currently holds, in any spelling.
        Raises :class:`CityRepickRequired` when the gazetteer cannot answer,
        which is a real outcome and not an error condition to be papered over.
        """
        taken = self._claimed_keys(claimed)
        entry = self.content.gazetteer_entry(requested)
        tried = []
        if entry is None:
            raise CityRepickRequired(
                requested, held_by, tried,
                self.suggestions(claimed),
                "%s is not in the gazetteer, so this engine has no neighbours for it "
                "to offer. Whoever is running the join proposes nearby cities from "
                "their own geography and the pick is recorded as normal "
                "(gazetteer resolution_rules.off_gazetteer)" % requested,
            )

        for name in entry.get("nearby", []):
            tried.append(name)
            if normalize_city(name) in taken:
                continue
            return Reassignment(
                requested, name, held_by, VIA_NEARBY_LIST,
                self._distance(entry, self.content.gazetteer_entry(name)),
                tried,
                "it is the closest neighbour of %s still unclaimed" % requested,
            )

        nearest = self._nearest_in_region(entry, taken)
        if nearest is not None:
            candidate, distance = nearest
            tried.append(candidate["name"])
            return Reassignment(
                requested, candidate["name"], held_by, VIA_NEAREST_IN_REGION, distance,
                tried,
                "every neighbour %s lists was taken too, so this is the nearest "
                "unclaimed city in %s, about %d km away"
                % (requested, self._region_label(entry.get("region")), round(distance)),
            )

        raise CityRepickRequired(
            requested, held_by, tried, self.suggestions(claimed),
            "every city %s lists as nearby is claimed, and no unclaimed city in %s "
            "is within config.cities.max_reassignment_search_radius_km (%s km). "
            "Offering a free re-pick beats assigning something absurd"
            % (
                requested,
                self._region_label(entry.get("region")),
                self.config.require_number("cities.max_reassignment_search_radius_km"),
            ),
        )

    def check_off_gazetteer(self, city):
        """Refuse an unlisted pick when config says this game does not take them.

        Default is to take them: spec #2 says players may pick freely, and the
        gazetteer is explicit that it seeds the runtime city list rather than
        being it. The knob exists for a facilitator who wants a game confined to
        cities the paper has data for.
        """
        if self.config.require_bool("cities.allow_off_gazetteer_picks"):
            return True
        if self.content.gazetteer_entry(city) is None:
            raise ContentError(
                "%r is not in the gazetteer and "
                "config.cities.allow_off_gazetteer_picks is false" % city
            )
        return True

    # -- internals --------------------------------------------------------

    @staticmethod
    def _claimed_keys(claimed):
        return {normalize_city(name) if isinstance(name, str) else name for name in claimed}

    def _region_label(self, region_id):
        for region in self.content.gazetteer.get("regions", []):
            if region["id"] == region_id:
                return region["label"]
        return region_id or "the region"

    @staticmethod
    def _distance(entry, other):
        """Kilometres between two gazetteer entries, or ``None``.

        ``None`` is the common case for a ``nearby`` entry: most of them have no
        entry of their own in the file, by design. A missing distance is
        reported as missing rather than guessed at -- the neighbour list is
        curated, and its ordering is the geography here.
        """
        if not entry or not other:
            return None
        if any(e.get("lat") is None or e.get("lon") is None for e in (entry, other)):
            return None
        return round(
            haversine_km(entry["lat"], entry["lon"], other["lat"], other["lon"]), 1
        )

    def _nearest_in_region(self, entry, taken):
        radius = self.config.require_number("cities.max_reassignment_search_radius_km")
        best = None
        for candidate in self.content.gazetteer.get("cities", []):
            if candidate.get("region") != entry.get("region"):
                continue
            if normalize_city(candidate["name"]) in taken:
                continue
            if normalize_city(candidate["name"]) == normalize_city(entry["name"]):
                continue
            distance = self._distance(entry, candidate)
            if distance is None or distance > radius:
                continue
            if best is None or distance < best[1]:
                best = (candidate, distance)
        return best


def join_player(engine, player_id, handle, city, is_facilitator=False, rng=None):
    """Seat a player, reassigning their city if somebody already holds it.

    The whole of spec #2 in one call, and the door a facilitator's agent should
    use instead of :meth:`GameEngine.register_player` -- which deliberately
    refuses a collision and leaves it at that.

    Returns a record of what happened: the seated player, whether they were
    moved, and if so the announcement owed to them.
    """
    registrar = engine.registrar
    registrar.check_off_gazetteer(city)
    try:
        player = engine.register_player(player_id, handle, city, is_facilitator)
    except DuplicateCity as clash:
        reassignment = registrar.resolve_duplicate(
            city, engine.claimed_cities(), held_by=clash.held_by
        )
        registrar.check_off_gazetteer(reassignment.city)
        player = engine.register_player(
            player_id, handle, reassignment.city, is_facilitator
        )
        return {
            "player_id": player_id,
            "city": player.city,
            "requested": city,
            "reassigned": True,
            "reassignment": reassignment.to_dict(),
            "announcement": reassignment.announcement,
            "spec": "#2",
        }
    return {
        "player_id": player_id,
        "city": player.city,
        "requested": city,
        "reassigned": False,
        "reassignment": None,
        "announcement": "You are the Mayor of %s." % player.city,
        "spec": "#2",
    }
