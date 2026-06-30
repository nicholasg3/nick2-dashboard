#!/usr/bin/env bash
# POL-003 — reconcile ledger↔bus, regenerate memos, push to GitHub Pages source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export AGENT_BUS_DB="${AGENT_BUS_DB:-$HOME/ai-agents-workspace/agent-bus/jobs.sqlite}"

python3 scripts/pmo_cycle.py || true
python3 scripts/reconcile-ledger.py
python3 scripts/generate-memos.py
python3 scripts/export_bus_live.py
python3 scripts/export-json-reports.py

git add logs/ceo-ledger.jsonl reports/ memos/ 2>/dev/null || true
if git diff --staged --quiet; then
  exit 0
fi

git commit -m "chore: dashboard-live sync $(date -u +%Y-%m-%dT%H:%MZ)"
STASHED=0
if ! git diff --quiet || ! git diff --cached --quiet; then
  git stash push -m "sync-dashboard-live stash $(date -u +%Y-%m-%dT%H:%MZ)" --include-untracked || true
  STASHED=1
fi
git pull --rebase origin main
git push origin main
if [ "$STASHED" = "1" ]; then
  git stash pop || true
fi