---
name: desk-ops
description: "Look after the computer TARS runs on: disk, memory, processes, launchd/cron jobs, pending updates and security settings, read through a read-only CLI that prints JSON. Changes happen only after the developer approves them. Pairs with the desk_ops focus template for remote care from the phone."
version: 0.1.0
user-invocable: true
recommended_tools:
  - bash
tags:
  - system
  - maintenance
  - security
  - ops
---

# desk-ops

Care for the desk TARS runs on, from the desk or from the TARS Remote app.
A companion script, `deskops.py`, ships next to this file and **only reads**.
Every change (killing a process, unloading a job, deleting files, installing
an update, changing a setting) is a command you run yourself, after the
developer approved it.

The script's path is this file's folder — for a hub install,
`<workspace>/skills/desk-ops/deskops.py`. Use the absolute path, and call it
with `python3` (standard library only, Python 3.9+). macOS is the main
target; Linux gets the same shape where a fact has an obvious source.

## When to invoke

- "How is the desk doing?", "why is it slow?", "is the disk full?"
- "What runs in the background / at login / on a schedule?"
- "Are there updates?", "is this machine set up safely?"
- A `desk_ops` focus pipeline (plan → apply → confirm) — see below.

## Reading

```bash
python3 <dir>/deskops.py snapshot                    # OS, uptime, load, memory, volumes, top processes
python3 <dir>/deskops.py disk --path ~ --top 15      # largest folders and files under a path
python3 <dir>/deskops.py procs --sort mem --top 20   # processes by CPU or memory
python3 <dir>/deskops.py jobs                        # launchd plists, crontab, TARS cron
python3 <dir>/deskops.py updates                     # macOS, Homebrew and TARS updates (can take minutes)
python3 <dir>/deskops.py security                    # firewall, FileVault, SIP, Gatekeeper, listening ports + findings
```

Each prints one JSON object: `{"ok": true, "platform": ..., "<command>": {...}, "errors": [...]}`.
`errors` lists facts that could not be read (a missing tool, a timeout, no
permission) — say which, do not guess them.

What the script never prints: command-line arguments of processes, launchd
`ProgramArguments` after the program, `EnvironmentVariables`, crontab command
lines. They are where tokens end up. Do not go and read them yourself unless
the developer asks about that one job, and never repeat a secret you find.

`security.findings` come from fixed rules (FileVault off → high, firewall
off → medium, ssh/screen sharing/file sharing reachable from the network →
medium, any other port reachable from the network → info). They are facts,
not verdicts: screen sharing may be on on purpose. Ask before calling it a
problem.

`jobs.tars_cron` needs `TARS_API_TOKEN` in the environment; without it the
error says 401 and the rest of the output is still good.

## Checking (for verify commands)

```bash
python3 <dir>/deskops.py check <name> [options]   # exit 0 pass, 1 fail, 2 could not tell
```

| Check | Passes when |
|---|---|
| `disk-free --path / --min-gb 30` | at least that much space is free |
| `process-absent --name Dropbox` / `process-present --name …` | no / some process has exactly that name |
| `port-closed --port 5900 [--exposed-only]` / `port-open …` | nothing listens on the port (with `--exposed-only`: nothing reachable from the network) |
| `job-absent --label com.example.agent` / `job-loaded --label …` | no plist and not loaded / loaded in the user's domain (macOS) |
| `path-absent --path ~/Downloads/big.iso` | the path is gone |
| `firewall-on`, `filevault-on` | the setting is on |
| `brew-current [--name git]` | Homebrew has nothing (or that package is not) outdated |

Exit 2 means the fact could not be read — that is a failed verification, not
a pass.

## Changing — the rules

1. **Propose before you change.** Name the exact command, what it affects, how
   to undo it, and the risk. Wait for approval. In a focus pipeline the plan
   gate (G1) is that approval; nothing outside the approved commands.
2. **Never `sudo`, never type a password.** Anything that needs one — a macOS
   update, a firewall change, a system daemon — is for the developer at the
   desk: give them the command and say why it needs them.
3. **Restarts are for the desk.** After a restart with FileVault on, the
   machine waits at the login window, Tailscale is not up, and the phone
   cannot reach it until someone logs in. Never restart, log out or shut down
   from a remote session.
4. **Prefer the reversible step.** Move to the Trash (`mv … ~/.Trash/`) rather
   than `rm`; `launchctl bootout` a job rather than deleting its plist; quit an
   app (`osascript -e 'quit app "X"'`) before `kill`, and `kill` before
   `kill -9`.
5. **Do not touch** TARS itself (its server, LaunchAgent and workspace),
   Tailscale, the `claude`/`gh` CLIs or anything the phone needs to reach the
   desk — that would cut the session you are working in.
6. **Write it down.** In a pipeline, log each change to
   `ops-log/<YYYY-MM-DD>-<slug>.md` in the working folder: the command, its
   trimmed output, and how to undo it. Never write secrets there.

## The desk_ops focus template

`tars template install desk_ops` adds a pipeline for this skill:

1. **Inspect and propose** (plan) — reads the facts, changes nothing, and
   proposes one task per change with `deskops.py check …` lines as the
   verification commands.
2. **Apply** (build) — runs exactly the approved commands, logging each.
3. **Confirm** (review) — reads the facts again, reports side effects as
   findings, and finishes the report.

Start it from the phone in a registered folder (an `ops` folder of its own is
a good choice: the reports collect there). Do not run it in **goal mode**:
goal mode approves the plan by itself, and the plan is where the developer
says yes to each change.
