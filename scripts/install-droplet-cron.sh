#!/usr/bin/env bash
# Install POL-003 dashboard-live cron on the droplet (every 15 min).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LINE="*/15 * * * * cd $ROOT && bash scripts/sync-dashboard-live.sh >> logs/sync-dashboard-live.log 2>&1"
(crontab -l 2>/dev/null | grep -v sync-dashboard-live || true; echo "$LINE") | crontab -
echo "Installed: $LINE"