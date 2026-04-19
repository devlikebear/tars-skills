---
name: log-watcher
description: "Collect recent logs from a Docker container or a local file. Emits a uniform JSON envelope so downstream skills can dedup and classify."
version: 0.1.0
user-invocable: true
recommended_tools:
  - bash
tags:
  - observability
  - logs
  - docker
---

# log-watcher

Uniform way to pull recent log lines. Phase A ships two sources: `docker` (container logs via the local Docker daemon) and `file` (tail a file on disk, optional grep filter).

Future sources (Sentry, Loki, OpenSearch, CloudWatch) will land as new subcommands on the same CLI or as separate skills — add them when a concrete scenario asks for it. Do not pre-abstract.

## When to invoke

- The user asks for "recent logs", "last N lines", "error logs" of a container or file.
- A downstream skill (e.g. `log-anomaly-detect`) needs a batch of recent log lines to classify.

## Usage

Run the companion CLI via the `bash` tool. The CLI lives alongside this file at `$SKILL_DIR/log_watcher.sh`.

```bash
# Docker container (required: --container)
bash "$SKILL_DIR/log_watcher.sh" docker --container <name> [--since 1h] [--tail 200]

# Local file
bash "$SKILL_DIR/log_watcher.sh" file --path /var/log/app.log [--tail 200] [--grep ERROR]
```

Default `--tail` is 200. Hard cap: `docker`=2000, `file`=5000 (to protect the chat context).

## Output

Stdout is a single JSON object:

```json
{
  "source": "docker" | "file",
  "target": "<container name or file path>",
  "lines": [
    { "ts": "2026-04-19T12:34:56Z", "level": "ERROR", "msg": "...", "raw": "<original line>" }
  ],
  "truncated": false,
  "line_count": 42
}
```

If the LLM needs structured parsing (ts/level/msg populated), the underlying log line must be JSON with `ts`, `level`, `msg` keys. Otherwise only `raw` is set and `ts`/`level`/`msg` are empty strings.

## Errors

Non-zero exit with a one-line stderr message in these cases:

- `docker` binary not on PATH
- Container not found / Docker daemon unreachable
- File does not exist / unreadable
- Invalid arguments (unknown subcommand, `--tail` out of range)

On error, stdout is still a valid JSON envelope with empty `lines` and an `error` field.

## Example

```
User: tars-examples-foo 컨테이너 최근 에러 로그 보여줘
→ Call: bash $SKILL_DIR/log_watcher.sh docker --container tars-examples-foo --tail 200
→ Parse JSON output, summarise error-level lines to the user.
```
