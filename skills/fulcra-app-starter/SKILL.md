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

Because this skill uses a harness approach, the preferred coding style is to avoid over-engineering, avoid overly-defensive code, and avoid writing an unnecessariliy large number of tests so that milestones only require a reasonable amount of time to be attempted and maintained. The point is to add milestones and allow the project to evolve in a stable way. You'll still have the opportunity to author all the code you want, but use milestones as smaller lego bricks to build your empire.

## Overview

This skill helps users start a Fulcra-backed web application by cloning one of the official app templates. These templates provide:

- Complete sign-in and sign-up flow out of the box
- User authentication with Fulcra
- Ready-to-use structure for making authenticated API calls
- Placeholder strings designed to be customized for the user's specific app

Once scaffolded, the user and their agent can iterate on the project to build their specific application.

## Template Options

Choose between two frontend frameworks:

1. **React**: https://github.com/fulcradynamics/app-template-react
2. **Svelte**: https://github.com/fulcradynamics/app-template-svelte

## Workflow

### 1. Interview and Create Spec

Ask the user what they want to build. Based on their response, create a spec that describes the app and breaks it into milestones that fit the harness flow (see [`references/harness-control-flow.md`](references/harness-control-flow.md)). If you need to ask clarifying questions, ask one question at a time.

### 2. Choose Template

Ask the user which template they prefer (React or Svelte), unless they've already specified.

### 3. Clone and Initialize

Clone the chosen template into a new directory named for their project:

```bash
git clone https://github.com/fulcradynamics/app-template-[react|svelte] <project-name>
cd <project-name>
rm -rf .git  # Remove template git history
git init     # Start fresh git history
```

### 4. Customize Placeholders

Update placeholder strings in the login flow. Each template includes placeholder text (like "Your App Name", "Your App Description", etc.) that should be replaced with content from the spec.

### 5. Install, Configure, and Verify

Follow the template's `README.md` ("Getting Started"): `npm install`, `cp .env.example .env`, then review and configure the Auth0 and Fulcra API values as directed. Run `npm run dev` and confirm the app starts locally and the sign-in screen renders before handing off—this verifies a working authentication foundation.

### 6. Mention Deployment

Inform the user that these templates work seamlessly with Vercel for deployment:

- Connect the repository to Vercel
- Follow Vercel's standard deployment flow
- Set environment variables in the deploy platform (named per framework: React uses `NEXT_PUBLIC_*`, Svelte uses `PUBLIC_*`)

### 7. Hand Off to Harness

With the spec, milestones, and working foundation in place, the harness (see [`references/harness-control-flow.md`](references/harness-control-flow.md)) can now process milestones sequentially to build out the app. The user and their agent drive iteration from here.

## Fulcra REST API

The Fulcra API provides a general-purpose backend for web applications. Full API documentation is available at:
**https://docs.fulcradynamics.com/rest-api/**

Key capabilities include:

- User authentication and session management
- Data storage and retrieval (annotations)
- File storage
- Custom tracking and analytics

When building features for the user's app, consult the API docs to understand available endpoints and how to make authenticated requests from the frontend.

## Key Points

- Keep setup minimal and straightforward
- The templates are designed to be customized—don't over-prescribe the structure
- Focus on getting a working starting point with authentication already configured
- The user's vision for their app drives what happens next
- Consult the Fulcra REST API docs when implementing app-specific features
