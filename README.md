# TARS Skill Hub

Public skill registry for [TARS](https://github.com/devlikebear/tars).

## Usage

```bash
# Search skills
tars skill search project

# Install a skill
tars skill install project-start

# List installed skills
tars skill list

# Update all skills
tars skill update

# Search trusted MCP packages
tars mcp search

# Install a hosted MCP server
tars mcp install safe-time
```

## Skill Format

Each skill lives in `skills/<name>/SKILL.md` with YAML frontmatter:

```yaml
---
name: my-skill
description: "What this skill does"
user-invocable: true
recommended_tools:
  - tool_name
---

# My Skill

Skill instructions in Markdown...
```

## Registry Format

`registry.json` indexes all available skills, plugins, and trusted MCP packages:

```json
{
  "version": 3,
  "skills": [
    {
      "name": "skill-name",
      "description": "...",
      "version": "0.6.0",
      "author": "username",
      "tags": ["tag1", "tag2"],
      "path": "skills/skill-name",
      "user_invocable": true
    }
  ],
  "mcp_servers": [
    {
      "name": "safe-time",
      "path": "mcp-servers/safe-time",
      "manifest": "tars.mcp.json",
      "files": [
        {
          "path": "tars.mcp.json",
          "sha256": "<sha256>"
        }
      ]
    }
  ]
}
```

## Contributing

1. Create `skills/<your-skill>/SKILL.md`
2. Or create `mcp-servers/<your-server>/tars.mcp.json` plus hosted runtime files
3. Add an entry to `registry.json`
4. Open a PR

## OpenClaw Compatibility

TARS can also install skills from [ClawHub](https://clawhub.ai) via adapter. Use the `--source openclaw` flag:

```bash
tars skill search --source openclaw <query>
tars skill install --source openclaw <package-name>
```

## License

MIT
