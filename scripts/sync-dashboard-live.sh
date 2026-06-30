#!/usr/bin/env bash
# POL-003 — reconcile ledger↔bus, regenerate memos, push to GitHub Pages source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export AGENT_BUS_DB="${AGENT_BUS_DB:-$HOME/ai-agents-workspace/agent-bus/jobs.sqlite}"
mkdir -p logs
date -u +%Y-%m-%dT%H:%M:%SZ > logs/sync-heartbeat.txt

python3 scripts/pmo_cycle.py || true
python3 scripts/reconcile-ledger.py
python3 scripts/generate-memos.py
python3 scripts/export_bus_live.py
python3 scripts/export-json-reports.py

git add logs/ceo-ledger.jsonl reports/ memos/ logs/sync-heartbeat.txt 2>/dev/null || true
if git diff --staged --quiet; then
  date -u +%Y-%m-%dT%H:%M:%SZ > logs/sync-heartbeat.txt
  python3 scripts/cron_health.py || true
  exit 0
fi

git commit -m "chore: dashboard-live sync $(date -u +%Y-%m-%dT%H:%MZ)"
# Never stash a human in-progress edit; the old git stash/pop with || true
# silently dropped uncommitted work on a pop conflict. If anything outside
# our generated paths is dirty, defer the rebase/push to a later tick.
if [ -n "$(git status --porcelain | grep -vE '^.. (reports/|memos/|logs/)')" ]; then
  echo "sync-dashboard-live: deferring push (non-generated changes present)"
  exit 0
fi
git pull --rebase --autostash origin main
git push origin main

date -u +%Y-%m-%dT%H:%M:%SZ > logs/sync-heartbeat.txt
python3 scripts/cron_health.py || true