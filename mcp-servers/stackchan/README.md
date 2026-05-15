# stackchan

Hosted MCP server for TARS that turns a [Stack-chan](https://github.com/stack-chan/stack-chan)
(スタックチャン) desktop robot into a physical ambient output channel for an
AI agent — facial expressions, head motion, speech, LEDs, camera, IR, and
built-in motion sequences.

Physical actions are exposed as **Tools**; live device state as **Resources**.

## Tools

| Tool | Arguments | Purpose |
| --- | --- | --- |
| `set_expression` | `emotion` (happy\|sad\|surprised\|angry\|sleepy\|neutral) | Change facial expression |
| `move_head` | `pan` (-165..165), `tilt` (0..85), `speed?` | Rotate head |
| `speak` | `text`, `voice?` | On-device TTS |
| `set_led` | `pattern`, `color` (hex) | 12 RGB LED ring |
| `capture_image` | — | Camera snapshot, returns a URI |
| `listen` | `duration_ms` (250..15000) | Mic capture → STT |
| `ir_send` | `protocol`, `code` | Send an IR remote code |
| `dance` | `pattern` | Play a built-in motion sequence |

> The vertical (tilt) servo is intentionally range-limited to `0..85°`.
> Driving it to a hard limit can stall and damage the servo.

## Resources

- `stackchan://status` — battery, RSSI, firmware, connection state
- `stackchan://camera/latest` — latest captured image handle
- `stackchan://sensors/imu` — accelerometer / gyroscope
- `stackchan://nfc/last_tag` — last NFC UID

## Bridge modes

- **mock** (default): no hardware required. All actions are simulated and
  device state is kept in memory. Use this to design and test the agent
  integration before any firmware work.
- **http**: set `STACKCHAN_BRIDGE_URL` to a self-hosted Stack-chan bridge.
  Tools `POST ${STACKCHAN_BRIDGE_URL}/command` with
  `{ "tool", "arguments" }`; resources
  `GET ${STACKCHAN_BRIDGE_URL}/resource?uri=<uri>`.

```bash
# mock (default)
node ${MCP_DIR}/server.cjs

# wired to a local bridge
STACKCHAN_BRIDGE_URL=http://localhost:8080 node ${MCP_DIR}/server.cjs
```

## Use in TARS

```bash
tars mcp install stackchan
```

Allow the launcher in your config:

```yaml
mcp_command_allowlist_json: ["node"]
```
