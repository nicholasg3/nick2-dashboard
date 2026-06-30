#!/usr/bin/env bash
# Refresh bus-live.json from droplet agent-bus and push to GitHub Pages source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export AGENT_BUS_DB="${AGENT_BUS_DB:-$HOME/ai-agents-workspace/agent-bus/jobs.sqlite}"
python3 scripts/export_bus_live.py
git add reports/bus-live.json
if git diff --staged --quiet; then
  exit 0
fi
git commit -m "chore: refresh bus-live snapshot ($(date -u +%Y-%m-%dT%H:%MZ))"
git pull --rebase origin main
git push origin main