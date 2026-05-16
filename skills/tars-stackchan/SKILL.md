---
name: tars-stackchan
description: "Drive an M5Stack Stack-chan desktop robot as a living physical presence for the agent — express the agent's emotion on its face, speak notifications out loud, and react with head/motion/LED at the right moments. Use when the agent should embody a feeling or get the user's attention physically, or when the user asks Stack-chan to smile/nod/speak/light up or check robot status."
version: 0.2.0
user-invocable: true
recommended_tools:
  - stackchan_get_status
  - stackchan_set_expression
  - stackchan_move_head
  - stackchan_set_led
  - stackchan_run_motion
  - stackchan_speak
tags:
  - stackchan
  - robot
  - m5stack
  - hardware
  - mcp
  - embodiment
---

# tars-stackchan

Stack-chan (M5Stack K151 / ESP32-S3) is a small desktop robot with a face,
a pan/tilt head, RGB LEDs, canned motions, and speech. This skill is the
**agent-facing playbook** for using it as a *physical body* for TARS / Claude
Code: a way to show what the agent is feeling and to get the user's attention
in the real world, not just in the terminal.

The skill does **not** contain or build an MCP server. It drives the
**official `devlikebear/tars-stackchan` MCP server** (installed via Homebrew —
see Setup). Do not reimplement or vendor a server; if the tools are missing,
fix the install instead.

## Setup (one-time)

The MCP server is a single Homebrew binary. Guide the user through these steps;
do not run destructive or account-level commands on their behalf without asking.

1. Install the server:

   ```bash
   brew install devlikebear/tap/tars-stackchan
   ```

2. Register it with the client at **user scope** (available in every project):

   ```bash
   export TARS_STACKCHAN_TOKEN="<token flashed into the Stack-chan firmware MOD>"
   claude mcp add tars-stackchan -s user -t stdio \
     -e TARS_STACKCHAN_BRIDGE=http \
     -e TARS_STACKCHAN_BASE_URL=http://<device-ip> \
     -e TARS_STACKCHAN_TOKEN="$TARS_STACKCHAN_TOKEN" \
     -- "$(command -v tars-stackchan-mcp)"
   ```

   `tars-stackchan-mcp install --target claude-code` automates this, and
   `--target tars` / `--target claude-desktop` emit config for those clients.

3. Sanity-check before the first actuation:

   ```bash
   TARS_STACKCHAN_BRIDGE=http TARS_STACKCHAN_BASE_URL=http://<device-ip> \
   TARS_STACKCHAN_TOKEN="$TARS_STACKCHAN_TOKEN" tars-stackchan-mcp doctor
   ```

### Connection pitfalls (read before debugging)

- **No mDNS.** `http://stackchan.local` often does not resolve. Use the device
  **IP** from the firmware boot log or `GET /v1/status`. The IP is DHCP-assigned
  and can change between boots — if calls suddenly fail, re-check the IP and
  re-register.
- **Mock vs real.** With no `TARS_STACKCHAN_BRIDGE=http`, the server runs a
  **mock** bridge: tools "succeed" but nothing physically moves. `doctor` warns
  about this. If `stackchan_get_status` reports a mock/`-mock` firmware, tell
  the user no real movement happened and how to switch to `http`.
- **Token is firmware-flashed and unrecoverable.** `GET /v1/status` is
  unauthenticated, so status can read *connected* while every actuation fails
  with HTTP 401 if `TARS_STACKCHAN_TOKEN` ≠ the token flashed into the bridge
  MOD. There is no recovery except re-flashing the MOD with a known token.
- Always call `stackchan_get_status` once before the first actuation in a
  session. If it errors, **stop and report** — do not retry blindly.

## Tools (verified contract)

| Tool | Purpose | Args |
|------|---------|------|
| `stackchan_get_status` | Connection, firmware, bridge mode, capabilities | none |
| `stackchan_set_expression` | Face emotion | **`emotion`** ∈ `neutral` `happy` `sad` `surprised` `angry` `sleepy` `blink` |
| `stackchan_move_head` | Pan/tilt head | **`pan_deg`**, **`tilt_deg`**, **`speed`** (all numbers, required) |
| `stackchan_set_led` | RGB LED ring | **`pattern`** ∈ `solid` `blink` `pulse` `off`; **`color`** hex `#rrggbb`; **`brightness`** 0.0–1.0 |
| `stackchan_run_motion` | Named canned motion | **`name`** (string, e.g. `nod`) |
| `stackchan_speak` | Speak text aloud | **`text`**; optional **`volume`** 0.0–1.0 |

### Safety contract

- `tilt_deg` is **clamped by the firmware** (roughly `5..85`). A request of `0`
  comes back as `~5`. Never assume an out-of-range tilt took effect — trust the
  `state` echoed in the tool result, not your input.
- `pan_deg` is **not** clamped (K151 X is continuous). Keep to ~`-90..90`
  unless the user explicitly wants a full sweep.
- `speed` is 0.1–1.0; stay conservative (≤0.5) unless asked for energetic.
- `color` must match `^#[0-9a-fA-F]{6}$`; map named colors yourself
  (red→`#ff0000`, warm white→`#ffd9a0`, calm green→`#00cc66`).
- `volume` defaults low for close-range desks; only raise if asked. Keep
  `text` short (a sentence or two) — this is a notifier, not a TTS reader.
- `run_motion` `name` is firmware-defined. `nod` is known-good; for others,
  if the result is an error, fall back to `nod` or an expression and say so.

## Use it as a living presence (the point of this skill)

Stack-chan is most valuable when the agent uses it **proactively and briefly**
to externalize its own state — not only when explicitly told "make it nod".
Treat it like body language: small, well-timed, never spammy.

> **It cannot see.** The firmware exposes only expression/head/LED/motion/
> speech — there is **no camera or microphone tool here**. Any awareness of the
> user (presence, mood, what they're doing) comes from the *host agent's own*
> context/perception, with the user's knowledge — never frame this as covertly
> watching the user. Stack-chan is the agent's *output/body*, not its eyes.

Good moments to embody, and a fitting reaction:

- **Needs the user's attention** (long task done, input required, approval
  gate, build finished): `stackchan_speak` a one-line summary + a matching
  expression + a `nod` / brief LED `pulse`. This is the headline feature —
  physical notification beats a buried terminal line.
- **The agent succeeded / is pleased**: `happy` + green `pulse` + `nod`.
- **Something failed / bad news**: `sad` + red `blink`. Speak the failure in
  one sentence if it needs action.
- **Working / thinking** (start of a long step): brief `surprised`→`neutral`,
  or a slow amber `pulse`, so the user can glance over and see it's busy.
- **Idle / done for now**: `sleepy` + LEDs `off` (or very dim). Wake to
  `neutral` when activity resumes.
- **Greeting / session start**: `neutral` + a single `nod`, optionally a short
  spoken hello if the user likes that.
- **Acknowledging the user** ("look at me", or the agent wants to signal it
  heard them): `stackchan_move_head pan_deg=0 tilt_deg=45 speed=0.4` to face
  forward + `neutral`.

Pick the **smallest sufficient** sequence — usually expression + one of
{motion | LED | one short speech}. Do not chain many micro head moves. Match
intensity to the moment (a minor info ping ≠ a full dance).

## Translating explicit requests

- "react happy / celebrate" → `set_expression happy` + `run_motion nod` (or a
  `dance` motion if firmware supports it) + `set_led #00cc66 pulse 0.4`.
- "tell me / say X" → `speak text="X"` (trim long text, say you trimmed it).
- "bad news / it failed" → `set_expression sad` + `set_led #ff0000 blink 0.5`.
- "go idle / sleep" → `set_expression sleepy` + `set_led #000000 off 0`.
- "wake up / pay attention" → `set_expression neutral` + `run_motion nod`.
- "look at me / center" → `move_head pan_deg=0 tilt_deg=45 speed=0.4`.
- "blink the lights <color>" → `set_led <hex> blink 0.5`.

## Output

After a sequence, report what was sent and the **echoed** state in one line,
and whether it was real or mock:

```
Stack-chan: expression=happy, motion=nod, LED=#00cc66/pulse — bridge=http, connected
```

If `bridge=mock`, add one reminder that nothing physically moved and how to
switch to `http`. Do not poll status in a loop.

## Failure handling

- Any tool returns an error → surface the message **verbatim**, name the tool
  that failed, and **stop the sequence** (don't keep queuing onto a broken
  bridge). Retry at most once.
- `get_status` shows disconnected / HTTP error → most likely the device IP
  changed, Wi-Fi dropped, or the token doesn't match the firmware. Point at
  `TARS_STACKCHAN_BASE_URL` / `TARS_STACKCHAN_TOKEN` and the doctor hints; do
  not loop.
- HTTP 401 on actuation while status is fine → token mismatch with the flashed
  firmware MOD. Tell the user it must be re-synced (re-flash MOD with a known
  token); the skill cannot recover it.
- Unknown emotion/motion/color from the user → map to the nearest supported
  value and say what you substituted, or ask if genuinely ambiguous.

## Example

```
User: 빌드 깨졌어. 스택짱한테 알려줘
→ stackchan_set_expression { "emotion": "sad" }
→ stackchan_set_led { "pattern": "blink", "color": "#ff0000", "brightness": 0.5 }
→ stackchan_speak { "text": "빌드가 실패했어요. 로그를 확인해 주세요." }
→ stackchan_get_status
→ "Stack-chan: 표정=sad, LED=#ff0000/blink, 음성 알림 전송 (bridge=http, connected)."
```
