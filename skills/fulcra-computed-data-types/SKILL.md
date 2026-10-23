---
name: fulcra-computed-data-types
description: "Generates custom Python scripts to parse raw data exports and ingest them as computed Fulcra data types, dynamically tagging records by a specific data dimension (e.g., Artists, Genres, Categories)."
homepage: "https://github.com/fulcradynamics/community-skills"
license: "MIT"
user-invocable: true
metadata: { "openclaw": { "emoji": "🛠️" } }
---

# Computed Data Types Generator

This skill enables agents to act as personal data engineers. Instead of running a static script, you will generate a custom Python parser on the fly to extract a specific dimension (e.g., Spotify Artists, Netflix Genres, Amazon Categories) from a user's raw data export and upload it to Fulcra as a highly-queryable custom data type.

## Prerequisites

1. **The Data:** The user must provide the path to their extracted data files.
2. **Authentication:** Ensure you are authenticated to the Fulcra CLI (`uvx fulcra-api auth login --get-auth-url`).

## Dependencies & References

This skill is an advanced extension of the core ingestion pipeline. You MUST load the `fulcra-ingest` skill (via `skill_view(name="fulcra-ingest")`) to access its reference files. They live in that skill, not in this one, so there is a single source of truth:
- [fulcra-ingest-cli.md](https://github.com/fulcradynamics/agent-skills/blob/main/skills/fulcra-ingest/references/fulcra-ingest-cli.md) has the exact syntax for `data-type create`, `tag create`, and `record` operations.
- [fulcra-ingest-source-mapping.md](https://github.com/fulcradynamics/agent-skills/blob/main/skills/fulcra-ingest/references/fulcra-ingest-source-mapping.md) explains how to register the new computed type in the user's `source_map.md` and log it in the `ingest_log.md`.

## The Workflow

### 1. Identify the Goal and Data Shape
Ask the user what dimension they want to track (e.g., "I want to track my Spotify streams by Artist"). 
Use tools to briefly inspect the shape of their raw data files (e.g., `head -n 20 data.json`) to identify the required fields (timestamps, specific tags, and notes).

### 2. Schema Creation
Check if the desired target schema already exists using `uvx fulcra-api catalog | jq '.[] | select(.categories | index("user_configured"))'`.
If not, consult the `fulcra-ingest` CLI reference to create the appropriate base annotation type (`MomentAnnotation`, `DurationAnnotation`, `NumericAnnotation`, etc.) via the CLI.
Capture the returned JSON schema ID (e.g., `com.fulcradynamics.annotation...`).

### 3. Generate the Custom Processing Script
You must write a custom Python script that parses the user's files and builds the JSONL records. 
**Crucially, do not start from scratch.** Read the template located at `templates/computed_type_template.py`.
The template contains the necessary boilerplate for:
- Generating deterministic UUIDs for idempotency.
- Extracting and batch-creating tags via the `fulcra-api tag create` command.
- Safely caching and matching tags case-insensitively.

Copy the template, fill in the custom parsing logic in the designated `# TODO:` section (handling timestamps, notes, and the extracted tag name), and save it to the local workspace. 
*Tip: If you need an example of a fully implemented script, see `examples/spotify_artists.py`.*

### 4. Execute and Ingest
1. Run your generated script to parse the files, fetch/create the tags, and output the `output_records.jsonl` file. 
2. Consult the `fulcra-ingest` CLI reference to batch ingest your `output_records.jsonl` file (running in the background for large datasets).
3. Update the user's `source_map.md` and `ingest_log.md` according to the rules in the core `fulcra-ingest` skill.

### 5. Handoff
Once the background upload begins, notify the user that their data is being processed and let them know they will soon be able to view their customized, categorized data directly on their timeline.
