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

# Review and install a domain pack
tars pack install github-maintainer-pack
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
      "user_invocable": true,
      "quality": {
        "score": 85,
        "last_updated": "2026-05-01",
        "tests_passing": true,
        "required_tools": ["bash"],
        "permissions": ["filesystem"],
        "companion_cli": true,
        "install_count": 120
      }
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
  ],
  "packs": [
    {
      "name": "github-maintainer-pack",
      "description": "GitHub maintainer workflow bundle for log triage, issue filing, and PR/worktree operations.",
      "version": "0.1.0",
      "author": "devlikebear",
      "tags": ["github", "maintenance", "dogfooding"],
      "skills": ["github-ops", "log-watcher", "log-anomaly-detect"],
      "plugins": [],
      "mcp_servers": [],
      "quality": {
        "score": 86,
        "last_updated": "2026-05-01",
        "tests_passing": true,
        "required_tools": ["bash", "git", "gh"],
        "permissions": ["filesystem", "github", "shell", "docker"],
        "companion_cli": true
      }
    }
  ]
}
```

### Quality Metadata

Every installable registry entry may include a `quality` object. TARS renders
this metadata in the Extensions Hub before install:

- `score`: required when `quality` is present; integer from 0 to 100.
- `last_updated`: ISO date (`YYYY-MM-DD`) for the packaged entry metadata or files.
- `tests_passing`: whether the latest maintainer smoke/unit test pass is known.
- `required_tools`: local executables or CLIs the package expects.
- `permissions`: user-impacting capabilities such as `filesystem`, `github`,
  `network`, `browser`, or `mcp`.
- `companion_cli`: whether the skill ships or depends on a companion CLI/script.
- `install_count`: optional observed install count when available.

### Domain Packs

`packs` are reviewable bundles of existing skills, plugins, and MCP packages.
TARS prints the install plan before applying it, then installs each member
through the same sandbox checks as individual package installs.

## Contributing

1. Create `skills/<your-skill>/SKILL.md`
2. Or create `mcp-servers/<your-server>/tars.mcp.json` plus hosted runtime files
3. Or create a `packs` entry that references existing packages
4. Add an entry to `registry.json` with quality metadata
5. Open a PR

## OpenClaw Compatibility

TARS can also install skills from [ClawHub](https://clawhub.ai) via adapter. Use the `--source openclaw` flag:

```bash
tars skill search --source openclaw <query>
tars skill install --source openclaw <package-name>
```

## License

MIT
