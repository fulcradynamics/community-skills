"""The seating plan for the integration game: who plays, and when they show up.

Spec's Generation Rules ask for simulated players that are genuinely separate
agents, and M8 asks for varying engagement levels. Those are two different
things and this file only does the second one. *What* a mayor says is written
by that mayor's own agent and lives in ``playtest/transcript.json``; *whether
they were at their desk that day* is here, because it is a property of the
table, not of the player -- somebody has to be away for spec #16's silent skip
and spec #19's lapsed window to happen at all, and a simulated human who is
always available exercises neither.

The engagement column is honest about that split: it is handed to the mayor's
agent as part of its brief, so an erratic mayor writes like somebody who
half-followed the game, and the ``away`` set is what the replay actually
enforces.

The long weekend
----------------
Round 6 is empty. Every mayor is away, which is a thing that happens to a
24-hour-round async game played by adults with jobs, and it is the single most
load-bearing round in this file, because one quiet day drives three separate
fallback paths at once:

* the need that **opened** in round 6 collects nothing, so its city ramps up its
  own industry and still takes the profit (spec #17);
* the need that **closed** in round 6 gets no pick from its mayor, so every
  offer wins and the money splits evenly (spec #19);
* round 6's question gets no answers at all, so the paper has to write an
  empty postbag without inventing a distribution (spec #25).

Individual ``away`` rounds elsewhere cover spec #16's silent skip.
"""

from engine.clock import utc

#: Fixed, so the whole run replays move for move -- the import needs drawn, the
#: ballot shuffles and the profit rolls all derive from it. A real game night
#: leaves ``engine.rng_seed`` null; a regression artifact cannot.
SEED = 6180339

#: A Thursday, so a 24-hour round means the long weekend lands on a weekend.
START = utc(2026, 9, 10, 9, 0)


class Seat:
    """One mayor at the table.

    ``requested_city`` is what the player *asked for*, which is not always what
    they get: two seats here ask for Reykjavík and spec #2 says the second one
    moves. The reassignment is performed by the engine at join time and recorded
    in the transcript, so the game the agents played is the game that replays.
    """

    __slots__ = (
        "player_id", "handle", "requested_city", "is_facilitator", "joins_round",
        "engagement", "engagement_note", "persona", "away",
    )

    def __init__(self, player_id, handle, requested_city, engagement, engagement_note,
                 persona, joins_round=0, is_facilitator=False, away=()):
        self.player_id = player_id
        self.handle = handle
        self.requested_city = requested_city
        self.is_facilitator = is_facilitator
        #: 0 means seated in the lobby before the game starts; anything else is
        #: a mid-game arrival (spec #3), which is also what decides whether they
        #: get two import turns or one (spec #12).
        self.joins_round = joins_round
        self.engagement = engagement
        self.engagement_note = engagement_note
        self.persona = persona
        self.away = frozenset(away)

    def is_present(self, round_index):
        return round_index >= self.joins_round and round_index not in self.away

    def to_dict(self):
        return {
            "player_id": self.player_id,
            "handle": self.handle,
            "requested_city": self.requested_city,
            "is_facilitator": self.is_facilitator,
            "joins_round": self.joins_round,
            "engagement": self.engagement,
            "engagement_note": self.engagement_note,
            "persona": self.persona,
            "away": sorted(self.away),
        }


#: The long weekend. Named because it is referred to from three places and a
#: bare ``6`` in three away-sets is a coincidence waiting to be broken.
LONG_WEEKEND = 6

SEATS = [
    Seat(
        "m-rvk", "@vidar", "Reykjavík",
        engagement="facilitator, diligent",
        engagement_note=(
            "You run this game and you also play in it under exactly the same rules "
            "as everybody else. You check in every round you are able to."
        ),
        persona=(
            "Mayor of Reykjavík. Dry, precise, faintly weary. Talks about weather and "
            "infrastructure the way other people talk about family. Never oversells."
        ),
        is_facilitator=True,
        away=(LONG_WEEKEND,),
    ),
    Seat(
        "m-vlp", "@rosa", "Valparaíso",
        engagement="eager",
        engagement_note=(
            "You love this game. You check in the moment the round opens, every round, "
            "and your offers are the most elaborate at the table."
        ),
        persona=(
            "Mayor of Valparaíso. Warm, theatrical, a little competitive. Runs a city "
            "of hills, funiculars, stray dogs and paint. Cannot resist a flourish."
        ),
        away=(LONG_WEEKEND,),
    ),
    Seat(
        "m-hbt", "@nell", "Hobart",
        engagement="steady",
        engagement_note=(
            "You check in most rounds, usually near the deadline, and you do not "
            "agonise. Occasionally a week gets away from you."
        ),
        persona=(
            "Mayor of Hobart. Understated, deadpan, extremely practical. Weather, "
            "ferries, rope, and a suspicion of anything described as 'vibrant'."
        ),
        away=(LONG_WEEKEND, 9),
    ),
    Seat(
        "m-kmp", "@otim", "Kampala",
        engagement="erratic",
        engagement_note=(
            "You are genuinely enthusiastic and genuinely unreliable. You miss rounds "
            "entirely, then come back and act as though you had been there all along."
        ),
        persona=(
            "Mayor of Kampala. Loud, fast, funny, generous. Boda riders, markets that "
            "start before dawn, and an unshakeable belief that everything is fixable."
        ),
        away=(2, LONG_WEEKEND, 11),
    ),
    Seat(
        # Asks for a city the facilitator already holds. Spec #2: the first claim
        # stands and this seat is moved to a geographically close alternative,
        # announced, never silent. Whatever the gazetteer picks is what this
        # mayor's agent was briefed as, so the persona is written for the city
        # they actually got.
        "m-kop", "@juno", "Reykjavik",
        engagement="steady",
        engagement_note=(
            "You joined a beat late, asked for a city that was already taken, and were "
            "moved next door. You are good-natured about it and mention it more often "
            "than strictly necessary."
        ),
        persona=(
            "Mayor of a town in the shadow of a capital, which is most of your "
            "personality. Modern, sensible, mildly overshadowed, quietly excellent at "
            "the things the big neighbour does not bother with."
        ),
        away=(4, LONG_WEEKEND),
    ),
    Seat(
        # Off-gazetteer on purpose (spec #2: "players may pick freely"), and a
        # mid-game arrival (spec #3) who therefore earns one import turn, not two
        # (spec #12) -- provided they export at all, because that is what queues
        # them (spec #5).
        "m-nao", "@tobi", "Naoshima",
        engagement="lurker",
        engagement_note=(
            "You joined late and mostly read. You check in rarely, and when you do it "
            "is brief and slightly apologetic. You are more interested in the "
            "newspaper than in winning."
        ),
        persona=(
            "Mayor of Naoshima -- a small island of art museums, ferries, olive trees "
            "and about three thousand people. Quiet, wry, unbothered by scale."
        ),
        joins_round=3,
        away=(5, LONG_WEEKEND, 8, 10),
    ),
    Seat(
        "m-bel", "@asha", "Belgrade",
        engagement="late but keen",
        engagement_note=(
            "You arrived after the game was well underway and are making up for it. "
            "You check in every round you can and you take the picking seriously."
        ),
        persona=(
            "Mayor of Belgrade. Blunt, hospitable, argumentative in a friendly way. "
            "Rivers, concrete, coffee that takes two hours, and strong opinions about "
            "everybody else's opinions."
        ),
        joins_round=4,
        away=(LONG_WEEKEND,),
    ),
    Seat(
        # The other side of spec #12. Everyone above queues while rotation 1 is
        # still open and is owed two import turns; this seat arrives after
        # rotation 1 has closed and is owed exactly one. Without them the
        # rotation-count rule is only ever tested in the direction that passes
        # by default.
        "m-tri", "@pell", "Trieste",
        engagement="very late",
        engagement_note=(
            "You joined when the game was two thirds over, on a friend's "
            "recommendation. You are entirely aware you have missed most of it and "
            "entirely unbothered."
        ),
        persona=(
            "Mayor of Trieste. Melancholy, literary, coffee-obsessed. A port city "
            "that has belonged to four countries and is loyal to none of them."
        ),
        joins_round=9,
        away=(11,),
    ),
]

SEATS_BY_ID = {seat.player_id: seat for seat in SEATS}


def facilitator_seat():
    for seat in SEATS:
        if seat.is_facilitator:
            return seat
    raise AssertionError("the table has no facilitator (spec #4, #6)")
