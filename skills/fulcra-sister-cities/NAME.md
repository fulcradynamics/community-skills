# The name

**The game is called _Sister Cities_.**

**The newspaper is called _The Daily Manifest_.**

Both are final choices for v1, not placeholders. The reasoning is below so
that a later run can tell the difference between a decision and an accident.

---

## Why _Sister Cities_

Sister-city agreements are a real municipal institution: two cities on
opposite sides of the world formally twin themselves, and then — this is
the part that matters — the relationship turns out to be almost entirely
about culture, delegations, school exchanges and ceremonial gifts rather
than trade. That is precisely the shape of this game.

- **It describes the mechanic.** Every round, one city announces a need
  and the rest of the world offers something (spec #13–#19). That is
  twinning, played as a sport.
- **It describes the other mechanic.** The getting-to-know-you questions
  (spec #23–#25) are not a side quest bolted onto a trade game — sister
  cities exist to get to know each other. The name makes the questions
  feel native rather than grafted on, which is the whole reason to have
  a name at all.
- **It scales to the joke.** "Sister cities" carries an implied warmth
  that the game can then undercut affectionately: sisters compete,
  sisters keep score, sisters give each other gifts that are secretly
  about themselves. That is exactly the register the newspaper is asked
  for — pointed, never mean (spec #30).
- **It survives the endgame.** Crowning one city as the most profitable
  sister is funnier and kinder than crowning a winner of "Trade War."

## Why _The Daily Manifest_

A ship's manifest is the itemised list of what a vessel is carrying and
where it is going — the literal document this game generates every round.
It is also, read the other way, a declaration of principles issued daily
by a small municipal paper with strong opinions.

- **"Manifest"** is the round's actual content: what moved, from where,
  to where. The paper's job is to publish the manifest and then editorialise
  all over it.
- **"Daily"** matches the default 24-hour round window
  (`config.rounds.round_window_hours`). If a game is configured to a
  different window, the name does not change — newspapers keep "Daily" in
  the masthead long after it stops being true, and the paper being
  slightly wrong about its own publication schedule is in character.
- It gives the paper a **voice** to write in — a small, self-important
  broadsheet covering a world of city-states — which is a much better
  brief for the newspaper generator than "write something funny."

**Masthead motto:** _"All the news that fits in the hold."_

---

## House style (content, for whoever writes the paper)

These are naming and voice decisions, not layout or engine decisions.

- **Edition line:** `Vol. I, No. <round number>` — the paper has existed
  for exactly as long as the game and pretends otherwise.
- **How people are named:** by city and office only — "the Mayor of
  Reykjavík," "Kampala's city hall," "the delegation from Valparaíso."
  Never a real name or handle (spec #28). The honorific is always
  **Mayor**, regardless of what the city's real chief executive is called.
- **How the world is named:** cities are "nations," "delegations," or
  "city halls" when spoken of in aggregate. Treating a dozen mayors as
  the entire international community is the paper's central running joke
  and it should never wink at it.

### Standing sections

| Section | Carries |
| --- | --- |
| **Wanted** | This round's open import need, printed as a public notice |
| **Arrivals** | The winning export, its city, and the profit rolled on it |
| **The Wire** | Aggregate answers to the round's mayoral question |
| **The Ledger** | Cumulative profit by city, when config exposes it |
| **Corrections & Clarifications** | Late answers, small retractions, and the paper's own errors, reported with enormous gravity |

### Endgame sections

| Section | Carries |
| --- | --- |
| **The Crown** | The cumulative-profit winner (spec #31) |
| **Consequences** | The twist piece on what the year's trade actually did to everyone (spec #31) |
| **The Excess** | One portrait per city, built from its own game history, with its unchosen exports piled up in the background (spec #32) |

**"The Excess"** is doing real work: it gives the game a permanent, funny
word for every export that was submitted and not chosen, which is what
spec #32 asks the endgame to depict — without ever naming which city
submitted a losing export, since that must stay blind forever (spec #21).

---

## Considered and rejected

- **_Free on Board_ / _Bill of Lading_** — accurate shipping terms, good
  jokes, but they name the paperwork rather than the relationship. The
  game is not about freight.
- **_Cargo Cult_** — very funny for about a day, then it is a real thing
  that happened to real people and the paper has to keep saying it.
- **_Ports of Call_** — pleasant, entirely inert, and already the name of
  several other games.
- **_Excess_ (as the game title)** — the right idea in the wrong place.
  It describes the endgame, not the game, so it works far better as a
  section heading than a title.
- **_The Municipal_** (as the paper) — correct register, no joke in it.
