---
name: browser-devtools
description: Guide for using Chrome DevTools MCP browser automation tools
user-invocable: false
recommended_tools:
  - navigate_page
  - take_snapshot
  - click
  - fill
  - take_screenshot
  - evaluate_script
---

# Browser DevTools

This plugin provides **Chrome DevTools MCP** for interactive browser control. The MCP server connects to a Chrome browser and exposes 29 tools across 6 categories.

## Connection Modes

1. **Auto-launch** (default) — MCP server starts a new Chrome instance automatically
2. **Auto-connect** (`--autoConnect`) — connects to an already running Chrome with remote debugging
3. **Headless** (`--headless`) — runs Chrome without a visible window

## Available Tools

### Navigation
- `navigate_page` — open a URL
- `new_page` / `close_page` — manage tabs
- `list_pages` / `select_page` — switch between tabs
- `wait_for` — wait for element, navigation, or timeout

### Input
- `click` — click an element
- `fill` / `fill_form` — type into inputs or fill entire forms
- `hover` — hover over elements
- `type_text` / `press_key` — keyboard input
- `drag` — drag and drop
- `upload_file` — file upload
- `handle_dialog` — accept/dismiss alerts

### Inspection
- `take_snapshot` — get page accessibility tree (preferred over screenshot for understanding page structure)
- `take_screenshot` — capture visible page as image
- `evaluate_script` — run JavaScript in page context

### Network & Performance
- `list_network_requests` / `get_network_request` — inspect API calls
- `performance_start_trace` / `performance_stop_trace` / `performance_analyze_insight` — profiling
- `take_memory_snapshot` — heap analysis

### Debugging
- `list_console_messages` / `get_console_message` — read console output
- `lighthouse_audit` — run Lighthouse audit

### Emulation
- `emulate` — set device/viewport
- `resize_page` — change viewport size

## Best Practices

- Use `take_snapshot` over `take_screenshot` when you need to understand page structure — it returns the accessibility tree which is more useful for automation decisions.
- Use `fill_form` to fill multiple fields at once instead of individual `fill` calls.
- Always `wait_for` an element before interacting with it on pages that load dynamically.
