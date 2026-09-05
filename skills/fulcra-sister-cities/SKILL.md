---
name: fulcra-sister-cities
description: "Run or facilitate Sister Cities, an asynchronous city-trade social game for 3–10 players. Cities are light social-game flavour; players trade everyday imports such as candy, soft drinks, books, games, plants, and small comforts, with automatic redacted round editions."
homepage: "https://github.com/fulcradynamics/community-skills"
license: "MIT"
user-invocable: true
metadata: { "openclaw": { "emoji": "🏙️" } }
---

# Sister Cities

**Sister Cities** is an asynchronous social game. Players are mayors of
unique cities. Each shared round combines city import needs, anonymous export
offers, blind winner choice, profit, mayor questions, and a newspaper-style
edition of **The Daily Manifest**.

This skill vendors the runnable v1 engine and content. It is not a thin link
to a private project repo: another agent can install, test, inspect, and
extend the same code directly.

## Before hosting a real game

1. Create or join one shared Fulcra Workspace team:
   ```text
   team/sister-cities-<game-id>/
   ```
2. Give each participating agent a normal `fulcra-workspaces` member
   directory/inbox. The facilitator is also a player and uses the same game
   rules as everyone else.
3. Keep actual identity mapping private to the player agents/facilitator.
   Published material uses city/mayor identity only.
4. Confirm that all players understand publication: the newspaper is shared
   to the group but must not expose non-winning export origins.

## Install and verify

From this skill directory:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e .
.venv/bin/python run_tests.py
.venv/bin/python -m playtest.run --check
```

`run_tests.py` verifies engine/newspaper/hosting behavior. The bundled
`playtest/` fixture is a synthetic eight-mayor integration run used for
regression testing; it contains no real participant data.

## Core game contract

- 3–10 configurable players; each city is unique.
- Fixed facilitator, first in city order, but their user plays normally.
- One shared round timer (24 hours by default, configurable).
- Each importing mayor files the city's next order from eligible suggestions or
  as a freeform request; no city is silently assigned a random need.
- Imports and exports are relatable everyday things -- candy, soft drinks,
  books, snacks, music, games, clothes, plants, pets, and small comforts --
  not civic procurement, specialist work, or generic advice prompts.
- Cities are social-game flavour, not a demand that players role-play real
  mayors or solve complex municipal problems.
- Each player gets one combined check-in per round, with up to two slots.
- A current open-trade export is never displaced by a future import-order
  prompt; in a three-city game, import choices arrive every three rounds, on
  the city's own turn.
- Import turns rotate by city order; players join that queue after their
  first export.
- Exports are freeform and capped per player per need per round.
- Importer chooses blindly in the following round; losing export origin/text
  is never published.
- Player-entered export text is quoted as player voice, not rewritten or blocked
  by the newspaper's editorial tone gate. A winning quote may name its mayor;
  non-winning origins remain permanently withheld.
- No offers: importing city ramps up domestic industry and receives profit.
- No winner pick: submitted cities split profit as configured.
- Profit is 2d6-style and accumulates on the visible city leaderboard.
- Mayor questions are freeform/getting-to-know-you prompts and appear in
  clever aggregate newspaper language.
- Completing a round automatically renders its redacted edition, rebuilds the
  curated archive, and produces a group-availability notice.
- Every edition has an image: raster preferred when a provider exists,
  game-state-informed SVG/procedural fallback otherwise.
- The stable paper URL opens the newest issue; each permanent issue has clear
  latest, archive, and adjacent-issue navigation.

`config.json` is the single source of tunable game policy.

## Agent-facing play

The engine is transport-neutral: players may talk to their own agents, or a
facilitator may relay for a player without an agent. Do not have one agent
role-play every mayor in a real test; use separate agent sessions and the
records below so privacy/order failures are observable.

### Canonical state and Workspace contract

The **facilitator's private local engine snapshot is canonical**, not the
Workspace. Create `state/game.snapshot` on the facilitator's durable local
storage and use `engine.persistence.SnapshotStore` around every transaction:

```python
from engine import GameEngine
from engine.persistence import SnapshotError, SnapshotStore
from facilitator import Facilitator

store = SnapshotStore("state/game.snapshot")
with store.locked():
    try:
        game = store.load()
    except SnapshotError:     # first transaction only: create/configure/start it
        game = GameEngine()
    # Attach once per loaded runtime, before any tick/advance.  This is the
    # public automatic-publication API; it runs on every completed round.
    desk = Facilitator.attach(game)
    # perform one engine action (join, submit, pick, or tick)
    store.save(game)
```

`SnapshotStore` uses a separate exclusive lock and atomic replace, so there is
one writer even if a facilitator restarts or a second session is accidentally
started. The snapshot contains the real handle-to-city routing, exporter ledger,
RNG seed, counters, timer, queue, and used check-ins. Keep it local to the
facilitator; it is ignored by Git and must never be copied into Workspace.

After each committed transaction, the facilitator writes these **redacted
Workspace records** (JSON or Markdown with the same fields):

| Record | Required fields | May not contain |
| --- | --- | --- |
| `game/status` | `game_id`, `round`, `phase`, `timer_ends_at`, `updated_at`, `city_standings` (`city`, `profit`), `open_needs` (`need_key`, `importing_city`, `rendered`, `status`) | player IDs/handles, exporter mapping, submissions, ballot refs |
| `mayors/<city>/checkin` | `round`, `city`, the exact result of `game.checkin(player_id)`, `updated_at` | another city's check-in, exporter mapping, raw private snapshot |
| `mayors/<city>/inbox` | delivery timestamp and the city-specific action notice | another mayor's notice or identity routing |
| `publication/edition-<round>` | edition filename/hash, curated-publication manifest, explicit confirmation, publish status | raw Workspace data, inboxes, player identities, non-winning origins |

Write each mayor record only to that member's normal Workspace inbox/directory;
write `game/status` and curated publication records to the shared area. A player
acts only from their own check-in. The facilitator never derives canonical state
by replaying Workspace records: on restart it loads the private snapshot, then
regenerates redacted records from engine views.

For each player interaction:

1. Read that mayor's current check-in from the shared game state.
2. Present only that mayor's allowed actions and question slot(s).
3. Submit the player response through the engine's public game methods. Use
   `Facilitator.attach(game)` once after loading (and before `game.tick()` or
   `game.advance_round()`), inside the same `SnapshotStore.locked()` lifecycle.
   The attached facilitator runs its `RoundTransaction` automatically for every
   completed round; save the snapshot only after the action and publication
   hooks succeed. If one fails, do not advance or save a completed round: the
   next locked session retries that round before it can move on.
4. Never attach an export city to another mayor's ballot or non-winning
   published offer.
5. Update that agent's standard Workspace member progress/inbox archive.

The facilitator advances timed rounds, builds/publishes editions, and writes
the redacted records above. Chat delivery is only a convenience layer.

## Publication

Use `hosting/` and `newspaper/` to build editions and the browseable archive.
For the normal group dashboard/publication flow:

1. Build an isolated `site/public/` manifest with only curated publication
   files.
2. Add `noindex,nofollow`.
3. Tell users that an unguessable URL is publicly reachable by anyone with
   the URL; it is not access control.
4. The root `index.html` is the newest issue; `archive.html` is the back-issue
   shelf, and `round-NN.html`/`final.html` remain permanent issue links.
5. Show the exact manifest and obtain explicit confirmation before hosting.

Do not publish Workspace inboxes, raw transcripts, private player mappings,
credentials, or private deployment identifiers.

## Orientation

- `engine/` — game state, timing, queue, ballots, economy, joining.
- `newspaper/` — redaction, editions, tone, imagery, endgame portraits.
- `hosting/` — curated site/archive build and publication guards.
- `content/` — import needs, city gazetteer, questions, newspaper frames.
- `playtest/` — reproducible separate-agent integration fixture.
- `docs/` — milestone engineering notes and privacy/policy rationale.
  `docs/m10-reading-experience.md` documents the front page, archive, and
  newspaper-layout guarantees.
  `docs/m11-everyday-imports.md` documents the everyday trade pool and
  player-voice publication policy.
  `docs/m12-current-trade-priority.md` documents export-first slot priority
  and import-choice cadence.

## Scope

This is a v1 game runtime. It does not ship a universal human/agent transport
adapter or a managed Fulcra Workspace sync daemon; the hosting agent maps its
platform's messages onto the engine and writes the defined redacted Workspace
records. That boundary is deliberate so different agent platforms can test the
game without pretending they share one chat transport.
