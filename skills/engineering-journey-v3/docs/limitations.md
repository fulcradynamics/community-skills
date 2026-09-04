# Prototype limitations and deferred work

Engineering Journey v3 is a working, private prototype with deterministic ingestion,
recovery, evidence validation, and publication boundaries. It is not an unattended hosted
service. The following limits are intentional and visible:

- The installed Python package does not install GitHub CLI. The operator installs `gh`, and
  GitHub browser/device authentication remains interactive. Fulcra authentication is a
  separate SDK device flow.
- Non-interactive execution cannot confirm an identity or approve a plan. An unchanged digest
  may be supplied only after the exact interactive display has been explicitly reviewed.
- The running agent authors the ephemeral structured narrative plan from the generated
  handoff. There is no external model-provider client or deterministic prose fallback.
- The operator/agent performs two approved `journey` invocations: one to produce the handoff
  and one to validate and privately publish the authored plan. This is not a dashboard.
- Recovery requires the owner-only local run directory. The prototype supports bounded
  checkpoints and reviewed fresh-process resume, but does not schedule backups, retention,
  secure deletion, or automatic restart after a machine failure.
- Publication is only to the two private Fulcra Markdown siblings and a private validation
  report. Public/dashboard publishing, sharing with another principal, and resume generation
  are out of scope.
- GitHub Actions/CI, gists, wikis, Projects, multiple identities, v2 migration/cleanup, and
  persisted editorial rollups or notability scores are not supported.
- GitHub and Fulcra API evolution, very large histories, platform-specific process behavior,
  and revoked permissions need continued operational testing beyond the approved prototype
  run. A snapshot mismatch or partial sibling upload fails visibly and requires an operator
  to review and rerun the unchanged approved command.

Post-prototype work should focus on distribution signing/version policy, broader supported
platform testing, retention controls, clearer guided orchestration around the two narrative
steps, and continued fault injection against API changes. None of that should weaken explicit
identity confirmation, immutable-plan approval, private-only evidence handling, exact raw
citations, or v2 isolation.