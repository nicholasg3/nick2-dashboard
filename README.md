# Nick2 Dashboard

Public operations console for the Nick2 AI-native company.

**Live URL:** https://nicholasg3.github.io/nick2-dashboard/

## Architecture

| Layer | Role |
|-------|------|
| `logs/ceo-ledger.jsonl` | **Source of truth** — append-only event log |
| `dashboard/` | Static HTML/JS/CSS ops console |
| `reports/*.json` | Derived snapshots (trust, costs, roadmap) — regenerated on deploy |
| `.github/workflows/deploy.yml` | GitHub Pages deployment |

Agents never rewrite history. They append one JSON line per action.

## Update the dashboard

```bash
python3 scripts/append-ledger-event.py '{
  "actor": "PMO",
  "event": "task_started",
  "task_id": "PMO-001",
  "task": "Triage ready-for-agent issues",
  "status": "in_progress",
  "cost_usd": 0.03,
  "output": "Started triage."
}'

git add logs/ceo-ledger.jsonl
git commit -m "ledger: PMO triage started"
git push
```

Push redeploys in ~1 minute.

## Sync from ai-agents-workspace

The canonical agent repo is private (`nicholasg3/ai-agents-workspace`). This public repo hosts only the dashboard surface — no secrets. CEO/agents can push ledger updates here directly, or you can mirror ledger commits from the private repo.

## Local preview

```bash
python3 scripts/export-json-reports.py
mkdir -p _site/logs _site/reports
cp dashboard/* _site/ && cp logs/ceo-ledger.jsonl _site/logs/ && cp reports/*.json _site/reports/
cd _site && python3 -m http.server 8765
```

Open http://localhost:8765

## Enable Pages (one-time)

**Settings → Pages → Build and deployment → Source: GitHub Actions**