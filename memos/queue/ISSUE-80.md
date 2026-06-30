[Tue Jun 30, 2026]

[← Dashboard](https://nicholasg3.github.io/nick2-dashboard/index.html)

**ISSUE-80: Dashboard live-sync + honest memos**

## SITUATION

Nick cannot tell what workers are doing from thin job memos and lagging exports. POL-003 requires reconcile-on-finish, bus-live export, and cron sync on the droplet.

## MECE DECOMPOSITION

- **Live export** — export_bus_live.py + generate_job_memos on sync tick
- **Reconcile** — reconcile-ledger.py flags stale in_progress per POL-002
- **Cron** — sync-dashboard-live.sh every 15m on droplet
- **Witness** — witness_dashboard_honesty.py exits 0

## PATHS CONSIDERED

- React rewrite
- Extend gate server + vanilla JS (chosen for SYS-002)
- Static-only shorter cron

## CHOSEN PATH + WHY

Extend existing Python gate server — same path as SYS-002 live mission; add POL-005 narrative job memos so Nick sees what each worker is actually doing.

## WHERE IT STANDS

JOB-573 executing on nick2-dashboard in parallel with ISSUE-BUS-001 on workspace repo.

## EFFORT & COST

- **Time:** Parallel lane #2 after PMO triage
- **Work:** coding_worker on nick2-dashboard
- **Budget:** spent $0.00 · remaining $20.00 · limit $20.00/week

## LINKS

- [Dashboard](https://nicholasg3.github.io/nick2-dashboard/)
- [GitHub #80](https://github.com/nicholasg3/ai-agents-workspace/issues/80)
- [CEO Ledger](https://nicholasg3.github.io/nick2-dashboard/memos/ledger.html)

_Last updated 2026-06-30 23:15 SGT_
