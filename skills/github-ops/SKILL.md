---
name: github-ops
description: "Thin wrapper over gh CLI + git worktree for issue search/create/comment, draft PRs, and per-branch worktree lifecycle."
version: 0.1.0
user-invocable: true
recommended_tools:
  - bash
tags:
  - github
  - gh
  - issues
  - pr
  - worktree
---

# github-ops

Uniform entry point for everyday GitHub operations in dogfooding workflows:

- Search / create / comment on issues on a given repo
- Open draft PRs
- Set up and clean per-branch git worktrees for isolated fix sessions

This skill **wraps the user's existing `gh` auth** — the CLI assumes `gh auth status` already works in the environment TARS runs in. It does not manage tokens.

## When to invoke

- Another skill (e.g. `log-anomaly-detect`, `fix-and-pr`) needs to create an issue or PR.
- The user asks to "list open issues", "file an issue", "comment on #N", "open a draft PR", "prepare a worktree for a fix".

## Usage

```bash
# Search issues
bash "$SKILL_DIR/github_ops.sh" issue-search --repo devlikebear/tars-examples-foo [--query "boom"] [--state open|closed|all] [--limit 20]

# Create issue
bash "$SKILL_DIR/github_ops.sh" issue-create --repo OWNER/NAME --title "..." --body "..." [--label bug --label auto]

# Comment on issue
bash "$SKILL_DIR/github_ops.sh" issue-comment --repo OWNER/NAME --issue 42 --body "..."

# Open draft PR
bash "$SKILL_DIR/github_ops.sh" pr-draft --repo OWNER/NAME --head feat/foo [--base main] --title "..." --body "..."

# Worktree lifecycle (local repo on disk)
bash "$SKILL_DIR/github_ops.sh" worktree-setup   --repo-path /abs/path/to/repo --branch fix/bug-123 [--base main] [--slug foo]
bash "$SKILL_DIR/github_ops.sh" worktree-cleanup --repo-path /abs/path/to/repo --branch fix/bug-123 [--slug foo]
```

Worktrees are placed under `$TARS_WORKSPACE/managed-repos/<slug>/<branch>/` by default (or `$PWD/workspace/managed-repos/...` if `TARS_WORKSPACE` is unset).

## Output

Stdout is always a single JSON object. Shape depends on the subcommand:

- `issue-search` → `{ok, repo, state, items:[{number,title,state,labels,created_at,body}]}`
- `issue-create` → `{ok, repo, number, url}`
- `issue-comment` → `{ok, repo, issue, url}`
- `pr-draft` → `{ok, repo, number, url}`
- `worktree-setup` → `{ok, repo_path, branch, base, worktree_path}`
- `worktree-cleanup` → `{ok, repo_path, branch, worktree_path, removed}`

On failure: `{ok:false, error:"..."}` and a non-zero exit code.

## Preconditions

- `gh` CLI must be installed. `gh auth status` must succeed (for any gh subcommand).
- `git` must be installed (for worktree subcommands).
- For `worktree-setup`, `--repo-path` must be an existing git working tree.

## Input validation

- `repo` must match `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`.
- `branch` and `slug` must match `^[A-Za-z0-9_./-]+$` and have no shell metacharacters.
- `issue_number` and `--limit` must be positive integers.

Invalid input → exit 2 with a one-line stderr message.

## Example

```
User: devlikebear/tars-examples-foo 리포에 'boom' 관련 이슈 있는지 봐줘
→ bash $SKILL_DIR/github_ops.sh issue-search --repo devlikebear/tars-examples-foo --query boom
→ Parse items, summarise open matches.
```
