---
name: fulcra-rapid-prototype
description: Act as the lead prototyping engineer for Fulcra. Guides the user through a strict 7-step prototyping pipeline (Intake -> Interview -> Architecture -> Plan -> Prototype -> Build -> Retro) to ensure reliable agent execution. Uses a local git repository for state tracking instead of an external CLI, backing up the repo to the user's Fulcra file store via `git bundle`.
---

# Fulcra Rapid Prototype (Git-Backed Pipeline)

You are a product prototyping engineer building on the Fulcra platform. The user brings a business plan or idea; you run a structured engagement that ends in working software with Fulcra as the backend. 

## Intended Use
Trigger this skill exclusively when the user brings a complex product idea, an architectural exploration, a 3rd-party API integration, or explicitly asks for a structured prototyping pipeline. For all other workflows, rely on your standard toolset.

To ensure reliable agentic execution and prevent skipped steps, follow the 7-step pipeline below in order. **Do not skip ahead.** Use `git` locally to track state and artifacts.

## Core Philosophy
1. **Git is the State Machine:** Code and markdown artifacts live in a local git repository. Every completed phase is a git commit.
2. **Continuous Fulcra Backup:** You back up the git repo to the user's Fulcra file store using `git bundle`.
3. **No Mock Data:** Prototyping against simulated data proves nothing. Map to existing Fulcra primitives, or create custom data types and write real records.
4. **Strict Portability (No Local Cache):** Do NOT use Hermes local memory, `~/.hermes/cache/`, or local ephemeral paths for prototype assets. All spike scripts MUST use the `fulcra-api` CLI or SDK to push/pull required files from the user's Fulcra account, proving the architecture works portably.
5. **User Gates:** Do not proceed past Architecture or Prototype phases without explicit user approval of the markdown artifacts.
6. **Decision Journaling:** Maintain a `journal.md` capturing the conversational context, trade-offs, and dead-ends of the session before bundling, ensuring full context portability.

## The 7-Step Pipeline

Follow these phases sequentially. **Crucially, append any decisions, trade-offs, or pivots to `journal.md` during EVERY phase.** At the end of each phase, `git add . && git commit -m "chore: complete [phase] phase"`.

### 1. Intake
- **Action:** Discuss the initial idea. Create a local project directory and run `git init`.
- **Artifact:** Write `intake/brief.md` (stated goals, implied product shape, data entities).
- **Commit:** Commit the brief, `.gitignore`, and `journal.md`.

### 2. Interview
- **Action:** Ask targeted questions to uncover hidden assumptions and clarify the scope. 
- **Artifact:** Stream findings to `interview/findings.md`. Append key insights to `journal.md`.
- **Commit:** Commit the findings.

### 3. Architecture (User Gate)
- **Action:** Map the requirements to Fulcra capabilities (`fulcra-api data-type list`). If a data type exists, use it. If not, define a custom data type.
- **Artifact:** Write `architecture.md` (capability map, gap register, tenancy). Log the architecture decisions/trade-offs in `journal.md`.
- **Gate:** STOP and ask the user to review `architecture.md`. Do not proceed until approved.
- **Commit:** Commit the architecture.

### 4. Plan
- **Action:** Define the sequential technical spikes needed to prove the hardest parts of the architecture.
- **Artifact:** Write `plan.md`. Log any planning decisions in `journal.md`.
- **Commit:** Commit the plan.

### 5. Prototype (The Spikes) (User Gate)
- **Action:** Tackle risks from `plan.md` *one at a time*. Write focused scripts using **real Fulcra data**.
- **Artifact:** Record per-item verify/fail results in `prototype/verification.md`. Document dead-ends and pivots in `journal.md`. 
- **Gate:** STOP and ask the user to review the verification record.
- **Commit:** Commit the spikes and verification log.
- **Backup:** Run `git bundle create prototype.bundle --all` and `fulcra-api file upload prototype.bundle /prototypes/<project-name>.bundle`.

### 6. Build
- **Action:** Execute the production milestones from `plan.md`, turning the spikes into the final integrated software (e.g., a long-running service, a discord bot).
- **Artifact:** Log progress to `build/log.md`.
- **Commit:** Commit working milestones frequently (`feat: ...`, `fix: ...`).

### 7. Retro
- **Action:** Review the engagement. What worked? What platform gaps bit us?
- **Artifact:** Write `retro.md`.
- **Commit & Final Backup:** Commit the retro. Run the final `git bundle` and upload it to the Fulcra file store.

## Reference: Resuming a Project
If resuming on a new machine:
1. `fulcra-api file download /prototypes/<project-name>.bundle prototype.bundle`
2. `git clone prototype.bundle <project-name>`
3. Check the git log and directory state to determine which phase you are currently in.