"""A scripted demo game, so the paper can be read before anyone plays.

This is the fixture behind ``editions/sample-game/`` and behind the newspaper
tests. It is deliberately not a happy path: it contains a mayor who joins in
round 3, a notice nobody answers at all, an importing mayor who lets their
picking window lapse, mayors whose two game actions crowd the question out of
their check-in, an export that names its own city, and an export whose own
wording trips the paper's editorial register. Those are the rounds where
the paper has to say something careful, and a sample edition that only showed the
easy round would prove very little.

It runs on a hand-advanced clock and a fixed seed, so it completes instantly and
identically every time -- which is what lets the committed sample editions be
checked for drift rather than merely admired.
"""

from engine import Config, Content, GameEngine
from engine.clock import ManualClock, utc

#: A Thursday morning, so the datelines read like a real week.
START = utc(2026, 9, 3, 9, 0)

FACILITATOR = ("m-rvk", "@ada", "Reykjavík")
FOUNDERS = (
    ("m-vlp", "@bo", "Valparaíso"),
    ("m-hbt", "@cy", "Hobart"),
    ("m-kmp", "@dee", "Kampala"),
)
LATECOMER = ("m-brg", "@eli", "Bergen")

#: What each city orders, in the order its turns come round (spec #13). Since the
#: 2026-08-31 decision nothing is drawn: an importing mayor files their city's
#: next import themselves, so a scripted game scripts that too. These are chosen
#: to read like a table of mayors ordering for their own towns -- Valparaíso
#: buying board games for a wet fortnight, Bergen buying cordial and then coffee
#: -- and to spread across spec #13a's everyday kinds of thing, because the
#: sample editions are also what a reader looks at to find out what this game is
#: about. Since the 2026-09-02 decision that means candy, drinks, books, games,
#: clothes and plants rather than trusses and survey crews: nobody should have to
#: know how a city works to enjoy the sample edition either.
#:
#: Reykjavík's second order is a mapping rather than a seed id: that is the other
#: half of spec #13, a mayor writing their own order when the slate does not have
#: what the city needs, and it is in the sample on purpose so the freeform path
#: is visible in published bytes rather than only in the test suite.
ORDERS = {
    "Reykjavík": (
        "need-plants-01",
        {
            "category": "small_comforts",
            "trade_family": "wear_and_comfort",
            "title": "Four hundred hot water bottles, and the covers for them",
            "need_brief": "It is dark in {city} by two in the afternoon for most of "
                          "December, and the flats at the top of the hill are cold in "
                          "a way that no amount of tea has ever settled. Wanted: hot "
                          "water bottles -- four hundred, rubber, boring, the kind "
                          "that outlive their owners -- knitted covers for all of "
                          "them, and two hundred pairs of thick socks in case the "
                          "covers run short.",
            "exporter_prompt": "Ship {city} four hundred hot water bottles and the "
                               "covers for them, and say what the covers are knitted "
                               "from.",
            "excess_flavor": "hot water bottles, cooling, in a cupboard",
        },
    ),
    "Valparaíso": ("need-games_and_puzzles-01", "need-books-01"),
    "Hobart": ("need-clothes-03", "need-snacks-03"),
    "Kampala": ("need-snacks-02", "need-toys_and_novelties-02"),
    "Bergen": ("need-soft_drinks-02", "need-hot_drinks-01"),
}

#: Each city answers in a consistent voice, cycling through its own offers as the
#: game goes on. Written as consignments rather than counsel (spec #13a, #15), and
#: since the 2026-09-02 decision written as *everyday* consignments: liquorice,
#: socks, apples, kites, cinnamon buns. A reader of the sample should be able to
#: tell within one edition that filling somebody's order needs nothing but taste.
OFFERS = {
    "Reykjavík": (
        "Salted liquorice, forty cases, which visitors have twice described as a prank.",
        "Wool socks in colours our grandmothers chose. A thousand pairs, all slightly wrong.",
        "Skyr by the pallet, the spoons for it, and a warning that it is not a dessert.",
        "A crate of paperbacks about weather, read to destruction over one long winter.",
    ),
    "Valparaíso": (
        "Four hundred metres of bunting in the colours the hills painted themselves, ladders included.",
        "Six thousand alfajores, packed in tins that families here reuse for thirty years.",
        "A brass band with its own van, its own repertoire, and no intention of stopping at ninety minutes.",
        "Nine hundred rooted bougainvillea cuttings, wrapped in yesterday's newspaper.",
    ),
    "Hobart": (
        "Apples, forty cases, in six varieties nobody off this island has heard of.",
        "Two hundred waxed cotton raincoats, unbeautiful, tested annually by the actual weather.",
        "A crate of jam, the recipe, and the woman who will not permit you to alter the recipe.",
        "Board games for a wet fortnight, forty boxes, every piece counted twice.",
    ),
    "Kampala": (
        "Roast maize, chapati and a spice mix in unlabelled bags, because labels slow everything down.",
        "A market's worth of Saturday, transplanted whole, noise included.",
        "Eleven hand-painted shop signs, still wet, and the sign-painter, who travels.",
        "Three hundred kites of feed sack and split cane, and the children who fly them best.",
    ),
    "Bergen": (
        "Rain, in quantity, and the raincoats to shrug at it.",
        "Fish soup in vacuum packs, and a two-hundred-year opinion about freshness.",
        "Seven brass instruments, tuned, and a procession route we are prepared to lend.",
        "Cinnamon buns, three hundred a morning, frozen, ready for an oven you already own.",
    ),
}

#: The one export in this game that names its own city, so the sample exercises
#: spec #21's withholding rule: an offer that signs itself cannot be reprinted
#: without exposing where a losing offer came from.
SIGNED_OFFER = (
    "m-hbt",
    "A crate of Hobart apples with the word Hobart stamped into every single one.",
)

#: The one offer in this game whose own wording the paper would never write, so
#: the sample exercises spec #30b: a mayor's export is player voice, printed as
#: typed even when it trips the editorial register, and cited to the mayor who
#: wrote it rather than absorbed into the paper's voice.
#:
#: "Stupid" here is aimed at a book about drainage, which is the case
#: ``content/newspaper.json``'s own note on the register describes -- a word a
#: kinder paper might use innocently -- and it is the whole reason the register
#: cannot be allowed to bind players: the alternative is a round that will not
#: publish because one mayor was rude about a municipal handbook.
#:
#: It is deliberately the longest offer on its ballot, since the scripted mayor
#: picks by length (see :func:`_pick_winners`), so it wins and is quoted rather
#: than reprinted anonymously. The declined-offer side of #30b is proved in
#: ``tests/test_player_voice.py``, where a game can be built to order.
BLUNT_OFFER = (
    "m-kmp",
    "Two hundred paperbacks from the stall by the taxi park, no two alike, and "
    "the one I nearly kept is a stupid little book about drainage that I have "
    "now read four times.",
)

#: The round-by-round deviations. Everything not listed here is a cooperative
#: round: everybody exports, every importing mayor picks, everybody who is
#: offered the question answers it.
PLAN = {
    # Kampala's delegation is late to the first round, so it is not queued yet.
    1: {"skip_exports": ("m-kmp",)},
    # Bergen joins mid-game (spec #3) and exports immediately, which is what
    # queues them (spec #5).
    3: {"register": (LATECOMER,), "signed_offer": True},
    # Nobody answers this notice at all, so its city ramps up its own industry
    # two rounds later (spec #17).
    4: {"no_exports": True},
    # An importing mayor lets the picking window lapse, so every offer wins and
    # the profit is split evenly (spec #19).
    6: {"skip_picks": True},
    # One mayor simply does not check in.
    7: {"skip_exports": ("m-vlp",)},
    # An offer whose own wording trips the paper's editorial register, sent to
    # Valparaíso's second notice. It wins, and the paper prints it as written
    # and cites it to the mayor who wrote it (spec #30b).
    8: {"blunt_offer": True},
}

#: Questions this seed draws that are deliberately left unanswered, so the paper
#: has to handle an empty postbag. Round 1's is one on purpose: a real first round
#: is exactly when mayors are still working out what the game is.
DELIBERATELY_UNSCRIPTED = frozenset({"q-unofficial-teacher"})

#: What the mayors say, keyed by the question the round actually drew, and the
#: clustering the facilitator applies to those answers. The engine will not
#: cluster freeform answers itself -- deciding that "the fish counter" and "the
#: market" are the same answer is a judgement (see :mod:`engine.aggregate`) -- so
#: a scripted game has to supply the judgement a facilitator would.
#:
#: These are the questions this seed draws, in the order it draws them, less the
#: ones in :data:`DELIBERATELY_UNSCRIPTED`. Between them they cover every outcome
#: the phrasing ladder can select -- the world unanimous, the world with one
#: hold-out, a supermajority, a plurality, a two-way tie, a fragmented world with
#: no two answers alike, and the low-respondent floor -- plus a round where nobody
#: replied at all. A content edit that changes which questions this seed draws
#: leaves one of them unscripted, and ``tests/test_newspaper.py`` fails rather
#: than quietly publishing an empty postbag.
ANSWERS = {
    # Only two mayors are scripted here, so round 2 lands on the low-respondent
    # floor: two answers are not a world and the paper has to decline to
    # generalise from them.
    "q-standing-meal": {
        "Valparaíso": "An empanada from a window on Cerro Alegre, eaten walking.",
        "Kampala": "Roast maize from a woman on Jinja Road who has never once been wrong.",
    },
    "q-desk-object": {
        "Reykjavík": "A pebble from a beach that no longer exists.",
        "Valparaíso": "Half a funicular ticket from 1974.",
        "Hobart": "A jar of something. It was labelled once.",
        "Kampala": "My grandmother's bell, which I ring for no particular reason.",
        "Bergen": "A barometer that has been wrong since April.",
    },
    "q-last-laugh": {
        "Reykjavík": "A puffin, doing something unwise, at considerable length.",
        "Valparaíso": "A cat that has learned to open the office door.",
        "Hobart": "A dog on the ferry who clearly commutes.",
        "Kampala": "A goat on the bypass, entirely unbothered by any of us.",
        "Bergen": "My neighbour, mishearing me, twice, in the same conversation.",
    },
    # Three for one medium and two for another: the one shape where the paper has
    # both a headline bloc and a genuine subgroup to point at ("some countries").
    "q-mandatory-work": {
        "Reykjavík": "A short book about drainage. It would settle several arguments.",
        "Valparaíso": "A film. Two hours in the dark is the only way to get consensus.",
        "Hobart": "A book. Something with maps in it.",
        "Kampala": "A film, so that they all have to sit still for two hours.",
        "Bergen": "A book about weather, so they stop asking me about the weather.",
    },
    "q-never-understood": {
        "Reykjavík": "Brunch.",
        "Valparaíso": "Brunch, and I have genuinely tried.",
        "Hobart": "Golf. All of it.",
        "Kampala": "Brunch. It is two meals refusing to choose.",
        "Bergen": "Camping. We have houses.",
    },
    "q-time-capsule": {
        "Reykjavík": "A tide table, annotated in my own handwriting.",
        "Valparaíso": "A funicular ticket, punched.",
        "Hobart": "A jar of jam and the recipe for the jam.",
        "Kampala": "A recording of the market at seven in the morning.",
        "Bergen": "A length of the old harbour bell rope.",
    },
    # Round 8's four respondents divide exactly two against two, which is the one
    # distribution the plurality register cannot describe -- see the ladder's
    # tie_case.
    "q-mornings": {
        "Reykjavík": "At war, and losing.",
        "Valparaíso": "I tolerate them. They tolerate me.",
        "Hobart": "At war. Openly, and for years.",
        "Kampala": "I love them. The city is at its best at six.",
        "Bergen": "At war. It is dark, it is raining, and I am expected to be cheerful.",
    },
    "q-longest-awake": {
        "Reykjavík": "Thirty-one hours, a newborn, and no regrets whatsoever.",
        "Valparaíso": "Two nights in a hospital corridor with my father.",
        "Hobart": "A sick dog and a very long drive to a vet who was asleep.",
        "Kampala": "My sister's first baby. Nobody in that house slept.",
        "Bergen": "A neighbour's roof came off in the night. We took shifts.",
    },
    # Two, one and one: a bloc that leads without commanding a majority, which is
    # the plurality register and the one place "more capitals than name anything
    # else" is true and "most nations" is not.
    "q-bad-news-style": {
        "Reykjavík": "All at once.",
        "Valparaíso": "It depends entirely on the news, and I know which when I hear it.",
        "Hobart": "All at once. I am not a serial.",
        "Kampala": "All of it, immediately, and then leave me alone for an hour.",
        "Bergen": "In instalments, please. I have to keep working afterwards.",
    },
    "q-never-delegate": {
        "Reykjavík": "The apology. Always the apology.",
        "Valparaíso": "Bad news. I deliver it myself or it isn't delivered.",
        "Hobart": "The apology.",
        "Kampala": "Apologies. And the hiring.",
        "Bergen": "An apology. It has to be the actual mayor or it isn't one.",
    },
    # Round 12 is the round the game ends in, so no check-in happens and nobody
    # answers this one. It is scripted anyway: the engine still draws a question
    # for that round, and a table covering only the answerable rounds would make
    # the drift check in tests/test_newspaper.py impossible to state simply.
    "q-exile-city": {
        "Reykjavík": "I would rebuild in place. Where else would I go.",
        "Valparaíso": "Up the coast. Not far. Within sight of it.",
        "Hobart": "Rebuild. Same hill, same weather, fewer mistakes.",
        "Kampala": "I would stay and start again the following morning.",
        "Bergen": "Somewhere with less rain, and I would be back inside a year.",
    },
}

#: How a facilitator would group each of those answer sets before the paper
#: measures a share (spec #25). Keyed by question, then by city.
BUCKETS = {
    "q-standing-meal": {"Valparaíso": "street food", "Kampala": "street food"},
    "q-desk-object": {
        "Reykjavík": "sentimental", "Valparaíso": "sentimental",
        "Hobart": "unidentifiable", "Kampala": "sentimental", "Bergen": "broken",
    },
    "q-last-laugh": {
        "Reykjavík": "an animal", "Valparaíso": "an animal", "Hobart": "an animal",
        "Kampala": "an animal", "Bergen": "a person",
    },
    "q-mandatory-work": {
        "Reykjavík": "a book", "Valparaíso": "a film", "Hobart": "a book",
        "Kampala": "a film", "Bergen": "a book",
    },
    "q-never-understood": {
        "Reykjavík": "brunch", "Valparaíso": "brunch", "Hobart": "golf",
        "Kampala": "brunch", "Bergen": "camping",
    },
    "q-time-capsule": {
        "Reykjavík": "a document", "Valparaíso": "a personal object",
        "Hobart": "food", "Kampala": "a recording", "Bergen": "something civic",
    },
    "q-mornings": {
        "Reykjavík": "at war with mornings", "Valparaíso": "at peace with mornings",
        "Hobart": "at war with mornings", "Kampala": "at peace with mornings",
        "Bergen": "at war with mornings",
    },
    "q-longest-awake": {
        "Reykjavík": "looking after somebody", "Valparaíso": "looking after somebody",
        "Hobart": "looking after somebody", "Kampala": "looking after somebody",
        "Bergen": "looking after somebody",
    },
    "q-bad-news-style": {
        "Reykjavík": "all at once", "Valparaíso": "it depends on the news",
        "Hobart": "all at once", "Kampala": "all at once", "Bergen": "in instalments",
    },
    "q-never-delegate": {
        "Reykjavík": "the apology", "Valparaíso": "bad news", "Hobart": "the apology",
        "Kampala": "the apology", "Bergen": "the apology",
    },
    "q-exile-city": {
        "Reykjavík": "rebuilding in place", "Valparaíso": "somewhere nearby",
        "Hobart": "rebuilding in place", "Kampala": "rebuilding in place",
        "Bergen": "abroad",
    },
}


def sample_game(seed=7, config=None, limit=40):
    """Play the scripted game to its end and return the finished engine."""
    config = config if config is not None else Config.load()
    content = Content.load(config)
    game = GameEngine(
        config=config, content=content, clock=ManualClock(START), rng_seed=seed
    )
    game.register_player(*FACILITATOR, is_facilitator=True)
    for founder in FOUNDERS:
        game.register_player(*founder)
    _file_orders(game)
    game.start()

    offer_index = {}
    rounds = 0
    while game.phase == "running" and rounds < limit:
        step = PLAN.get(game.current_round, {})
        for late in step.get("register", ()):
            game.register_player(*late)
            _file_orders(game)
        if not step.get("skip_picks"):
            _pick_winners(game)
        if not step.get("no_exports"):
            _submit_exports(game, step, offer_index)
        _answer_question(game)
        game.clock.advance(game.timer.window)
        game.tick()
        rounds += 1
    return game


def _file_orders(game):
    """Every mayor files what :data:`ORDERS` says their city is buying (#13).

    Filed as soon as a mayor is at the table -- before the game starts for the
    founders, on arrival for the latecomer -- which is what a facilitator's
    agent would do with "what does your city need?" and what keeps the check-in
    slots in this sample about exports, picks and questions.
    """
    filed = []
    for player_id in sorted(game.players):
        city = game.players[player_id].city
        scripted = ORDERS.get(city, ())
        while game.unfiled_import_turns(player_id) > 0:
            index = len(game.import_programme_for(player_id)) + (
                game.players[player_id].import_turns_served
            )
            if index >= len(scripted):
                break
            order = scripted[index]
            filed.append(
                game.choose_import(player_id, need_id=order)
                if isinstance(order, str)
                else game.choose_import(player_id, request=order)
            )
    return filed


def _pick_winners(game):
    """Every importing mayor with a ballot in front of them chooses."""
    for player_id in sorted(game.players):
        need = game.picking_need_for(player_id)
        if need is None:
            continue
        for slot in game.checkin(player_id)["slots"]:
            if slot and slot["kind"] == "import_pick" and slot["ballot"]:
                # A subjective choice with no rubric (spec #18); this scripted
                # mayor picks the offer whose text is longest, which is as
                # defensible a taste as any and is at least reproducible.
                best = max(slot["ballot"], key=lambda entry: len(entry["export"]))
                game.pick_winner(player_id, best["ballot_ref"])
                break


def _submit_exports(game, step, offer_index):
    need = game.collecting_need()
    if need is None:
        return
    skip = set(step.get("skip_exports", ()))
    for player_id in sorted(game.players):
        if player_id in skip or player_id == need.importing_player_id:
            continue
        if "export" in game.checkin_used(player_id):
            continue
        city = game.players[player_id].city
        if step.get("signed_offer") and player_id == SIGNED_OFFER[0]:
            game.submit_export(player_id, SIGNED_OFFER[1])
            continue
        if step.get("blunt_offer") and player_id == BLUNT_OFFER[0]:
            game.submit_export(player_id, BLUNT_OFFER[1])
            continue
        offers = OFFERS[city]
        index = offer_index.get(city, 0)
        offer_index[city] = index + 1
        game.submit_export(player_id, offers[index % len(offers)])


def _answer_question(game):
    """Answer this round's question from the script, then cluster the answers."""
    record = game.rounds[game.current_round]
    if record.question_id is None:
        return
    script = ANSWERS.get(record.question_id)
    if script is None:
        # A content edit changed which questions this seed draws. The paper will
        # honestly report that nobody replied rather than invent a distribution;
        # tests/test_newspaper.py asserts this does not happen silently.
        return
    for player_id in sorted(game.players):
        city = game.players[player_id].city
        if city not in script:
            continue
        slots = game.checkin(player_id)["slots"]
        if any(slot and slot["kind"] == "mayor_question" for slot in slots):
            game.answer_question(player_id, script[city])

    answered = game.answers_by_city(game.current_round)
    if not answered:
        return
    clustering = BUCKETS.get(record.question_id) or {}
    buckets = {city: clustering[city] for city in answered if city in clustering}
    if len(buckets) == len(answered):
        game.record_answer_buckets(game.current_round, buckets)
