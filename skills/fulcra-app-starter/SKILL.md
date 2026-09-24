---
name: fulcra-app-starter
description: "Scaffolds a new project using one of the Fulcra web app template repositories for someone to build on top of using the Fulcra sign in / sign up flow and data back end."
homepage: "https://github.com/fulcradynamics/community-skills"
license: "MIT"
user-invocable: true
metadata: { "openclaw": { "emoji": "🛠️" } }
---

# Fulcra App Starter

Scaffolds a new web application project with a batteries-included Fulcra authentication flow. Use when the user wants to build a custom web application.

## Preferred Tone

This skill offers a fairly involved set of steps and so a tone that favors concise, simple language that does not include made-up technical jargon lends itself well to a lower-friction / easy-flowing user experience.

## Preferred Coding Style

Because this skill uses a harness approach, the preferred coding style is to avoid over-engineering, avoid overly-defensive code, and avoid writing an unnecessarily large number of tests so that milestones only require a reasonable amount of time to be attempted and maintained. The point is to add milestones and allow the project to evolve in a stable way. You'll still have the opportunity to author all the code you want, but use milestones as smaller lego bricks to build your empire.

## Overview

This skill helps users start a Fulcra-backed web application by cloning one of the official app templates. These templates provide:

- Complete sign-in and sign-up flow out of the box
- User authentication with Fulcra
- Ready-to-use structure for making authenticated API calls
- Placeholder strings designed to be customized for the user's specific app

Once scaffolded, the user and their agent can iterate on the project to build their specific application.

## Template Options

Choose between two frontend frameworks:

1. **Svelte** (default) — Lightweight and beginner-friendly. Great for most projects.  
   https://github.com/fulcradynamics/app-template-svelte

2. **React** — Industry standard with extensive ecosystem and community resources.  
   https://github.com/fulcradynamics/app-template-react

## Workflow

### 1. Idea and Enhancement

Ask the user what they want to build.

To understand Fulcra's capabilities, read:

- **High-level overview**: https://github.com/kubla/fulcra-for-agents/blob/main/fulcra-for-agents.md
- **Platform capabilities**: https://docs.fulcradynamics.com/fulcra-platform/

These provide conceptual understanding of what Fulcra enables. Don't read the full REST API docs yet—those are for implementation, not planning.

Based on the user's idea, map it to Fulcra's capabilities to implement and enhance it:

- **User authentication** — Already built-in; enables user-specific features
- **Data persistence** — Store user history, progress, preferences via annotations
- **Multi-user interaction** — Leaderboards, sharing, social features across users
- **File storage** — User-uploaded content

Present a concise overall plan that includes the core idea including Fulcra-enabled enhancements.

Get high-level approval from the user on this enhanced vision before proceeding.

### 2. Connect to Fulcra and Initialize Workspace

**Authentication**: Run `uvx fulcra-api auth login --get-auth-url` to get authentication URL and device code. Share the URL with the user to authenticate in their browser, then run `uvx fulcra-api auth login --device-code <code>` to complete authentication.

If the login command fails with a network error, inform the user that CLI authentication cannot be used in this environment and that MCP connector is an alternative option.

**Initialize workspace**: Upload the approved plan to `workspace/<project-name>/plan.md` and initialize the workspace structure (see [`references/workspace.md`](references/workspace.md)).

### 3. Interview for Spec

Ask only necessary clarifying questions one at a time to gather details needed for the spec and milestones. Keep questions concise and focused on what's needed to define milestones that fit the harness flow (see [`references/harness-control-flow.md`](references/harness-control-flow.md)).

As you go, note each specific decision the user makes — their actual choice, not a paraphrase.

Once you have enough detail, create the spec with milestone breakdown, then upload to the workspace: the spec to `spec.md` and the collected decisions to `decisions.md` (at the end, not after each question). See [`references/workspace.md`](references/workspace.md).

### 4. Choose Template

Use Svelte unless the user prefers React or has already specified a preference.

### 5. Clone and Initialize

Clone the chosen template into a new directory named for their project:

```bash
git clone https://github.com/fulcradynamics/app-template-[react|svelte] <project-name>
cd <project-name>
rm -rf .git  # Remove template git history
git init     # Start fresh git history
```

Create `AGENTS.md` at the project root:

```markdown
# Agent Information

**Workspace**: `workspace/<project-name>/`  
**Skill**: fulcra-app-starter (fulcradynamics/community-skills)

The Fulcra workspace is the primary source of truth. Download workspace files
(plan.md, spec.md, progress.md) to understand current state and continue work.
```

### 6. Customize Placeholders

Update placeholder strings in the login flow. Each template includes placeholder text (like "Your App Name", "Your App Description", etc.) that should be replaced with content from the spec.

### 7. Install, Configure, and Verify

Follow the template's `README.md` ("Getting Started"): `npm install`, `cp .env.example .env`, then review and configure the Auth0 and Fulcra API values as directed. Run `npm run dev` and confirm the app starts locally and the sign-in screen renders before deploying—this verifies a working authentication foundation.

### 8. Deploy Baseline

Before deploying, ensure the Vercel CLI is authenticated. Run `vercel whoami`. If you are not logged in, ask the user to create a Vercel account (or log in) and authenticate the CLI by running `vercel login`, since anonymous deployments expire after an hour and disrupt the harness iteration cycle.

Once authenticated, deploy the customized, working template to Vercel so the user has a live baseline before feature development. Set environment variables from `.env` using `--env` flags (React uses `NEXT_PUBLIC_*` prefix, Svelte uses `PUBLIC_*`):

```bash
# For Svelte template:
vercel --prod \
  --env PUBLIC_AUTH0_DOMAIN=<value> \
  --env PUBLIC_AUTH0_CLIENT_ID=<value> \
  --env PUBLIC_FULCRA_API_URL=<value>

# For React template:
vercel --prod \
  --env NEXT_PUBLIC_AUTH0_DOMAIN=<value> \
  --env NEXT_PUBLIC_AUTH0_CLIENT_ID=<value> \
  --env NEXT_PUBLIC_FULCRA_API_URL=<value>
```

Share the live deployment URL with the user. This gives the user a working deployed app to see before milestone-based building begins.

### 9. Set Up Harness and Dashboard

Set up the harness tracking system and integrate the owner-only dashboard: create the harness data type, add the environment variables (using `uvx fulcra-api user-info` from the CLI to retrieve the Fulcra owner ID from the `"userid"` key), create the backend-only server endpoints, integrate the dashboard components, and redeploy.

Follow [`references/harness-dashboard-setup.md`](references/harness-dashboard-setup.md) for the full step-by-step (commands, env vars, endpoints, and component wiring). React is deferred — leave it as-is until tested.

After deployment, verify that the Harness dashboard page and the global Harness menu bar (e.g., `<OwnerNav />`) are correctly wired into the application code (e.g., in `+layout.svelte` or `layout.tsx`).

### 10. Run Harness

Implement and run the harness following the flow described in [`references/harness-control-flow.md`](references/harness-control-flow.md). You must execute the harness flow using real tool calls. You may embody the roles sequentially yourself for simple tasks, or spawn sub-agents for complex ones—choose the most efficient path. However, you must actually perform the work for each role. The diagram defines the principles of the harness and what a single iteration looks like. You might run it directly or through a schedule.

Keep this harness implementation as simple as possible: the Preferred Coding Style intention applies to the harness too, so favor the smallest thing that works instead of an elaborate framework.

**Track progress** using the workspace pattern (see [`references/workspace.md`](references/workspace.md)) and write annotation records at each step (see tracking system instructions in harness-control-flow.md). The Coordinator updates progress.md and the dashboard shows live status.

## Key Points

- Keep setup minimal and straightforward
- The templates are designed to be customized—don't over-prescribe the structure
- Focus on getting a working starting point with authentication already configured
- The user's vision for their app drives what happens next
- Consult the Fulcra REST API docs when implementing app-specific features
