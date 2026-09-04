# Local security and fixture handling

## Sensitive local state

The default state root is `${XDG_STATE_HOME:-~/.local/state}/engineering-journey-v3`.
`ENGINEERING_JOURNEY_STATE_DIR` may select another root. Configuration lookup does
not create files. Runtime code must create sensitive directories through
`ensure_private_directory` (owner-only mode `0700`) and new sensitive files through
`create_private_file` (owner-only mode `0600`, exclusive creation, no symlink
endpoint where the platform supports `O_NOFOLLOW`). Existing directory permissions
are tightened. A symlink used as the state directory is rejected.

Local state can contain private repository evidence. It must not
be placed in a checkout, shared temp directory, test snapshot, log bundle, or bug
report. Credentials must never be written to plan, checkpoint, progress, handoff, or
fixture files. Automated retention and secure deletion remain deferred; operators must
protect and deliberately remove private run directories when they are no longer needed.

Publication is private-only and bound to the confirmed principal. Private repository access
never authorizes a public/dashboard copy or a copy for another principal. The CLI sends no
evidence to a model provider: untrusted GitHub text is handed to the already-running agent in
explicit delimiters. Credentials remain owned by `gh` and the Fulcra SDK and are excluded from
versioned run-file upload allowlists.

## Fixtures

The enforceable fixture rules are in `tests/fixtures/README.md`. Committed JSON
fixtures must declare synthetic origin and that they contain no private repository
data. Offline adversarial tests reject missing declarations and scan the shipped
runtime for model-provider clients and key checks. The release suite additionally installs
the wheel in a temporary environment and uses only synthetic account names while testing the
GitHub subprocess boundary.
