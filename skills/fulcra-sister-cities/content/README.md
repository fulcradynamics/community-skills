# Seeded game content

The game is **Sister Cities**; the newspaper is **The Daily Manifest**. See
[`../NAME.md`](../NAME.md) for the naming rationale and the paper's house
style.

| File | Serves | Spec |
| --- | --- | --- |
| `import_needs.json` | The draw pool of import needs, plus the categories the repetition rule operates on | #13, #14, #22 |
| `gazetteer.json` | City suggestions on join, and the lookup + documented procedure for reassigning a duplicate city pick | #2 |
| `questions.json` | The mayor question bank, plus the aggregate-phrasing ladder the newspaper reports answers with | #23, #24, #25 |

This directory is **data only**. It contains no game-flow logic — round
timing, queueing, export collection, blind voting, scoring and the
newspaper itself are later milestones. Every behavioural knob these files
reference (`config.cities.*`, `config.imports.*`,
`config.facilitator_questions.*`, `config.content.*`) is read from
[`../config.json`](../config.json); nothing here re-derives a config value
or hardcodes one.

## What the import needs are about (schema 3)

The seed bank has been rewritten twice, and the second rewrite is the one that
matters for playing it. Schema 1 asked exporters what a city *should do* about a
civic problem. Schema 2 (the 2026-08-31 decision) fixed that by making every
need an order for goods — and left a bank of orders for roof trusses, survey
crews, hydrophones and seaweed balers. Both were unplayable for the same
underlying reason: a good offer needed civic or professional knowledge that
nobody at a game night has any reason to bring.

Schema 3 is the 2026-09-02 decision (spec #13a as it now reads). Every one of
the 48 seeds is now something a person can picture in a shop, a kitchen or a
coat pocket, across 16 everyday categories:

| | | | |
| --- | --- | --- | --- |
| `candy` | `soft_drinks` | `snacks` | `baked_goods` |
| `hot_drinks` | `condiments` | `books` | `music` |
| `games_and_puzzles` | `toys_and_novelties` | `clothes` | `plants` |
| `pets` | `homeware` | `stationery` | `small_comforts` |

The city is still the player's persona and still the unit of scoring; it is
light social-game flavour, not a job. A mayor is a person saying what their town
would like a crate of.

`trade_policy` makes that checkable, and it has **three refusals** rather than
one — a need may not ask for **advice**, may not be **civic procurement**, and
may not require **specialist problem solving**. They are separate lists because
they are separate failures: an advice request is not an order at all, a
procurement notice is a perfectly good order that asks a player to behave like a
council officer, and "trusses, ties, and a stamped calculation from somebody
insured" is honest goods that only a professional could answer. All three are
enforced at all three doors into the pool (seeds at load, player suggestions,
and an importing mayor's freeform order) by `engine/trade.py`. The affirmative
half of the check is the declared `trade_family`, whose six values now enumerate
only everyday kinds of thing.

## Deterministic checks

These invariants were verified with `jq` against the committed files. Run
from the repo root to re-check. `tests/test_import_choice.py` holds the same
checks as tests, plus the refusal/acceptance cases the policy exists for.

**Import needs** — `48` needs, `16` categories, ids, titles and briefs unique,
every need in a declared category, every category used, every brief and prompt
city-agnostic (`{city}` present per `placeholders`), no placeholder in any
title, min 3 needs per category:

```sh
jq -c '[ (.needs|length),
         ((.needs|map(.id)|unique|length)==(.needs|length)),
         (.categories|length),
         (.needs|map(.category)|unique|length),
         ((.needs|map(.category)|unique)-(.categories|map(.id))|length),
         (.needs|map(select(.need_brief|contains("{city}")))|length),
         (.needs|map(select(.exporter_prompt|contains("{city}")))|length),
         ((.needs|map(.title)|unique|length)==(.needs|length)),
         ((.needs|map(.need_brief)|unique|length)==(.needs|length)),
         (.needs|map(select(.title|contains("{")))|length),
         (.needs|group_by(.category)|map(length)|min) ]' content/import_needs.json
# => [48,true,16,16,0,48,48,true,true,0,3]
```

All required fields present on all 48, every seed tagged, `61` distinct tags
across the pool (the variety check for #33), and every seed declaring one of the
six everyday trade families — with all six actually used:

```sh
jq -c '[ (.needs|map(select(has("id") and has("category") and has("trade_family")
             and has("title") and has("need_brief") and has("exporter_prompt")
             and has("excess_flavor") and has("tags") and has("source")))|length),
         (.needs|map(select(.tags|length>0))|length),
         (.needs|map(.tags)|flatten|unique|length),
         ((.needs|map(.trade_family)|unique|sort)==(.trade_policy.families|keys|sort)) ]' \
   content/import_needs.json
# => [48,48,61,true]
```

The three refusal lists are non-empty and disjoint, so no phrase can be
attributed to the wrong refusal in a message to a mayor:

```sh
jq -c '.trade_policy | [ (.advice_markers|length), (.civic_markers|length),
         (.specialist_markers|length),
         ((.advice_markers + .civic_markers + .specialist_markers)|length)
           == ((.advice_markers + .civic_markers + .specialist_markers)|unique|length) ]' \
   content/import_needs.json
# => [26,39,26,true]
```

A maximum-size game (10 cities × 2 rotations, per `config.players.max_players`
and `config.rounds.rotations_target`) draws 20 needs from a pool of 48 in 16
categories, so no city ever has to take a category twice.

**Gazetteer** — `148` cities, names unique, no name/alias collisions, every
region declared, no city listed as its own neighbour, ≥4 reassignment
candidates each, no duplicates within a `nearby` list, all coordinates in
range, `32` join-suggestable cities spanning all 12 regions:

```sh
jq -c '(.regions|map(.id)) as $R |
       [ (.cities|length),
         ((.cities|map(.name)|unique|length)==(.cities|length)),
         (.cities|map(. as $c|select(($R|index($c.region))==null))|length),
         (.cities|map(. as $c|select(($c.nearby|index($c.name))!=null))|length),
         (.cities|map(.nearby|length)|min),
         (.cities|map(select((.nearby|unique|length)!=(.nearby|length)))|length),
         ([.cities[]|.name,.aliases[]]|map(ascii_downcase)|group_by(.)|map(select(length>1))|flatten|unique),
         (.cities|map(select(.suggest_on_join))|length),
         ([.cities[]|select(.suggest_on_join)|.region]|unique|length) ]' content/gazetteer.json
# => [148,true,0,0,4,0,[],32,12]
```

Every reassignment candidate is **unambiguous on its own**. A `nearby` entry is
handed to a player with no surrounding context, so a bare toponym shared by two
real cities is a live hazard: an unqualified `"Athens"` under Atlanta reassigns
a Georgian mayor to Greece — well-formed data, 9,994 km wrong, and a silent
failure of #2's "geographically close". Names that collide take a parenthetical
qualifier (`Athens (Georgia)`, `Toledo (Ohio)`, `San Antonio (Chile)`), per
`resolution_rules.naming_convention`. No `nearby` string now resolves to a
gazetteer city or alias outside its own region, and no bare toponym is listed
by cities in two different regions:

```sh
jq -c '. as $g
  | ($g.cities|map({key:.name,value:.region})|from_entries) as $reg
  | ([$g.cities[]|{n:.name,a:.aliases}]|map(.a[] as $x|{key:$x,value:.n})|from_entries) as $al
  | [ ([$g.cities[]|. as $c|$c.nearby[]|select($reg[.]!=null and $reg[.]!=$c.region)]|unique),
      ([$g.cities[]|. as $c|$c.nearby[]|select($al[.]!=null)]|unique),
      ([$g.cities[]|. as $c|$c.nearby[]|{n:.,r:$c.region}]
         |group_by(.n)|map(select((map(.r)|unique|length)>1))|map(.[0].n)) ]' \
   content/gazetteer.json
# => [[],[],[]]
```

Every gazetteer-internal `nearby` link is also genuinely near — the longest is
596 km (Hobart → Melbourne), inside
`config.cities.max_reassignment_search_radius_km` (800):

```sh
jq -c '. as $g | ($g.cities|map({key:.name,value:{lat:.lat,lon:.lon}})|from_entries) as $m
  | [ $g.cities[] | . as $c | $c.nearby[] | select($m[.]!=null)
      | ((($m[.].lat-$c.lat)*111.0) as $dy
         | (($m[.].lon-$c.lon)*111.0*(($c.lat*3.14159/180)|cos)) as $dx
         | (($dy*$dy+$dx*$dx)|sqrt|round)) ] | max' content/gazetteer.json
# => 596
```

**Questions** — `36` questions (≥ the 20 rounds of a maximum-size game, so
none ever repeats), ids and texts unique, every entry fully specified with all
three aggregate registers, every question mayor-framed, ladder tiers strictly
descending 1.0 → 0.4 and no tier declaring a `min_respondents` below the
aggregate floor:

```sh
jq -c '[ (.questions|length),
         ((.questions|map(.id)|unique|length)==(.questions|length)),
         ((.questions|map(.text)|unique|length)==(.questions|length)),
         (.questions|map(select(has("id") and has("text") and has("framing")
             and has("answer_shape") and has("buckets")
             and has("newspaper_hook") and has("aggregate_examples")))|length),
         (.questions|map(select(.aggregate_examples|keys==["majority","split","unanimous"]))|length),
         (.questions|map(select(.framing=="to_the_mayor" or .framing=="about_the_mayor"))|length),
         (.aggregate_phrasing.ladders.default.tiers|map(.min_share)),
         (.aggregate_phrasing.ladders.default
            | ([.tiers[].min_respondents]|min)
              >= .selection.min_respondents_for_aggregate) ]' content/questions.json
# => [36,true,true,36,36,36,[1.0,0.8,0.6,0.4],true]
```

Every `conditional_phrases` entry, wherever it appears, carries both a
`phrase` and an `only_if` (`5` of them, all well-formed):

```sh
jq -c '.aggregate_phrasing.ladders.default as $L |
       [$L.tiers[], $L.tie_case, $L.fragmented_case,
        $L.selection.low_respondent_floor]
       | map(.conditional_phrases // []) | flatten
       | [ length, (map(select(has("phrase") and has("only_if")))|length) ]' \
   content/questions.json
# => [5,5]
```

The ladder is **decidable**: `ladders.default.selection.steps` fixes an
ordered procedure (respondent floor → fragmented → tie → first qualifying
tier), so exactly one outcome is correct for any answer distribution, and the
phrase it licenses is arithmetically true of that distribution. Worked through
by hand for every distribution up to R = 6, the procedure is exhaustive and
mutually exclusive. Five consequences worth knowing before grading #25:

- Below `min_respondents_for_aggregate` (3) the paper uses
  `low_respondent_floor` and does **not** say "the world" — an aggregate over
  two answers is a false claim, not a joke.
- **Ties get their own case.** `tie_case` catches any distribution where two
  or more buckets tie for largest (4 respondents split 2‑2, 6 split 3‑3). A
  tie caps S at 0.5, so it only ever displaces `plurality` and can never
  pre-empt `supermajority` or above. Without it, a plurality phrase could be
  selected at exactly S = 0.5, where nothing actually led.
- **`fragmented_case` owns the whole below‑0.4 range** at 3+ respondents, not
  4+. A 3‑respondent three-way split (1/1/1, S = 0.33) is "the world is
  divided", not "some countries" — there is no agreeing sub-group to point at.
- **A correct outcome does not make every wording under it true.** Each
  outcome's `phrases` are safe by construction — true of *every*
  distribution that can select it. Wordings that need a narrower
  distribution live in `conditional_phrases` with an explicit `only_if`:
  "the world, with one hold-out" (overclaims at 8/1/1, share 0.8 with two
  hold-outs), "the world is split down the middle" (overclaims at 2‑2‑1),
  "no two nations agree" (overclaims at 2‑2‑2), "the only two delegations
  to reply" (needs R = 2). This split is the general fix for that class,
  not a patch on those four phrases.
- `subgroup_phrasing` ("some countries", bucket of 2+) and `outlier_phrasing`
  ("one lone municipality", bucket of 1) are garnishes alongside the chosen
  outcome, **not tiers**. Both were previously tiers (`minority` at 0.2 and
  an earlier `min_share: 0.0` entry) and both were wrong as tiers: they
  handed the headline to a bucket that had already lost, and once
  `fragmented_case` owns everything below 0.4, no distribution could reach
  them anyway. Per-tier `min_respondents` was likewise re-derived after the
  respondent floor was added — nothing declares 2 now, since R ≥ 3 is already
  guaranteed by the time tiers are walked.

**Config cross-references** — `questions.json`'s `set_id` and `scope` match
`config.content.question_set_id` and `config.facilitator_questions.scope`, and
the ladder named by `config.facilitator_questions.aggregate_phrasing_ladder`
exists:

```sh
jq -s '.[0] as $c | .[1] as $q |
       [ ($q.set_id == $c.content.question_set_id),
         ($q.scope  == $c.facilitator_questions.scope),
         ($q.aggregate_phrasing.ladders
            | has($c.facilitator_questions.aggregate_phrasing_ladder)) ]' \
   config.json content/questions.json
# => [true,true,true]

# and all three declared content paths resolve:
jq -r '.content|.import_needs_file,.gazetteer_file,.questions_file' config.json | xargs ls -1
```

## Notes for the milestones that consume this

- `gazetteer.json` seeds the city list; it is **not** the ledger of claimed
  cities. Uniqueness is enforced against the game's runtime city list, which
  also holds off-gazetteer picks. `resolution_rules` in that file spells out
  the procedure.
- `import_needs.json` is appended to during play by player suggestions
  (`config.content.allow_player_suggested_import_needs`); `player_extensions`
  in that file states the schema and the rules a suggestion must satisfy.
- `questions.json`'s `aggregate_phrasing.integrity_rules` are the constraints
  that keep spec #25's "clever" phrasing honest — pick the tier by arithmetic,
  then write the sentence, and never let the questions channel reveal anything
  about who submitted which export (#18, #21).
