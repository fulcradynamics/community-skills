# Interacting with the Fulcra Vault via MCP

If you have the Fulcra MCP server connected, you can read from the vault directly through MCP filesystem tools.

Currently, MCP access to the Fulcra file library is typically read-only.
- Use the MCP `read_file` or equivalent capabilities to read `vault/index.md` or individual notes.
- If you need to make mutations (adding notes, updating logs), you must fall back to the native CLI/shell methods (see `fulcra-vault-cli.md`).

Always respect the structure and exclusions outlined in `vault/meta.json` when traversing via MCP.
