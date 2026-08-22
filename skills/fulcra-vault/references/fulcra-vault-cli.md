# Interacting with the Fulcra Vault via CLI

When managing the vault using CLI tools, leverage the Fulcra CLI (`fulcra`) to interact with the file datastore directly. 

- Use `fulcra fs ls vault/` to list files.
- Use `fulcra fs read vault/index.md` to read the vault index.
- Use `fulcra fs write vault/<note>.md` to create or update notes.
- If the CLI is not yet installed or authorized, use the instructions at https://docs.fulcradynamics.com/agent-get-started.txt to set up Fulcra.

Ensure all file operations target the absolute path under `vault/` in the Fulcra file library. The CLI handles synchronization automatically.
