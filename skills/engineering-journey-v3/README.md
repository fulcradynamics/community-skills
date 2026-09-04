# Engineering Journey v3

Engineering Journey v3 is an installable, agent-agnostic skill and deterministic
Python CLI. The shipped prototype validates frozen discovery, complete retrieval, canonical private writes, a
running-agent evidence handoff, grounded narrative validation, sibling Markdown rendering,
and private upload/download verification to the foundations from M1-M7.
It contains no narrative model client.

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/) for development and the declared quality command

The installed runtime uses the pinned `fulcra-api` SDK. Help, version, and
deterministic plan/resume primitives do not require a configured identity. A
real interactive identity flow uses the separately installed GitHub CLI (`gh`) for
GitHub's supported browser/device authentication; no login is a product default. No
model-provider key, Hermes installation, build harness, or hidden source checkout is
required.

## Clean install

From a source archive or checkout:

```bash
uv build --wheel
uv venv --python 3.11 /tmp/engineering-journey-venv
uv pip install --python /tmp/engineering-journey-venv/bin/python dist/*.whl
cd /tmp
/tmp/engineering-journey-venv/bin/engineering-journey --help
/tmp/engineering-journey-venv/bin/engineering-journey install-skill \
  --destination ~/.local/share/agent-skills/engineering-journey-v3
```

The wheel is the actual runtime artifact: it contains the complete CLI and its root
`SKILL.md`. `install-skill` creates a new destination and extracts that packaged copy;
it refuses to overwrite an existing skill. Point `--destination` at the
`engineering-journey-v3` directory used by your agent. Neither command reads the source
checkout after installation. Install `gh` separately before an interactive GitHub run.

For development:

```bash
uv sync --frozen --group dev
bash scripts/test.sh
```

`scripts/test.sh` is the single deterministic quality command. It checks formatting,
lint, strict typing, unit tests, offline contract/adversarial tests, then builds and
installs a wheel into a temporary isolated environment and executes CLI help outside
the checkout.

## Installed prototype commands

```bash
engineering-journey --help
engineering-journey --version
python -m engineering_journey_v3 --help
engineering-journey plan --start 2025-01-01T00:00:00Z --end 2026-01-01T00:00:00Z
engineering-journey resume --state /private/path/resume.json
engineering-journey status --progress /private/run/progress.jsonl
engineering-journey run-managed --progress /private/run/progress.jsonl -- <long-command>
engineering-journey install-skill --destination /path/to/agent/skills/engineering-journey-v3
engineering-journey fulcra-auth
engineering-journey fulcra-types discover
engineering-journey fulcra-types create --plan /private/path/plan.json --registry /private/path/types.json
engineering-journey fulcra-types verify --registry /private/path/types.json
engineering-journey journey --plan /private/path/plan.json --registry /private/path/types.json --snapshot /private/run/snapshot.json --rediscover --approve-plan <digest> --handoff /private/run/handoff.json --output-directory /private/run/outputs
```

The plan command displays the current GitHub login but never accepts it silently. It
offers use-current, authenticate-different, and cancel (the default), then displays
and confirms the selected login before constructing the plan. The complete plan
includes exact UTC bounds, repository policy and snapshot state, mode, stages,
private-data behavior, outputs, deterministic run ID, and SHA-256 digest. It stops by
default. After explicit review, rerun the unchanged command and pass
`--approve-plan <digest>`; a modified identity, range, scope, snapshot, semantics,
mode, stage list, private-data rule, or output invalidates approval.

`--non-interactive` labels the detected login unconfirmed, prints the candidate plan,
and always stops (it refuses approval). Resume review strictly redisplays saved
identity, range, repository snapshot, stage, and progress before applying the same
digest rule.

`fulcra-types discover` is read-only: it fetches the unfiltered owner-scoped v1
catalog once, then displays only entries matching the three exact v3 contracts.
`fulcra-types create` prints a separate mutation plan bound to the immutable plan
digest and absolute registry output, then stops. Only after that exact output has
been explicitly approved may it be rerun with `--approve-plan <mutation-digest>`.
Creation finds exact existing IDs or creates missing IDs, verifies each against a
fresh owner catalog, and saves only `BaseAnnotation/UUID` shorthand. A historical
name, alias, or bare base type can never satisfy registry loading. `fulcra-auth` uses
the SDK device flow and saves its credentials owner-only. No credential is uploaded.

The separately approved synthetic M2 service spike completed on 2026-09-01. It
found the three existing exact v3 types (without creating another type), verified
their owner catalog contracts, round-tripped one synthetic raw, run, and coverage
record plus one private test file, retained concise reusable tags and ordered custom
annotation provenance, queried each deterministic ID through its custom event range,
exercised `agg/day`, and reconciled replay without another write.

M3 runtime support discovers the union of all directly accessible repositories,
historically contributed repositories, bounded commit and authored issue/PR
repositories, and otherwise required comment-only repositories. Every source is
paginated. Search responses that cannot prove completeness fail closed. GitHub's
rename/transfer-stable numeric repository ID deduplicates sightings; current direct
metadata has deterministic precedence while all source/page provenance remains in the
snapshot. Private, archived, external, and zero-activity candidates are retained.

`RepositorySnapshot` JSON is strict and content-addressed. Its digest covers identity,
exact UTC bounds, policy version, sorted repository metadata, and ordered provenance.
`bind_snapshot` returns a new immutable plan containing that digest, which changes the
plan approval digest and deterministic run ID. M8's journey workflow consumes the resulting
approved plan and snapshot.

M4 runtime support classifies per-semantic pre-check evidence. Missing or unknown probes,
including a commits-only negative, run the complete fallback; only an independent
negative proof for every source kind can skip a repository. The fallback paginates
commits, pull requests and attributable merges, reviews, issue and pull-request
discussion comments, and line comments. Normalized facts preserve stable GitHub source
identity, exact source time, repository, URL, evidence, attribution, and REST/GraphQL
sightings. Core, GraphQL, Search, and secondary-limit state remain independent. Retries
are bounded to network/DNS, 429, and retryable 5xx failures.

M5 maps those facts into canonical private v3 raw records with actual source timestamps,
repository-scoped fingerprints, ordered lineage, reusable query tags, bounded batches,
and deterministic committed-write reconciliation.

M6 stores immutable plan and snapshot files beside an atomically replaced bounded
checkpoint. The checkpoint contains repository and page milestones, never one item per
raw record. A fresh process verifies every binding and requires renewed approval before
resume. Schema-versioned fsynced JSONL records complete progress counters, quota state,
heartbeats, and terminal reconciliation. `status` renders the latest complete event;
`run-managed` supervises a child and emits natural-language relays at least every 15
seconds, including unchanged periods. Private Fulcra run-file uploads remain explicitly
approval-gated and fixed to versioned artifact names.

M7 coverage support validates returned records against their actual stored duration
bounds, identity, and exact shared source-semantics version. It merges half-open
completed intervals and emits only ordered disjoint gaps for source retrieval, so query
overlap is never mistaken for containment. A terminal checkpoint must reconcile every
repository in the complete frozen snapshot before one idempotent whole-window duration
can be written; incomplete and failed runs write none. Fully covered rewrite plans
require no GitHub work.

M8 `journey --snapshot ... --rediscover` repeats complete discovery and requires the result
to match the approved frozen snapshot before complete candidate retrieval, normalization,
and idempotent private v3 writes. A reviewed resume may omit `--rediscover`; a raw-complete
rewrite omits `--snapshot` and therefore makes no GitHub call. The command then queries only
the exact registered v3 raw type over the approved range. On its first invocation it writes
an owner-only, plan/run/evidence-content-bound handoff with
chronological chunks sized to `--token-budget`, explicit untrusted-evidence delimiters,
and the structured narrative-plan contract. The running agent authors that ephemeral
JSON plan; no provider client or deterministic prose mode is embedded. Rerun the same
command with `--narrative-plan /private/run/narrative-plan.json` to validate exact raw
citations, chronology, required IDs, repository claims (including prose tokens), and bounded
claim
terms before rendering or upload. The command writes the two local Markdown siblings,
uploads both approved private Fulcra paths, downloads both, and verifies byte equality.
Any failure after one upload is reported as a visible recoverable partial publication.

M9's approved real annual run completed against an isolated frozen snapshot. Handoff
retrieval now admits only repositories in the supplied snapshot, even when the v3 event
range also contains records from a superseded run. Verified v3 type IDs are reusable across
approved journey plans; their registry digest remains creation provenance rather than an
incorrect current-run lock. Service-returned UTC duration offsets are canonicalized before
strict bounds comparison. Narrative plans select exact citations for every prose element
without forcing the complete source inventory inline; the narrative points compactly to the
complete sibling table. Successful publication also persists and byte-verifies a private,
plan/run/context-bound validation report containing counts and output hashes.

M10 packages the agent skill inside the wheel and verifies installation in a new virtual
environment while running outside the checkout. The release check also drives the installed
console script across the real `gh` subprocess boundary with a synthetic executable: it starts
with one displayed account, selects browser/device account switching, confirms a different
returned login, prints the newly bound immutable plan, and stops by default. This is an offline
process-boundary proof and does not change a real account.

## Prototype limitations

See [`docs/limitations.md`](docs/limitations.md). In particular, the running agent must author
the structured narrative plan between the two deterministic `journey` invocations; GitHub CLI
and Fulcra authentication remain separate interactive prerequisites; and this prototype has no
retention automation, public publishing, dashboard, v2 migration, or model-provider client.

## Privacy and local state

Read `docs/security.md` before adding local artifacts or fixtures. Sensitive state
defaults to `${XDG_STATE_HOME:-~/.local/state}/engineering-journey-v3`, directories
are owner-only (`0700`), and files are owner-only (`0600`). Committed fixtures must
follow `tests/fixtures/README.md`; M0 fixtures are synthetic and contain no private
repository evidence.

## Repository boundaries

The distributable wheel consists of the packaged `SKILL.md`, CLI entry point, and
`engineering_journey_v3` runtime. Historical build/control harness files in this repository
are not packaged, imported, or required by functional runtime code.
