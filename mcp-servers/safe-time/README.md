# safe-time

Hosted MCP server for TARS that exposes one low-risk tool:

- `get_current_time`: returns the current time in the local timezone or a requested IANA timezone

This package is fully hosted in `tars-skills` and runs with:

```bash
node ${MCP_DIR}/server.js
```

To use it in TARS:

```bash
tars mcp install safe-time
```

And allow the launcher in your config:

```yaml
mcp_command_allowlist_json: ["node"]
```
