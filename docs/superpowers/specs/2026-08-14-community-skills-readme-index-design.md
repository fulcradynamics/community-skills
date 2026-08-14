# Community Skills README Index Design

## Goal

Replace the repository's one-line README with a useful catalog of the
community-contributed skills that extend Fulcra's official
[`agent-skills`](https://github.com/fulcradynamics/agent-skills) collection.

## Audience and Positioning

The README serves two audiences:

- People deciding whether this repository contains a useful Fulcra extension.
- Agents looking for the correct `SKILL.md` to load for a requested workflow.

It must state clearly that these skills are contributed by the community,
built on Fulcra and its core skills, and complementary to—not replacements
for—the official skills repository.

## Content Structure

The README will use a curated hybrid catalog:

1. A concise introduction that explains the repository's relationship to
   Fulcra and the official skills collection.
2. Installation guidance for both the official foundation and this community
   collection, using the `skills` CLI.
3. A compact skills index inspired by the project table in
   `ashfulcra/fulcra-tools`, with columns for the skill, what it does, and the
   core Fulcra capability or skill it builds on.
4. A short section for each current community skill, linked from the index:
   - `fulcra-agent-coordination`
   - `fulcra-computed-data-types`
   - `fulcra-project-dashboard`
   - `fulcra-rapid-prototype`
5. A short pointer back to the official skills repository.

The per-skill sections will explain the use case, notable workflow or output,
and dependencies in plain prose. They will link directly to each `SKILL.md`
without reproducing YAML frontmatter.

## Source of Truth

Descriptions will be curated from each skill's full instructions rather than
copied mechanically from frontmatter. This avoids carrying stale wording into
the README and keeps the catalog useful even when metadata is terse.

The directory `skills/*/SKILL.md` remains authoritative. The README is a
human- and agent-friendly index, not a second manifest.

## Scope Boundaries

- Modify `README.md` and add this design record only.
- Do not change skill behavior or metadata.
- Do not add automation or a generated index.
- Do not introduce repository-wide contribution policy not already present.
- Do not assert a repository-level license while no root `LICENSE` file is
  present; individual skill metadata remains unchanged.
- Use current `fulcra-workspaces` terminology when describing workspace-based
  skills.

## Validation

Before publication:

- Confirm every `skills/*/SKILL.md` appears exactly once in the index and once
  as a detail section.
- Confirm every local Markdown link resolves to an existing file.
- Confirm heading anchors used by the table match their detail sections.
- Review the rendered Markdown structure for readable tables, lists, and code
  blocks.
- Confirm the implementation commit changes no skill files.

## Publication

The work will be committed on `agent/community-skills-readme-index`, pushed to
GitHub, and proposed as a draft pull request against the repository's default
branch. The pull request will explain the community-versus-official
positioning, the new index, and the validation performed.
