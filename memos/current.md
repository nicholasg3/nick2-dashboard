_Current focus → [SYS-002](queue/SYS-002.html) · 0 gated · 2026-07-02 10:06 SGT_

**CEO supervision — portfolio idle**

[Thu Jul 2, 2026]

[← Dashboard](https://nicholasg3.github.io/nick2-dashboard/index.html)

**SYS-002: Make the dashboard live**

## SITUATION

The operating dashboard still reads ledger and agent-bus state from GitHub Pages snapshots that can lag minutes behind reality. POL-002 needs server-side stale detection so workers cannot sit at Executing while asleep.

## MECE DECOMPOSITION

- **Live read path** — Add droplet API for ledger tail + bus SQLite — in flight via JOB-924
- **Honest reconcile** — Auto-flag or transition tasks with no heartbeat in 30+ minutes
- **Publish cadence** — 15-minute cron to reconcile, regenerate memos, and push
- **Client wiring** — dashboard app polls live API when configured, static JSON fallback

## PATHS CONSIDERED

- Full React/Node rewrite on GitHub Pages
- Extend existing Python gate server with /api/live/* + vanilla JS polling
- Static-only: shorter cron and hope agents heartbeats

## CHOSEN PATH + WHY

We chose extending the gate server and vanilla JS because it fixes latency and honesty without a framework migration. React would improve DX but would not stop agents from going quiet without the reconcile layer; static-only leaves the phone and dashboard blind during the export gap. The gate server already runs on the droplet beside the ledger — adding live endpoints is the cheapest path that unifies memo and panel reads.

## WHERE IT STANDS

JOB-924 is **executing now** on the droplet (not blocked). One harness crash earlier required a requeue; repo-lock zombies (JOB-755/453) are cleared. Worker is implementing live ledger/bus API, POL-002 reconcile, and 15m sync cron on branch job/20260630-924. JOB-102 waits for 924 to finish. No Nick gate.

## EFFORT & COST

- **Time:** Now: executing since ~19:50 SGT · Mission age ~2h · Past stalls (resolved): ~45m repo locks + ~15m harness retry — not current blockers
- **Work:** JOB-924 attempt 2 executing; attempt 1 blocked (harness); JOB-102 held; JOB-438 parallel
- **Budget:** spent $0.00 · remaining $20.00 · limit $20/week

## LINKS

- [Dashboard](https://nicholasg3.github.io/nick2-dashboard/)
- [CEO Ledger](https://nicholasg3.github.io/nick2-dashboard/memos/ledger.html)

_Last updated 2026-06-30 20:34 SGT_
