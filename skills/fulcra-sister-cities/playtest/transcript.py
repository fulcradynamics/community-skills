"""The recorded game: what every mayor actually said, and when.

A transcript is the deliverable's only piece of *played* content. Everything
else in this repository is either rules or writing that the rules select from;
this is a record of seven agents improvising against those rules for sixteen
rounds. It is stored rather than regenerated because a game played by language
models is not reproducible and a regression artifact has to be -- with the
transcript plus ``config.json``'s seed, :func:`playtest.replay.replay` produces
the same game, the same editions and the same site, byte for byte, forever.

Shape::

    {
      "seed": 6180339,
      "start": "2026-09-10T09:00:00+00:00",
      "seats": [ ... playtest.table.Seat.to_dict() ... ],
      "exports":  {"m-vlp": {"1": "Forty-one working funicular cars ..."}},
      "answers":  {"m-vlp": {"1": "An empanada, eaten walking."}},
      "picks":    {"in-003": {"ballot_ref": "C", "by": "m-rvk", "round": 5,
                              "because": "..."}},
      "clusters": {"1": {"Valparaíso": "street food", ...}}
    }

Rounds are string keys because JSON has no integer keys; :class:`Transcript`
normalises that at the edge so nothing downstream has to remember it.

A pick is keyed by **need**, not by round, and records a ``ballot_ref`` --
never a city. That is not a storage convenience: a transcript is a file in a
public repository, and a pick recorded as "the Mayor of Reykjavík chose
Hobart's offer" would publish, permanently, which city sent an offer that lost
in some *other* round. Refs are per-need and shuffled at close (spec #18), so a
ref names nothing outside the ballot it belongs to.
"""

import json
import os

from engine.config import repo_root

#: Where the recorded game lives, relative to the repository root.
TRANSCRIPT_PATH = "playtest/transcript.json"

SCHEMA_VERSION = 1


class Decisions:
    """What a mayor does when the game asks them something.

    Two implementations: :class:`Transcript`, which looks the answer up in the
    recorded game, and :class:`Stand-ins <StandIns>`, which makes one up. The
    replay talks only to this interface, so the pass that discovers *what the
    mayors will be asked* runs through exactly the same code as the pass that
    plays their real answers -- which is what lets the second pass assert that
    the two agree round for round.
    """

    def import_choice_for(self, player_id, offer):
        """Which import this city orders next (spec #13).

        Returns a seeded need id, a ``{"request": {...}}`` mapping for a
        freeform order, or ``None`` to leave the turn unfiled -- which is a
        legitimate thing for a mayor to do and costs them the turn.
        """
        raise NotImplementedError

    def export_for(self, player_id, round_index, need):
        raise NotImplementedError

    def answer_for(self, player_id, round_index, question_id):
        raise NotImplementedError

    def pick_for(self, player_id, need_key, ballot):
        raise NotImplementedError

    def clustering_for(self, round_index, answers_by_city):
        raise NotImplementedError


class StandIns(Decisions):
    """A mayor-shaped placeholder who always shows up and says something bland.

    Used for one job only: running the game forward to find out what each
    round asks of each city, so the real mayors' agents can be briefed on the
    notices they will actually face. The text is deliberately contentless and
    deliberately uniform in length -- it must not read as game content, and it
    must not accidentally become a *good* export that a placeholder pick would
    then reward.

    Nothing structural depends on it. Which need each city draws, when each
    rotation closes and how ballots shuffle are functions of the seed, the
    roster and who showed up -- never of what anybody wrote.
    """

    def __init__(self, import_choices=None):
        self.counter = 0
        #: The orders each city files, if the caller has some. The stand-in pass
        #: exists to discover *what each round asks of each city*, and since
        #: spec #13 that depends on what the mayors ordered -- so the pass that
        #: has to agree with the recorded game is given the recorded game's
        #: orders, and only the writing is stood in for. With none supplied a
        #: stand-in takes the first suggestion on the slate, which is a choice
        #: like any other.
        self.import_choices = {
            player_id: list(orders) for player_id, orders in (import_choices or {}).items()
        }

    def import_choice_for(self, player_id, offer):
        filed = self.import_choices.get(player_id)
        if filed:
            return filed.pop(0)
        if filed is not None:
            # This mayor's orders are all filed; anything further is not theirs.
            return None
        return offer["suggestions"][0]["need_id"]

    def export_for(self, player_id, round_index, need):
        self.counter += 1
        return "[[stand-in offer %03d]]" % self.counter

    def answer_for(self, player_id, round_index, question_id):
        return "[[stand-in answer to %s]]" % question_id

    def pick_for(self, player_id, need_key, ballot):
        # First ref on the ballot. A placeholder has no taste and should not
        # pretend to one; spec #18's subjective choice is the real mayors' job.
        return {"ballot_ref": ballot[0]["ballot_ref"]} if ballot else None

    def clustering_for(self, round_index, answers_by_city):
        # Grouping freeform answers is a judgement (see engine.aggregate) and a
        # stand-in has none. Returning nothing leaves the round unclustered,
        # which the aggregate already knows how to report honestly.
        return None


class Transcript(Decisions):
    """The recorded game, as played."""

    def __init__(self, data):
        self.data = data
        self.seed = data["seed"]
        self.start = data["start"]
        self.seats = data.get("seats", [])
        self._exports = _by_round(data.get("exports", {}))
        self._answers = _by_round(data.get("answers", {}))
        self._picks = dict(data.get("picks", {}))
        self._clusters = {int(k): v for k, v in (data.get("clusters", {}) or {}).items()}
        self._imports = {
            player_id: list(orders)
            for player_id, orders in (data.get("import_orders", {}) or {}).items()
            if not player_id.startswith("_")
        }
        #: Every lookup that came back empty, so a replay can report "this mayor
        #: was at their desk and chose not to act" separately from "the
        #: transcript is missing a round".
        self.misses = []

    # -- Decisions ---------------------------------------------------------

    def import_choice_for(self, player_id, offer):
        """The notice this city opened next, from the record (spec #13).

        See this file's ``import_orders._note``: the recorded game was played
        before mayors chose their own imports, so these are the notices the
        archive says each city actually opened, replayed through the choice API
        so that a recording made under the old rule still plays under the new
        one. They are the archive's record, not decisions its agents made.
        """
        filed = self._imports.get(player_id)
        if not filed:
            self.misses.append({"kind": "import_order", "player": player_id})
            return None
        return filed.pop(0)

    def import_orders(self):
        """The recorded orders, unconsumed -- for the stand-in reference pass."""
        return {player_id: list(orders) for player_id, orders in
                (self.data.get("import_orders", {}) or {}).items()
                if not player_id.startswith("_")}

    def export_for(self, player_id, round_index, need):
        return self._get(self._exports, player_id, round_index, "export")

    def answer_for(self, player_id, round_index, question_id):
        return self._get(self._answers, player_id, round_index, "answer")

    def pick_for(self, player_id, need_key, ballot):
        pick = self._picks.get(need_key)
        if pick is None:
            self.misses.append({"kind": "pick", "player": player_id, "need": need_key})
            return None
        refs = {entry["ballot_ref"] for entry in ballot}
        if pick["ballot_ref"] not in refs:
            raise ValueError(
                "transcript picks %r for %s but that ballot offers %s -- the recorded "
                "game and the replayed game have diverged"
                % (pick["ballot_ref"], need_key, sorted(refs))
            )
        return pick

    def clustering_for(self, round_index, answers_by_city):
        clustering = self._clusters.get(round_index)
        if not clustering:
            return None
        # Only the cities that actually answered: the engine refuses a
        # clustering that invents a respondent, and correctly so.
        return {city: clustering[city] for city in answers_by_city if city in clustering}

    def _get(self, table, player_id, round_index, kind):
        value = table.get(player_id, {}).get(round_index)
        if value is None:
            self.misses.append({"kind": kind, "player": player_id, "round": round_index})
        return value

    # -- io ----------------------------------------------------------------

    def to_json(self):
        return json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def build(cls, seed, start, seats, exports, answers, picks, clusters, notes=None):
        return cls({
            "schema_version": SCHEMA_VERSION,
            "game": "Sister Cities",
            "publication": "The Daily Manifest",
            "spec": "#34 (each mayor is a separate agent), #16/#17/#19 (the "
                    "fallbacks this table's engagement levels produce)",
            "notes": notes or {},
            "seed": seed,
            "start": start,
            "seats": seats,
            "exports": exports,
            "answers": answers,
            "picks": picks,
            "clusters": clusters,
        })


def _by_round(table):
    return {
        player_id: {int(round_key): value for round_key, value in rounds.items()}
        for player_id, rounds in (table or {}).items()
    }


def transcript_path(root=None):
    return os.path.join(root or repo_root(), TRANSCRIPT_PATH)


def load_transcript(path=None, root=None):
    with open(path or transcript_path(root), "r", encoding="utf-8") as fh:
        return Transcript(json.load(fh))
