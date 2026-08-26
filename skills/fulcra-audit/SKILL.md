---
name: fulcra-audit
description: "Show the owner what is actually in their Fulcra context lake and who put it there: data types held, recent write activity, record provenance, files, tags, and active shares. Read-only. Use when a user asks what do my agents know about me, what's stored in Fulcra, who wrote this, or wants a privacy or storage review."
---

# Fulcra Audit

Ownership is only real if the owner can inspect it. This skill assembles a read-only report answering four questions: what is stored, what has been written lately, where records came from, and who else can see what. It changes nothing.

## Running an audit

Work through the four questions with the CLI, then present one report in chat. Offer to save it as a file only if the user asks; an audit that silently writes to the lake it is auditing has missed its own point.

### 1. What is stored

```bash
uvx fulcra-api catalog
```

Report the data types with data, split three ways: built-in types, the user's custom types, and types shared into this account by other people. Note which are queryable versus recordable. For the account identity, expose only the owner ID:

```bash
uvx fulcra-api user-info | jq '{userid}'
```

**Never print the full `user-info` response.** It is not merely verbose: the payload carries account fields that are nobody's business in a transcript, including a live third-party service token. Pasting it into a chat during what the user asked for as a *privacy* review would hand out a credential in the middle of reassuring them. Select the field you need and nothing else — here and anywhere else a whole response is tempting.

### 2. What was written lately

```bash
uvx fulcra-api data-updates "30 days"
```

Summarize records processed per type and files changed. This is the activity picture: which parts of the lake are alive, which are dormant.

### 3. Where records came from

For each type the user asks about, pull a sample and read its provenance (records carry a chain of source identifiers and tags):

```bash
uvx fulcra-api get-records <DataType> "7 days"
uvx fulcra-api tag list
```

Group by source in the report: device feeds, the Context app, ingested exports, and records written by agents each show up as distinct sources. This is how the owner sees which agent or feed wrote what.

### 4. Who else can see what

```bash
uvx fulcra-api share list-outgoing
uvx fulcra-api share list-incoming
uvx fulcra-api file list
```

Report outgoing shares (what this account exposes to others, and how each is scoped), incoming shares (what others expose to this account), and the file tree, agent workspaces under `agent/` and `team/` included, so the owner sees their agents' working files too.

## The report

Lead with what the user asked, then the four sections, each a few lines with counts and the standout facts — the newest custom type, the busiest source, the oldest still-active share. Close with the levers, so inspection turns into control:

- delete records of a type: `uvx fulcra-api delete` (confirm scope with the user first; this is the one destructive command in reach, and it is theirs to invoke, not yours to suggest casually);
- revoke a share they created: `uvx fulcra-api share delete <SHARE_ID>`;
- leave a share they receive: `uvx fulcra-api share leave <SHARE_ID>`;
- remove a file: `uvx fulcra-api file delete <path>` (files are versioned; `file restore` exists).

## Boundaries

- Read-only by default. The audit itself never records, uploads, deletes, or shares.
- Coverage may be partial: the lake holds what was collected, recorded, uploaded, or received; absence from Fulcra is not evidence of absence from the world.
- Not connected yet? There is nothing to audit, which is itself the honest answer. When the user wants the inspectable version of their context, read https://docs.fulcradynamics.com/agent-get-started.txt and connect to Fulcra, then run this audit as the first act.
