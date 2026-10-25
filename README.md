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

# Install the Stack-chan robot skill
# (the MCP server is external: `brew install devlikebear/tap/tars-stackchan` —
#  the skill guides setup; this repo ships no Stack-chan server)
tars skill install tars-stackchan

# Review and install a domain pack
tars pack install github-maintainer-pack

# Search and install focus templates (pipeline shapes for TARS focus mode)
tars template search
tars template install hotfix
tars template update
```

The console offers the same under **Extensions → Hub**: skills, MCP servers,
plugins, focus templates and packs.

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

### Focus Templates

A focus template is the shape of a TARS focus pipeline: its stages, the
behaviour each runs with (`plan`, `build`, `review`, `pr`, `pr_review`,
`merge`) and what each is told to do. It is text only — no commands run at
install. Each lives in `focus-templates/<id>/template.yaml`, the same YAML
TARS writes to `<workspace>/focus-templates/`, and its registry entry name is
the template id:

```json
"focus_templates": [
  {
    "name": "hotfix",
    "description": "...",
    "version": "0.1.0",
    "author": "devlikebear",
    "tags": ["focus-template", "development"],
    "path": "focus-templates/hotfix",
    "files": [{ "path": "template.yaml", "sha256": "<sha256>" }]
  }
]
```

TARS installs a template into the workspace's `focus-templates/` and never
replaces a local template of the same id. An update skips a template the
user has edited since installing it. Packs may list `focus_templates` too.

To share a template you made in TARS (the console's Focus templates page has
a **Share** button that prints these steps):

```bash
python3 scripts/registry.py add-focus-template ~/.tars/workspace/focus-templates/<id>.yaml
git switch -c add-<id>-focus-template
git add -A && git commit -m "Add <id> focus template"
gh pr create --fill
```

### Domain Packs

`packs` are reviewable bundles of existing skills, plugins, and MCP packages.
TARS prints the install plan before applying it, then installs each member
through the same sandbox checks as individual package installs.

## Contributing

1. Create `skills/<your-skill>/SKILL.md`
2. Or create `mcp-servers/<your-server>/tars.mcp.json` plus hosted runtime files
3. Or add a focus template with `python3 scripts/registry.py add-focus-template <file>`
4. Or create a `packs` entry that references existing packages
5. Add an entry to `registry.json` with quality metadata
6. Run `python3 scripts/registry.py sync` to write every file's sha256 —
   TARS refuses a file whose checksum does not match — and
   `python3 scripts/registry.py check` (CI runs it with PyYAML for full
   focus template validation)
7. Open a PR

## OpenClaw Compatibility

TARS can also install skills from [ClawHub](https://clawhub.ai) via adapter. Use the `--source openclaw` flag:

```bash
tars skill search --source openclaw <query>
tars skill install --source openclaw <package-name>
```

## License

MIT
