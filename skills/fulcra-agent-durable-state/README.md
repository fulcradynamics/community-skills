# fulcra-agent-durable-state

Your agent's tools should outlive the machine it happens to be running on.

Cloud containers get reclaimed and rolled back. Laptops sleep, reboot, and disappear. An agent whose scripts live only on local disk is one filesystem event away from amnesia — and the worse failure is not losing a script, it is silently getting an *old* one back. A rollback can revert a patched loop to the unpatched version, or restore a credential you already rotated, and nothing errors until it misbehaves an hour later.

This skill treats the Fulcra File Store as the agent's real home and local disk as a cache. On wake, the agent restores what is missing instead of rebuilding from memory. On change, it pushes the fix immediately, because an unstashed fix is a fix the next rollback undoes. Restores are checksummed against a manifest, so a diverged file fails loudly rather than quietly replacing a good one.

**Secrets never go in the stash.** A shared path is readable by everything that shares it, so credentials belong in environment configuration, the OS keychain, or an operator-held channel — never in a stashed `.env`. The skill carries a fail-closed guard that refuses secret-shaped filenames and credential-shaped content, and it tells you to test that guard against a known-bad file before trusting it. Losing a script costs one download; leaking a credential costs a rotation and an incident.

Needs only `fulcra-api`. No coordination engine, no team bus, no other skill.
