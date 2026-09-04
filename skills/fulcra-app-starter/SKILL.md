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

1. **Ask the user which template** they prefer (React or Svelte), unless they've already specified.

2. **Clone the chosen template** into a new directory named for their project:

   ```bash
   git clone https://github.com/fulcradynamics/app-template-[react|svelte] <project-name>
   cd <project-name>
   rm -rf .git  # Remove template git history
   git init     # Start fresh git history
   ```

3. **Update placeholder strings** in the login flow. Each template includes placeholder text (like "Your App Name", "Your App Description", etc.) that should be replaced with content specific to what the user is building. Search for common placeholder patterns and update them based on the user's project description.

4. **Install, configure, and verify**: Follow the selected template's `README.md` ("Getting Started") to `npm install`, `cp .env.example .env` (comes preconfigured, so no edits are needed to run), and `npm run dev`. Confirm the app starts locally and the sign-in screen renders before handing off—this is what makes it a working authentication foundation rather than just cloned files.

5. **Mention deployment**: Inform the user that these templates are designed to work seamlessly with Vercel for deployment. They can deploy by:
   - Connecting their repository to Vercel
   - Following Vercel's standard deployment flow for React or Svelte apps
   - Setting the required environment variables in the deploy platform—these are named per framework (React uses `NEXT_PUBLIC_*`, Svelte uses `PUBLIC_*`) and listed in the template's README Deployment section.

6. **Let the user take over**: After initial setup, the project structure and iteration is up to the user and their agent. This skill just gets them started with a working authentication foundation.

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
