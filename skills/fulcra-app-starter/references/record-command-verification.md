# Record command verification

The harness uses a MomentAnnotation whose `note` is a **string containing JSON**,
not a nested object. These checks exercise the real Fulcra CLI and API, not a
mock ingestion response. Use a dedicated test annotation, never an app's real
harness log; command-verification events are not milestone-completion evidence.

## Reproduce and verify

1. Inspect the installed package version with
   `uvx --from fulcra-api python -c "import importlib.metadata; print(importlib.metadata.version('fulcra-api'))"`.
2. Create an isolated type with
   `uvx fulcra-api data-type create MomentAnnotation "Harness record verification"`.
   Form `MomentAnnotation/<UUID>` from the returned `id`.
3. Run the old invocation with empty non-interactive stdin:

   ```bash
   uvx fulcra-api record "MomentAnnotation/<UUID>" \
     --note='{"run_id":"verification","step":"RUN_START","status":"started","detail":""}' < /dev/null
   ```

4. Isolate the second failure by piping `{}` to the same invocation. This avoids
   empty stdin, but the field option still converts the event into an object:

   ```bash
   printf '%s\n' '{}' | uvx fulcra-api record "MomentAnnotation/<UUID>" \
     --note='{"run_id":"verification","step":"RUN_START","status":"started","detail":""}'
   ```

5. Execute the corrected pipe example from
   [Recording Run Events](harness-control-flow.md#recording-run-events), replacing
   its UUID and run ID with test values. Keep schema validation enabled.
6. Save an outer record with a serialized string `note` to `event.json`, then run
   `uvx fulcra-api record "MomentAnnotation/<UUID>" --file event.json < /dev/null`.
   Include quotes, an apostrophe, backslashes, newline escapes, and Unicode in
   the event detail to exercise serialization rather than only plain text.
7. Read back using `uvx fulcra-api get-records "MomentAnnotation/<UUID>" "1h"`.
   Parse each returned JSONL record, assert `note` is a string, JSON-parse it,
   match the test run IDs and fields, and compare the file's note exactly.
   An ingestion upload receipt alone is insufficient. If records are delayed,
   poll within a bounded timeout rather than re-posting duplicates.
8. Archive the isolated test type after verification with
   `uvx fulcra-api data-type archive "MomentAnnotation/<UUID>"`.
   Retain the verification findings, not credentials or unrelated user data.

## Verified results

On 2026-09-30, with `fulcra-api` **0.1.42**:

- The old `--note` invocation with `/dev/null` failed with
  `Error: No input provided`.
- Adding `{}` stdin to that invocation failed schema validation at `note`:
  the JSON object is not a string.
- Explicit JSON stdin recorded successfully with validation enabled.
- Explicit `--file` input recorded successfully with empty stdin and preserved
  quoted/escaped/Unicode detail exactly.
- The corrected command extracted directly from `harness-control-flow.md`
  recorded successfully. Read-back assertions verified all three successful
  records, their JSON string notes, and the file round-trip.

This verifies the documented recording commands, **not** a newly scaffolded
application or the dashboard UI. The M1 acceptance gate must still be exercised
for each actual app. The credential-free contract tests run with:

```bash
python -m unittest discover -s skills/fulcra-app-starter/tests -v
```
