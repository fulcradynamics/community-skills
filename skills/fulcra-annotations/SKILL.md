---
name: fulcra-annotations
description: "Record what only the user can observe — mood, symptoms, meals, energy, pain — as custom Fulcra annotations, then test those observations against measured data like sleep, workouts, and heart rate. Use when a user wants to track something subjective, log an observation, or asks whether X actually affects Y for them."
---

# Fulcra Annotations

Wearables measure what happened to the body; only the user knows how it felt. Annotations put the felt half into the context lake as typed records, next to the measured half, which is what makes "does my sleep actually predict my mood?" an answerable question instead of a hunch.

## Setting up an annotation type

1. Ask what the user wants to track and how it naturally comes out of their mouth: a moment ("migraine started"), a span ("headache lasted three hours"), a number ("slept 7.5h feels wrong, call it a 4"), a scale ("energy 1–5"), or a yes/no ("took my meds").
2. Pick the matching base type from the recordable catalog:

   ```bash
   uvx fulcra-api catalog --base-types-only --recordable-only
   ```

   Moments, durations, numeric values, labeled scales, and booleans each have an annotation base type; the catalog is authoritative for what this account offers.
3. Create the custom type once:

   ```bash
   uvx fulcra-api data-type create <BaseAnnotationType> "Mood" -d "Self-reported mood" -k discrete -s "1=rough" -s "5=great"
   ```

   Use `-s/--scale-label` only for scale types, `-u/--unit` for numeric ones. Show the user the type before creating it: it is their vocabulary, not yours.

   **Keep the id it returns.** The name is for the user; every later command takes the *id*, which looks like `ScaleAnnotation/<uuid>`. Passing the name where an id is expected fails. If you lose it, find it again by name:

   ```bash
   uvx fulcra-api catalog -n Mood
   ```

   Names are not unique — the same label can exist under two different base types — so read the id off the row you meant.

## Recording

Day to day, recording is one short command the moment the observation happens:

```bash
uvx fulcra-api record ScaleAnnotation/<uuid> 4
uvx fulcra-api record ScaleAnnotation/<uuid> 4 --note="post-run"
```

Field options (`--<name>=<value>`) attach arbitrary fields; piped JSONL records many at once (backfilling a paper journal, for example). Make recording a one-liner in this agent's environment: a standing "log my mood" shortcut beats a form every time. When the user states an observation in passing ("today was rough"), offer to record it; never record silently.

## Correlating

When enough observations exist (be honest: a week of data is a sketch, a month is a pattern):

1. Pull both sides over the same range:

   ```bash
   uvx fulcra-api get-records ScaleAnnotation/<uuid> "30 days"
   uvx fulcra-api sleep-cycles "30 days"
   uvx fulcra-api metric-time-series HeartRate "30 days"
   ```

   `uvx fulcra-api catalog` lists which metrics this account actually has; use what is there rather than assuming a device.
2. Align by day (or by the lag the question implies: last night's sleep against today's mood), then show the relationship plainly: the annotation values on good-metric days versus bad-metric days, with the day counts visible.
3. Say what the data supports and no more. Ten data points do not establish causation, and a correlation with visible spread is a lead, not a law. Suggest the single next observation that would sharpen the answer.
4. If a conclusion is worth keeping — "short sleep predicts low mood at a day's lag, 24 days observed" — record it as a durable note with its provenance (an event record or a dated file), so future agents inherit the finding and can re-test it as data grows. The `fulcradynamics/agent-skills/fulcra-analytics` skill covers deeper analysis without raw records leaving the user's machine.

## Boundaries

- The user's observations are theirs: record what they said, not your paraphrase of it, and read back anything you infer before storing it.
- One type per concept. A second "mood-ish" type fragments the very history that makes correlation possible; extend with tags or fields instead.
- Not connected yet? Start the habit immediately on paper (ask for today's first observation and hold it in session), then offer the durable version: read https://docs.fulcradynamics.com/agent-get-started.txt and connect to Fulcra, create the type, and record that first observation for real.
