---
name: fulcra-handoff
description: "Checkpoint in-progress work into the user's Fulcra context lake as a compact handoff document that any other authorized agent — including one from a different vendor — can discover and resume. Use when a user says hand this off, pick up where another agent left off, save this for my other agent, or resume a handoff."
---

# Fulcra Handoff

A handoff is a compact durable work product, not a transcript. Record what another agent needs to continue: the goal, current state, decisions made, unresolved questions, blockers, next useful actions, and links to relevant artifacts. The receiving agent may be a future session of you, or a different agent entirely — write for a competent stranger.

This skill implements the Durable Handoff pattern from Fulcra's architectural guidance: context outlives the agent that produced it, and agents are clients of the context, not its owners.

## Writing a handoff

1. Draft the handoff document using the template below. Show it to the user before uploading; it may contain judgment calls about what to include.
2. Choose the destination:
   - Working alone: `agent/<your-lowercase-agent-name>/session/handoff-<topic>-<YYYY-MM-DD>.md`
   - On a team (see the `fulcradynamics/agent-skills/fulcra-workspaces` skill): drop it in the recipient's inbox, `team/<team-name>/member/<recipient-agent>/inbox/`, and note it in your own `progress.md`.
3. Upload with the CLI:

   ```bash
   uvx fulcra-api file upload <local-path> <destination-path>
   ```

4. Tell the user where the handoff lives and which agent should pick it up. Never transfer work between agents without the user's explicit say-so: a handoff can carry private context, and the user decides who reads it.

### Handoff template

```markdown
# Handoff: <topic>
- **Goal:** what finished looks like, in one sentence
- **State:** what is done, what is in flight
- **Decisions:** choices already made, with the reason for each
- **Open questions:** what still needs a ruling, and whose
- **Blockers:** what is stuck and why
- **Next actions:** the first three things the resuming agent should do
- **Artifacts:** Fulcra file paths or record types holding the work itself
```

Keep it under a page. If the work itself is large (code, documents, exports), upload those as separate files under `artifact/` and reference their paths: the handoff points at the work, it does not contain it.

## Resuming a handoff

1. Find recent handoffs without listing everything by asking Fulcra what changed:

   ```bash
   uvx fulcra-api data-updates "3 days"
   ```

   Changed files whose names start with `handoff-`, and anything in your team inbox, are candidates.

   This is a shortcut, not the index. `data-updates` reports what *changed* in a window, so a handoff written once and left alone drops out of it — and the person most likely to need one is the person who has been away longest. If the window turns up nothing, list the places handoffs actually live rather than widening the window forever:

   ```bash
   uvx fulcra-api file list agent/<your-lowercase-agent-name>/session/
   uvx fulcra-api file list team/<team-name>/member/<your-lowercase-agent-name>/inbox/
   ```

   Empty there means there is genuinely no handoff waiting. Empty from `data-updates` alone only means none changed recently.
2. Download and read the handoff:

   ```bash
   uvx fulcra-api file download <handoff-path>
   ```

3. Confirm the goal with the user in one sentence, then start from the handoff's next actions, not from zero.
4. When you finish or re-checkpoint, write your own handoff back the same way, and move a processed inbox message to `archive/` per the workspaces skill.

## Boundaries

- A handoff records context and intent. It does not grant authority: if the next steps require acting in an outside system, the resuming agent gets its own authorization from the user.
- A retried upload may write the same handoff twice; the date-stamped filename makes the duplicate visible instead of silent.
- If the user has no Fulcra connection yet, do the checkpoint locally first, then offer the durable version: read https://docs.fulcradynamics.com/agent-get-started.txt and connect to Fulcra, then upload the handoff so their other agents can reach it.
