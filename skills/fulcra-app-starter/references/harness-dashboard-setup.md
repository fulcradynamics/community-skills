# Harness Dashboard Setup

Steps to set up the harness tracking system and integrate the owner-only
dashboard. Referenced from step 9 of [`../SKILL.md`](../SKILL.md). See
[`harness-control-flow.md`](harness-control-flow.md) for the run flow and how
events are recorded, and [`workspace.md`](workspace.md) for the workspace files.

## Create the harness data type

```bash
uvx fulcra-api data-type create MomentAnnotation "Harness Runs: <project-name>"
```

Save the returned data type ID (of the form `MomentAnnotation/<UUID>`) — it
becomes `PUBLIC_HARNESS_ANNOTATION_ID` below. See
[`harness-control-flow.md`](harness-control-flow.md) for how to write run-event
records into it.

## Add environment variables to `.env`

```
# Server-only — NO PUBLIC_/NEXT_PUBLIC_ prefix. This must never reach the
# browser; the backend compares it against the authenticated user's Fulcra id.
OWNER_USER_ID=<your-fulcra-user-id>

# Client-readable (Svelte PUBLIC_*, React NEXT_PUBLIC_*).
PUBLIC_HARNESS_ANNOTATION_ID=<annotation-id-from-above>
PUBLIC_WORKSPACE_PATH=workspace/<project-name>
```

(For React, use the `NEXT_PUBLIC_*` prefix for the two client-readable vars;
keep `OWNER_USER_ID` server-only with no prefix.)

## Create server endpoints

The dashboard must fetch data through backend API endpoints (not directly from
Fulcra API) to avoid CORS issues. The Fulcra API must be called only from the
backend — never from the browser. Ownership is also enforced on the backend: the
owner's id (`OWNER_USER_ID`) stays server-only, and each route reads the caller's
id from the `fulcradynamics.com/userid` claim already carried in their Fulcra
access token (the JWT in the session cookie) and compares them — no extra network
call, so the identity provider is only hit once, at login. See
[`svelte/harness-api-server.js`](svelte/harness-api-server.js) and
[`svelte/harness-owner.js`](svelte/harness-owner.js) for the complete
implementation, which uses endpoints documented at
https://docs.fulcradynamics.com/rest-api/.

The `issues` and `overview` routes read markdown files from the workspace.
Fulcra's file API is two-step: list the folder
(`GET /input/v1/file?path=/<workspace-path>`, absolute path with a leading
slash) to resolve a file's input id, then download by id
(`GET /input/v1/file/{input_id}/download`, which returns raw text). The reference
`fetchWorkspaceFileText()` helper does both.

- For Svelte: Create:
  - `src/lib/server/harness-owner.js` (copy [`svelte/harness-owner.js`](svelte/harness-owner.js) — the shared `isOwner()` check)
  - `src/routes/api/harness/runs/+server.js` (export the GET_runs function as GET — 403s non-owners)
  - `src/routes/api/harness/issues/+server.js` (export the GET_issues function as GET — 403s non-owners; serves `outstanding-issues.md`)
  - `src/routes/api/harness/overview/+server.js` (export the GET_overview function as GET — 403s non-owners; serves the nurse-authored `overview.md`)
  - `src/routes/api/harness/owner/+server.js` (export the GET_owner function as GET — returns `{ isOwner }` so the dashboard/nav can gate visibility without seeing the id)
- For React (Next.js app router): the same four routes live in their own
  `route.ts` files. See [`react/harness-api-server.ts`](react/harness-api-server.ts)
  for all four handlers (named `GET_*` there only so they fit one file — rename
  each to `GET` in its own route file) and
  [`react/harness-owner.ts`](react/harness-owner.ts) for the shared `isOwner()`
  check. Create:
  - `lib/server/harness-owner.ts` (copy [`react/harness-owner.ts`](react/harness-owner.ts))
  - `app/api/harness/runs/route.ts` (export the GET_runs body as GET — 403s non-owners)
  - `app/api/harness/issues/route.ts` (export the GET_issues body as GET — 403s non-owners; serves `outstanding-issues.md`)
  - `app/api/harness/overview/route.ts` (export the GET_overview body as GET — 403s non-owners; serves the nurse-authored `overview.md`)
  - `app/api/harness/owner/route.ts` (export the GET_owner body as GET — returns `{ isOwner }` so the dashboard/nav can gate visibility without seeing the id)

  Copy the shared `fetchWorkspaceFileText()` helper into a small module (e.g.
  `lib/server/harness-files.ts`) or inline it in each route. Client-readable env
  vars use the `NEXT_PUBLIC_*` prefix; `OWNER_USER_ID` stays server-only.

## Integrate dashboard components

- For Svelte:
  - Install the markdown renderer used for the overview and issues panels: `npm install marked dompurify`. The dashboard runs `marked` to turn the nurse-authored markdown into HTML and `DOMPurify` to sanitize it before injecting with `{@html}`.
  - Copy [`svelte/HarnessDashboard.svelte`](svelte/HarnessDashboard.svelte) to `src/lib/components/HarnessDashboard.svelte`
  - Copy [`svelte/OwnerNav.svelte`](svelte/OwnerNav.svelte) to `src/lib/components/OwnerNav.svelte`
  - Create `src/routes/harness/+page.svelte` (see [`svelte/harness-page.svelte`](svelte/harness-page.svelte))
  - Add `<OwnerNav />` to `src/routes/+layout.svelte` before the main content

- For React:
  - Install the markdown renderer used for the overview and issues panels: `npm install marked dompurify`. The dashboard runs `marked` to turn the nurse-authored markdown into HTML and `DOMPurify` to sanitize it before injecting with `dangerouslySetInnerHTML`.
  - Copy [`react/HarnessDashboard.tsx`](react/HarnessDashboard.tsx) to your `components/` directory
  - Copy [`react/OwnerNav.tsx`](react/OwnerNav.tsx) to your `components/` directory
  - Create the harness dashboard page route (e.g. `app/harness/page.tsx`) rendering `<HarnessDashboard />`
  - Add `<OwnerNav />` inside `<UserProvider>` in `app/layout.tsx`, before the main content

The navigation bar will only appear when logged in as the owner and provides
quick access to the home page and harness dashboard. The dashboard will refresh
every 5 seconds to show live harness progress.

## Deploy dashboard update

```bash
vercel --prod
```

Share the updated deployment URL with the user so they can see the harness
dashboard.
