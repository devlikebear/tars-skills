#!/usr/bin/env node

const fs = require("fs");

let buffer = Buffer.alloc(0);

function writeMessage(message) {
  const body = Buffer.from(JSON.stringify(message), "utf8");
  const header = Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, "utf8");
  fs.writeSync(process.stdout.fd, Buffer.concat([header, body]));
}

function toolDefinition() {
  return {
    name: "get_current_time",
    description: "Return the current local time, optionally formatted for a requested IANA timezone.",
    inputSchema: {
      type: "object",
      properties: {
        timezone: {
          type: "string",
          description: "Optional IANA timezone such as Asia/Seoul or UTC."
        }
      }
    }
  };
}

function formatCurrentTime(timezone) {
  const now = new Date();
  const zone = typeof timezone === "string" && timezone.trim() ? timezone.trim() : Intl.DateTimeFormat().resolvedOptions().timeZone;
  const formatter = new Intl.DateTimeFormat("en-CA", {
    dateStyle: "full",
    timeStyle: "long",
    timeZone: zone
  });
  return {
    zone,
    iso: now.toISOString(),
    display: formatter.format(now)
  };
}

function success(id, result) {
  writeMessage({
    jsonrpc: "2.0",
    id,
    result
  });
}

function failure(id, code, message) {
  writeMessage({
    jsonrpc: "2.0",
    id,
    error: {
      code,
      message
    }
  });
}

function handle(request) {
  const id = Object.prototype.hasOwnProperty.call(request, "id") ? request.id : null;
  switch (request.method) {
    case "initialize":
      success(id, {
        protocolVersion: "2024-11-05",
        serverInfo: {
          name: "safe-time",
          version: "0.1.0"
        },
        capabilities: {
          tools: {}
        }
      });
      return;
    case "notifications/initialized":
      return;
    case "tools/list":
      success(id, {
        tools: [toolDefinition()]
      });
      return;
    case "tools/call": {
      const params = request.params || {};
      if (params.name !== "get_current_time") {
        failure(id, -32601, `unknown tool: ${params.name}`);
        return;
      }
      try {
        const current = formatCurrentTime(params.arguments && params.arguments.timezone);
        success(id, {
          content: [
            {
              type: "text",
              text: `Current time (${current.zone}): ${current.display}\nISO: ${current.iso}`
            }
          ]
        });
      } catch (err) {
        failure(id, -32000, `time formatting failed: ${err.message}`);
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
    try {
      handle(JSON.parse(body));
    } catch (err) {
      failure(null, -32700, `parse error: ${err.message}`);
    }
  }
}

process.stdin.on("data", (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  consumeBuffer();
});
