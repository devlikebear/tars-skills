# Browser DevTools Plugin

Chrome DevTools MCP server for interactive browser automation with TARS.

## What it provides

- **29 browser tools** via [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp): navigation, clicking, form filling, screenshots, JavaScript execution, network inspection, performance profiling
- **Skill guide** for effective use of browser tools

## Requirements

- Node.js (npx available in PATH)
- Chrome/Chromium installed

## Installation

```bash
# Copy to your TARS plugins directory
cp -r plugins/browser-devtools ~/.tars/plugins/browser-devtools

# Or symlink
ln -s $(pwd)/plugins/browser-devtools ~/.tars/plugins/browser-devtools
```

## Configuration Variants

The default config auto-launches Chrome. To customize, edit `tars.plugin.json`:

**Headless mode:**
```json
"args": ["-y", "chrome-devtools-mcp@latest", "--headless"]
```

**Connect to existing Chrome** (start Chrome with `--remote-debugging-port=9222`):
```json
"args": ["-y", "chrome-devtools-mcp@latest", "--autoConnect"]
```

**Minimal tool set** (3 tools for basic browsing):
```json
"args": ["-y", "chrome-devtools-mcp@latest", "--slim"]
```
