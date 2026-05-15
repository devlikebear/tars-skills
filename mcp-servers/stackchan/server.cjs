#!/usr/bin/env node

// stackchan-mcp: control surface for the Stack-chan (スタックチャン) desktop
// robot, exposed to MCP clients (Claude Desktop / Claude Code / TARS).
//
// Hardware actions are Tools; live device state is exposed as Resources.
//
// Bridge modes:
//   - mock (default): keeps in-memory state, simulates every action.
//   - http: set STACKCHAN_BRIDGE_URL to forward commands to a local
//     Stack-chan bridge (the self-hosted Go/WebSocket backend). Tools
//     POST to `${STACKCHAN_BRIDGE_URL}/command`, resources GET
//     `${STACKCHAN_BRIDGE_URL}/resource?uri=<uri>`.

const fs = require("fs");

const SERVER_NAME = "stackchan";
const SERVER_VERSION = "0.1.0";

const BRIDGE_URL = (process.env.STACKCHAN_BRIDGE_URL || "").replace(/\/+$/, "");
const BRIDGE_MODE = BRIDGE_URL ? "http" : "mock";

const EMOTIONS = ["happy", "sad", "surprised", "angry", "sleepy", "neutral"];

const PAN_MIN = -165;
const PAN_MAX = 165;
const TILT_MIN = 0;
const TILT_MAX = 85;

let buffer = Buffer.alloc(0);
let processing = Promise.resolve();

// In-memory device state for mock mode.
const mockState = {
  expression: "neutral",
  head: { pan: 0, tilt: 45 },
  lastSpoken: null,
  led: { pattern: "off", color: "#000000" },
  status: {
    connected: true,
    battery_pct: 87,
    rssi_dbm: -52,
    firmware: "esp-idf-5.5.1-mock",
    bridge_mode: BRIDGE_MODE
  },
  imu: { ax: 0.01, ay: -0.02, az: 0.98, gx: 0.0, gy: 0.0, gz: 0.0 },
  nfc: { uid: null, read_at: null }
};

function writeMessage(message) {
  const body = Buffer.from(JSON.stringify(message), "utf8");
  const header = Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, "utf8");
  fs.writeSync(process.stdout.fd, Buffer.concat([header, body]));
}

function success(id, result) {
  writeMessage({ jsonrpc: "2.0", id, result });
}

function failure(id, code, message) {
  writeMessage({ jsonrpc: "2.0", id, error: { code, message } });
}

function textResult(text) {
  return { content: [{ type: "text", text }] };
}

function isHexColor(value) {
  return typeof value === "string" && /^#?[0-9a-fA-F]{6}$/.test(value);
}

function normalizeHex(value) {
  return value.startsWith("#") ? value.toLowerCase() : `#${value.toLowerCase()}`;
}

function toolDefinitions() {
  return [
    {
      name: "set_expression",
      description: "Change Stack-chan's facial expression.",
      inputSchema: {
        type: "object",
        properties: {
          emotion: {
            type: "string",
            enum: EMOTIONS,
            description: "One of: " + EMOTIONS.join(", ")
          }
        },
        required: ["emotion"]
      }
    },
    {
      name: "move_head",
      description:
        "Rotate the head. pan is horizontal (-165..165 deg), tilt is vertical (0..85 deg). The vertical servo is range-limited to avoid stalling.",
      inputSchema: {
        type: "object",
        properties: {
          pan: { type: "number", description: `Horizontal angle ${PAN_MIN}..${PAN_MAX}` },
          tilt: { type: "number", description: `Vertical angle ${TILT_MIN}..${TILT_MAX}` },
          speed: { type: "number", description: "Optional 1..100 movement speed" }
        },
        required: ["pan", "tilt"]
      }
    },
    {
      name: "speak",
      description: "Speak text aloud via on-device TTS.",
      inputSchema: {
        type: "object",
        properties: {
          text: { type: "string", description: "Text to speak" },
          voice: { type: "string", description: "Optional voice id" }
        },
        required: ["text"]
      }
    },
    {
      name: "set_led",
      description: "Set the 12 RGB LED ring to a named pattern and color.",
      inputSchema: {
        type: "object",
        properties: {
          pattern: {
            type: "string",
            description: "Pattern name, e.g. solid, blink, breathe, rainbow, off"
          },
          color: { type: "string", description: "Hex color such as #ff0000" }
        },
        required: ["pattern", "color"]
      }
    },
    {
      name: "capture_image",
      description: "Capture a still image from the camera. Returns an image URI/handle.",
      inputSchema: { type: "object", properties: {} }
    },
    {
      name: "listen",
      description: "Capture microphone audio for a duration and return recognized text (STT).",
      inputSchema: {
        type: "object",
        properties: {
          duration_ms: {
            type: "integer",
            description: "Capture duration in milliseconds (250..15000)"
          }
        },
        required: ["duration_ms"]
      }
    },
    {
      name: "ir_send",
      description: "Send an infrared remote code (e.g. control an AC or TV).",
      inputSchema: {
        type: "object",
        properties: {
          protocol: { type: "string", description: "IR protocol, e.g. NEC, SONY, RC5" },
          code: { type: "string", description: "Hex code payload" }
        },
        required: ["protocol", "code"]
      }
    },
    {
      name: "dance",
      description: "Play a built-in motion sequence.",
      inputSchema: {
        type: "object",
        properties: {
          pattern: { type: "string", description: "Sequence name, e.g. wiggle, nod, spin, clap" }
        },
        required: ["pattern"]
      }
    }
  ];
}

function resourceDefinitions() {
  return [
    {
      uri: "stackchan://status",
      name: "Device status",
      description: "Battery, RSSI, firmware version, connection state.",
      mimeType: "application/json"
    },
    {
      uri: "stackchan://camera/latest",
      name: "Latest camera capture",
      description: "Metadata/handle for the most recent captured image.",
      mimeType: "application/json"
    },
    {
      uri: "stackchan://sensors/imu",
      name: "IMU sensors",
      description: "Accelerometer / gyroscope readings.",
      mimeType: "application/json"
    },
    {
      uri: "stackchan://nfc/last_tag",
      name: "Last NFC tag",
      description: "UID of the most recently read NFC tag.",
      mimeType: "application/json"
    }
  ];
}

async function bridgeCommand(tool, args) {
  if (BRIDGE_MODE === "mock") {
    return mockCommand(tool, args);
  }
  const res = await fetch(`${BRIDGE_URL}/command`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tool, arguments: args })
  });
  if (!res.ok) {
    throw new Error(`bridge command failed: HTTP ${res.status}`);
  }
  const data = await res.json();
  return typeof data === "string" ? data : JSON.stringify(data);
}

async function bridgeResource(uri) {
  if (BRIDGE_MODE === "mock") {
    return mockResource(uri);
  }
  const res = await fetch(`${BRIDGE_URL}/resource?uri=${encodeURIComponent(uri)}`);
  if (!res.ok) {
    throw new Error(`bridge resource failed: HTTP ${res.status}`);
  }
  return await res.text();
}

function mockCommand(tool, args) {
  switch (tool) {
    case "set_expression":
      mockState.expression = args.emotion;
      return `expression set to ${args.emotion}`;
    case "move_head":
      mockState.head = { pan: args.pan, tilt: args.tilt };
      return `head moved to pan=${args.pan} tilt=${args.tilt}` +
        (args.speed != null ? ` speed=${args.speed}` : "");
    case "speak":
      mockState.lastSpoken = args.text;
      return `spoke: "${args.text}"` + (args.voice ? ` (voice=${args.voice})` : "");
    case "set_led":
      mockState.led = { pattern: args.pattern, color: normalizeHex(args.color) };
      return `LED set to ${args.pattern} ${mockState.led.color}`;
    case "capture_image": {
      const uri = `stackchan://camera/${Date.now()}.jpg`;
      mockState._lastImage = uri;
      return `captured ${uri}`;
    }
    case "listen":
      return `(mock) heard nothing during ${args.duration_ms}ms capture`;
    case "ir_send":
      return `IR sent: ${args.protocol} ${args.code}`;
    case "dance":
      return `playing motion sequence: ${args.pattern}`;
    default:
      throw new Error(`unknown tool: ${tool}`);
  }
}

function mockResource(uri) {
  switch (uri) {
    case "stackchan://status":
      return JSON.stringify(mockState.status, null, 2);
    case "stackchan://camera/latest":
      return JSON.stringify(
        { latest: mockState._lastImage || null, expression: mockState.expression },
        null,
        2
      );
    case "stackchan://sensors/imu":
      return JSON.stringify(mockState.imu, null, 2);
    case "stackchan://nfc/last_tag":
      return JSON.stringify(mockState.nfc, null, 2);
    default:
      throw new Error(`unknown resource: ${uri}`);
  }
}

function validateArgs(tool, args) {
  switch (tool) {
    case "set_expression":
      if (!EMOTIONS.includes(args.emotion)) {
        throw new Error(`emotion must be one of: ${EMOTIONS.join(", ")}`);
      }
      break;
    case "move_head": {
      const { pan, tilt } = args;
      if (typeof pan !== "number" || pan < PAN_MIN || pan > PAN_MAX) {
        throw new Error(`pan must be a number in ${PAN_MIN}..${PAN_MAX}`);
      }
      if (typeof tilt !== "number" || tilt < TILT_MIN || tilt > TILT_MAX) {
        throw new Error(
          `tilt must be a number in ${TILT_MIN}..${TILT_MAX} (vertical servo is range-limited)`
        );
      }
      if (args.speed != null && (typeof args.speed !== "number" || args.speed < 1 || args.speed > 100)) {
        throw new Error("speed must be a number in 1..100");
      }
      break;
    }
    case "speak":
      if (typeof args.text !== "string" || !args.text.trim()) {
        throw new Error("text is required");
      }
      break;
    case "set_led":
      if (typeof args.pattern !== "string" || !args.pattern.trim()) {
        throw new Error("pattern is required");
      }
      if (!isHexColor(args.color)) {
        throw new Error("color must be a 6-digit hex string such as #ff0000");
      }
      break;
    case "listen": {
      const d = args.duration_ms;
      if (!Number.isInteger(d) || d < 250 || d > 15000) {
        throw new Error("duration_ms must be an integer in 250..15000");
      }
      break;
    }
    case "ir_send":
      if (typeof args.protocol !== "string" || !args.protocol.trim()) {
        throw new Error("protocol is required");
      }
      if (typeof args.code !== "string" || !args.code.trim()) {
        throw new Error("code is required");
      }
      break;
    case "dance":
      if (typeof args.pattern !== "string" || !args.pattern.trim()) {
        throw new Error("pattern is required");
      }
      break;
    default:
      throw new Error(`unknown tool: ${tool}`);
  }
}

async function handle(request) {
  const id = Object.prototype.hasOwnProperty.call(request, "id") ? request.id : null;
  switch (request.method) {
    case "initialize":
      success(id, {
        protocolVersion: "2024-11-05",
        serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
        capabilities: { tools: {}, resources: {} }
      });
      return;
    case "notifications/initialized":
      return;
    case "tools/list":
      success(id, { tools: toolDefinitions() });
      return;
    case "resources/list":
      success(id, { resources: resourceDefinitions() });
      return;
    case "resources/read": {
      const uri = request.params && request.params.uri;
      try {
        const text = await bridgeResource(uri);
        success(id, {
          contents: [{ uri, mimeType: "application/json", text }]
        });
      } catch (err) {
        failure(id, -32000, err.message);
      }
      return;
    }
    case "tools/call": {
      const params = request.params || {};
      const name = params.name;
      const args = params.arguments || {};
      const known = toolDefinitions().some((t) => t.name === name);
      if (!known) {
        failure(id, -32601, `unknown tool: ${name}`);
        return;
      }
      try {
        validateArgs(name, args);
        const message = await bridgeCommand(name, args);
        success(id, textResult(`[${BRIDGE_MODE}] ${message}`));
      } catch (err) {
        success(id, { content: [{ type: "text", text: `error: ${err.message}` }], isError: true });
      }
      return;
    }
    default:
      if (id !== null) {
        failure(id, -32601, `method not found: ${request.method}`);
      }
  }
}

function consumeBuffer() {
  while (true) {
    const headerEnd = buffer.indexOf("\r\n\r\n");
    if (headerEnd === -1) {
      return;
    }
    const headerText = buffer.slice(0, headerEnd).toString("utf8");
    const match = headerText.match(/Content-Length:\s*(\d+)/i);
    if (!match) {
      buffer = Buffer.alloc(0);
      return;
    }
    const contentLength = Number(match[1]);
    const messageEnd = headerEnd + 4 + contentLength;
    if (buffer.length < messageEnd) {
      return;
    }
    const body = buffer.slice(headerEnd + 4, messageEnd).toString("utf8");
    buffer = buffer.slice(messageEnd);
    let parsed;
    try {
      parsed = JSON.parse(body);
    } catch (err) {
      failure(null, -32700, `parse error: ${err.message}`);
      continue;
    }
    // Serialize handlers so async bridge calls reply in order.
    processing = processing.then(() => handle(parsed)).catch((err) => {
      failure(null, -32000, `internal error: ${err.message}`);
    });
  }
}

process.stdin.on("data", (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  consumeBuffer();
});
