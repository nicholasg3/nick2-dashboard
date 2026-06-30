# Nick2 Dashboard

Public operations console for the Nick2 AI-native company.

**Live URL:** https://nicholasg3.github.io/nick2-dashboard/

## Architecture

| Layer | Role |
|-------|------|
| `logs/ceo-ledger.jsonl` | **Source of truth** — append-only event log |
| `dashboard/` | Static HTML/JS/CSS ops console |
| `memos/` | Task memos (`queue/`, `completed/`, `decisions/`, `current.md`) |
| `reports/*.json` | Derived snapshots — regenerated on deploy |
| `scripts/reconcile-ledger.py` | Auto-fix stale queue/decision drift (append-only) |
| `.github/workflows/deploy.yml` | GitHub Pages deployment |
| `.github/workflows/hourly-reconcile.yml` | Hourly reconcile + memo refresh |

## GitHub issues (private repo)

- [#78](https://github.com/nicholasg3/ai-agents-workspace/issues/78) — droplet + nginx basic auth
- [#79](https://github.com/nicholasg3/ai-agents-workspace/issues/79) — Cloudflare Access + custom domain
- [#80](https://github.com/nicholasg3/ai-agents-workspace/issues/80) — droplet hourly reconcile cron

Agents never rewrite history. They append one JSON line per action.

## Nick gate rule

**If anything needs Nicholas → park it in the Gated by Nick queue (`nick_gate` event + `memos/gated/{id}.md`) and keep working on ungated items.**

See `memos/policy.md`. Do not idle waiting on Nick.

## Gate chat (Nick ↔ agent on gated items)

Gated items open an **interactive gate room** (not a static markdown page):

- **On dashboard:** click a gated row or **Discuss** — chat panel opens below the queue
- **Deep link:** `gate-room.html?task=DEC-002`

Messages live in `logs/gate-chats/{task_id}.jsonl` and deploy with the site. Nick's instructions also append `nick_gate_instruction` to the ledger when the bridge is running.

### Enable live send/receive

GitHub Pages is static — run the bridge on your Mac or droplet:

```bash
python3 scripts/gate_chat_server.py
```

Set `dashboard/config.json`:

```json
{ "gateChatApi": "http://YOUR_HOST:8787" }
```

Use ngrok/Cloudflare tunnel or the droplet (issue #78) so the public dashboard can reach it. Without the bridge, the UI still works: messages save locally and show a `curl` command + Telegram deep link.

Optional agent hook: `GATE_AGENT_CMD='python3 path/to/agent.py'` — receives JSON on stdin.

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