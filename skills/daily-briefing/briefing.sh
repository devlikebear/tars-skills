#!/bin/bash
# Daily briefing data collector
# This script collects system info as a demo of companion file support.

echo "=== Daily Briefing ==="
echo "Date: $(date '+%Y-%m-%d %H:%M')"
echo ""
echo "## System"
echo "- Hostname: $(hostname)"
echo "- Uptime: $(uptime | sed 's/.*up /up /' | sed 's/,.*//')"
echo ""
echo "## Disk Usage"
df -h / | tail -1 | awk '{printf "- Used: %s / %s (%s)\n", $3, $2, $5}'
echo ""
echo "## Recent Git Activity"
if git rev-parse --is-inside-work-tree &>/dev/null; then
    git log --oneline -5 2>/dev/null || echo "- No git history"
else
    echo "- Not in a git repository"
fi
echo ""
echo "=== End Briefing ==="
