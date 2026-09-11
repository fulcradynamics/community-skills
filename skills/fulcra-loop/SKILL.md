---
name: fulcra-loop
description: "Build change-driven agent loops on Fulcra: keep a durable watermark, discover what changed since it with data-updates, process only the deltas, record durable outputs, then advance the watermark. Use when a user wants an agent that reacts to new data, a recurring job that starts from what changed, or asks how to poll Fulcra properly."
---

# Fulcra Loop

Every loop starts with what changed. Instead of re-reading everything or asking the user to reconstruct state, a Fulcra loop keeps its own progress marker and asks one question each run: what happened since my marker? This is the Resumable Discovery pattern, and `data-updates` is the command built for it: CLI `uvx fulcra-api data-updates`, MCP `get_data_updates`, REST `/data/v1/updates`.

## The loop contract

Each run, in order:

1. **Read the watermark** — a small JSON file this loop owns:
   `agent/<your-lowercase-agent-name>/loop/<loop-name>/watermark.json`, holding the ISO8601 **upper bound of the last window this loop discovered** — not the time that run happened to finish.

   ```bash
   uvx fulcra-api file download agent/<agent>/loop/<loop-name>/watermark.json
   ```

   No file yet means first run: pick a sensible starting point with the user (for example "7 days ago"), not the beginning of time.
2. **Discover deltas** since the watermark. Capture the upper bound *before* you query, and keep it — this exact value is what you will persist in step 5:

   ```bash
   UPPER=$(date -u +%Y-%m-%dT%H:%M:%SZ)
   uvx fulcra-api data-updates "<watermark>" "$UPPER"
   ```

   The result lists data types with record counts processed in the range, plus changed files. It is a discovery index, not the data itself and not a job queue.
3. **Narrow before retrieving.** Only for the types this loop cares about, fetch the actual records:

   ```bash
   uvx fulcra-api get-records <DataType> "<watermark>" "$UPPER"
   ```

   Ignore everything else the summary mentions; that is the point of the summary.
4. **Produce a durable output.** A loop that only reads leaves nothing for the next agent. Record what you concluded or made: an event via `uvx fulcra-api record`, an updated summary file via `uvx fulcra-api file upload`, or a line in your `progress.md` (see the `fulcradynamics/agent-skills/fulcra-memory` skill).
5. **Advance the watermark last, to the bound you captured in step 2.** Write it only after the outputs are recorded — and write `$UPPER`, never the time the run finished. Those differ by however long steps 3 and 4 took, and anything Fulcra recorded inside that gap would fall before the next watermark yet after this run's query: discovered by nobody, silently. Persisting the captured bound closes the window by construction.

   If the run dies in the middle, the next run re-observes the same window, so make outputs tolerate repetition: overwrite a named summary file rather than appending, or give recorded events a stable identity the loop can check before writing again. Because repeats are already safe, starting the next window a little *before* the stored watermark is cheap insurance at the boundary.

## Setting one up

- Agree the loop's one job with the user in a sentence ("keep a weekly training summary current", "flag new files from my other agents").
- Confirm the types involved exist and have data: `uvx fulcra-api catalog -n <name>` and a one-off `data-updates "7 days"` tell you both.
- Schedule it the way this agent schedules things (a heartbeat entry, a cron job, or the user saying "run my loop") and record the choice in your memory file so future sessions know the loop exists.
- Ask before creating the schedule. A loop that the user did not ask to keep running is a bug, not a feature.

## Worked example: weekly training summary

Watermark at `agent/scout/loop/training-summary/watermark.json`. Each run: capture `$UPPER` → `data-updates` from watermark to `$UPPER` → if `WorkoutSummary` (or the workout types the account's catalog shows) changed, `get-records` just that window → rewrite `agent/scout/artifact/training-week.md` with totals and notable sessions → upload it → write the watermark as `$UPPER`. A workout that lands while the summary is being written is not lost: it sits after `$UPPER`, so the next run picks it up. Re-running after a crash rewrites the same file with the same facts: harmless.

## Boundaries

- One watermark per loop. Two jobs sharing a marker will starve or double-process each other.
- Coverage may be partial: absence of a type in the summary means Fulcra processed nothing new for it, not that nothing happened in the world.
- If the user is not connected yet, run the loop's logic once on whatever they can paste, then offer the durable version: read https://docs.fulcradynamics.com/agent-get-started.txt and connect to Fulcra, and the loop starts waking up to real changes.
