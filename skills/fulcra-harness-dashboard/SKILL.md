---
name: fulcra-harness-dashboard
description: "Adapts fulcra-project-dashboard into a safe, manager-facing view for a task-specific agent control harness: milestone/PR timeline, run evidence, durable status summary, decision requests, escalations, and optional curated publication."
homepage: "https://github.com/fulcradynamics/community-skills"
license: "MIT"
user-invocable: true
metadata: { "openclaw": { "emoji": "🧭" } }
---

# Fulcra Harness Dashboard

This is an **adaptation of `fulcra-project-dashboard`**, not a replacement
for it. Start by following that skill's static-triad/dashboard setup. Then
apply only the control-harness-specific additions below.

## Purpose

A project dashboard answers “what has the team done?” A harness dashboard
also answers:

- Which milestone is current, passed, blocked, or queued?
- What did the most recent Generator/Evaluator run prove?
- Is the current issue a user decision, a genuine escalation, or transient
  provider capacity?
- What is the concise “where we are / where we're going / next bearing”
  state?
- Did the milestone PR merge, remain reviewable, or fail evaluation?

## Required durable Workspace inputs

Read only the control harness's durable artifacts:

```text
team/<team>/status-summary.md
team/<team>/milestone-progress.md
team/<team>/progress.md
team/<team>/decision/
team/<team>/escalation/
team/<team>/artifact/*verdict*.md
team/<team>/member/*/progress.md
```

Do not infer status from Discord history, transient local model output, or
scheduler “completed” status alone.

## Base setup

1. Invoke `fulcra-project-dashboard` to build the base static triad and its
   manager-oriented layout.
2. Copy `templates/dashboard-data.json` as the curated data contract and
   use `scripts/refresh_harness_dashboard.py` to refresh it from downloaded
   `status-summary.md` and `milestone-progress.md`.
3. Copy `templates/harness-dashboard-components.js` and
   `templates/harness-dashboard-components.css` into the base dashboard's
   public static-triad assets. Add a root element such as
   `<section id="harness-dashboard"></section>` and call
   `renderHarnessDashboard(root, data)` after the base dashboard loads the
   curated JSON. The component supplies actual rendering for the flight
   plan, checkpoint, interactive run timeline, previous-run context, and
   Open Items; it deliberately does not replace the base dashboard shell.
4. Keep the base dashboard's executive summary, logs, progress, timeline,
   and activity visuals where useful; these adaptations make those views
   control-loop aware.

## Required project theming (restrained)

Before the first dashboard publication, establish a small project-specific
visual theme. A harness dashboard must not look like an unmodified generic
admin page, but theme must improve orientation rather than compete with
operational data.

Required minimum:

1. a project-specific dashboard title/subtitle and section copy;
2. a restrained palette (accent, soft accent, ink, paper/background) tied
   to the project domain;
3. one small motif or visual cue (symbol, border treatment, or compact
   header mark) relevant to the project;
4. readable contrast and unchanged access to milestones, runs, decisions,
   and escalations.

Start with `templates/harness-dashboard-theme.css`. Copy it after the base
`fulcra-project-dashboard` CSS and replace its theme placeholders. Do not
add large decorative imagery, autoplay animation, or third-party visual
assets merely to satisfy this requirement. If the project already has a
recognized identity/theme, reuse it; otherwise ask the user for a concise
vibe before rendering.

The chosen theme must be recorded in the curated dashboard configuration or
project status so later agents refresh rather than accidentally reset it.

## Harness-specific panels

### 1. Flight plan

Render every milestone with `passed`, `current`, or `queued` state from
`milestone-progress.md`. Do not leave a previous milestone visually current
just because a static dashboard file was not refreshed.

### 2. Run timeline

Render each terminal run as a dated marker with:

- milestone ID;
- PASS / escalation / decision-required state;
- short evidence summary;
- selected-run detail plus the previous two run summaries;
- horizontal scrolling and zoom for growing history;
- default scroll position at the latest runs.

### 3. Current checkpoint

Prominently render the durable `status-summary.md` sections:

```text
Where we are
Where we're going
Next bearing
```

Include retry mode (`manual` vs. bounded automatic) so a viewer does not
misread an unattended retry as a human decision.

### 4. Open items

Show only current unresolved items:

- open user decision requests from `team/<team>/decision/`;
- genuine unresolved escalations;
- current milestone work/next bearing.

Remove or mark resolved an item once its user decision is recorded and the
approved spec/config reflects it. Do not retain stale “open” items forever.

## Post-terminal refresh contract (required)

After every terminal milestone outcome for an active
`choice: create_and_publish` dashboard, refresh the local curated dashboard
only after the Coordinator has successfully persisted the canonical Workspace
`status-summary.md`, milestone progress, and any terminal verdict/decision
record. A dashboard must never silently keep showing an earlier completed
milestone as current.

1. Download the current durable status/progress inputs and refresh the
   curated JSON. Add a concise run-timeline entry from the terminal outcome;
   do not copy a raw verdict archive into `public/`.
2. Compare the exact candidate public manifest (path, byte size, and
   SHA-256) with the last deployed manifest, recorded durably at
   `team/<team>/dashboard/state.md` together with the dashboard URL and
   publication time.
3. If the manifest is unchanged, retain the deployed dashboard and record a
   successful refresh check. If it changed, write `refresh_pending` to the
   durable dashboard state and surface an operator decision request with the
   exact changed manifest.
4. Never silently republish a changed manifest. Print the public-manifest
   delta, restate that anyone with the URL can access it, and obtain a new
   explicit user confirmation. After deployment, update the durable state
   with the new URL (if changed), manifest SHA-256, and timestamp.

The dashboard URL is durable operational state, not a credential. It belongs
in the Workspace dashboard/status state rather than a local `.env` file.

## Publication adapter (normal flow; explicit user gate)

The normal harness-dashboard flow is **private-by-unguessability
publication**: deploy the curated `public/` dashboard to an unguessable
URL so the same status view is available across users/agents/sessions.
Surge is the preferred simple default, but another host is acceptable if it
supports the same safety contract.

Before every first deployment (and whenever the public manifest changes):

1. Build an isolated `public/` directory containing only UI assets and
   explicitly curated `dashboard-data.json`.
2. Copy `templates/public/noindex-head.html` into the `<head>` of
   `public/index.html`, producing:
   ```html
   <meta name="robots" content="noindex, nofollow">
   ```
3. Print the exact public manifest and tell the user plainly: **the
   dashboard is publicly reachable by anyone with the URL**. An unguessable
   URL and noindex/nofollow directives reduce discovery; they are **not
   access control**.
4. Obtain explicit user confirmation for that exact manifest.
5. Deploy with `templates/publish_surge.sh` (or an equivalent host adapter)
   using a random/unguessable domain. Keep the URL in the durable harness
   status/dashboard configuration, not in a credential file.

Never publish inboxes, full raw verdicts, credentials, private-repo content,
or raw Fulcra downloads. Make dashboard publish failure visible but never
let it mask the actual harness outcome.

A Coordinator may call a dashboard publish hook after terminal outcomes,
but the hook must first confirm durable status upload succeeded and must
deploy only the already-approved curated public manifest.

## What this skill does not change

- It does not replace `fulcra-project-dashboard`'s base visual system.
- It does not prescribe a particular host, provider, CDN, or dashboard
  framework.
- It does not make a dashboard source of truth; Fulcra Workspace artifacts
  remain canonical.
- It does not publish data automatically without the user's deployment
  permission.
