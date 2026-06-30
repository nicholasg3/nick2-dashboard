#!/usr/bin/env bash
# Refresh bus-live.json from droplet agent-bus and push to GitHub Pages source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export AGENT_BUS_DB="${AGENT_BUS_DB:-$HOME/ai-agents-workspace/agent-bus/jobs.sqlite}"
python3 scripts/export_bus_live.py
git add reports/bus-live.json memos/jobs/
if git diff --staged --quiet; then
  exit 0
fi
git commit -m "chore: refresh bus-live snapshot ($(date -u +%Y-%m-%dT%H:%MZ))"
# Never stash a human in-progress edit; the old git stash/pop with || true
# silently dropped uncommitted work on a pop conflict. If anything outside
# our generated paths is dirty, defer the rebase/push to a later tick.
if [ -n "$(git status --porcelain | grep -vE '^.. (reports/|memos/|logs/)')" ]; then
  echo "sync-bus-live: deferring push (non-generated changes present)"
  exit 0
fi
git pull --rebase --autostash origin main
git push origin main