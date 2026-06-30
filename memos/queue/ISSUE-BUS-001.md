[Tue Jun 30, 2026]

[← Dashboard](https://nicholasg3.github.io/nick2-dashboard/index.html)

**ISSUE-BUS-001: Fix agent-bus worker_model crash**

## SITUATION

Coding workers cannot reliably spawn: `bus.py` calls `worker_model.py` to pick an OpenRouter slug, but an empty-string registry model breaks resolution. Until this lands, DISPATCH-001 jobs pile up held/queued behind dead harnesses.

## MECE DECOMPOSITION

- **Reproduce** — Scratch tests in worktree exercising resolve_or_ccr_default — in flight
- **Patch** — bus.py passes None not "" when session meta has no model — patched in JOB-549 worktree
- **Unit test** — Permanent test_worker_model.py under agent-bus/scripts — not merged yet
- **Witness** — Tests exit 0; worker spawn shows model: line without traceback — open

## PATHS CONSIDERED

- Patch bus.py only (minimal — empty string → None)
- Rewrite worker_model tier routing (ISSUE-ROUTING-001 scope — defer)
- Bypass worker_model and hardcode CCR default (hides bug)

## CHOSEN PATH + WHY

Minimal bus.py fix first because the crash is an integration bug (empty string is truthy bad input), not missing routing policy. Routing policy is rank #3 separately.

## WHERE IT STANDS

JOB-549 executing on ai-agents-workspace. Worktree shows 1-line bus.py fix plus scratch reproduce scripts; permanent test + witness still needed before complete.

> POL-002: last ledger touch **45m** ago — heartbeat or status transition due.


## EFFORT & COST

- **Time:** Executing — watch 15m coding_worker timeout
- **Work:** coding_worker branch job/20260630-549-issue-bus-001-fix-agent-bus-wo
- **Budget:** spent $0.00 · remaining $20.00 · limit $20.00/week

## LINKS

- [Dashboard](https://nicholasg3.github.io/nick2-dashboard/)
- [worker_model.py](agent-bus/scripts/worker_model.py)
- [CEO Ledger](https://nicholasg3.github.io/nick2-dashboard/memos/ledger.html)

_Last updated 2026-06-30 22:30 SGT_
