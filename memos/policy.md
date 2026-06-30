# Nick gate policy — CEO & agents

## Rule

**If anything needs Nicholas, park it in the Gated by Nick queue and keep working on ungated items.**

Do not block the company waiting on Nick. The gate is a priority inbox for Nick, not a stop sign for agents.

## How to gate an item

Append one line to `logs/ceo-ledger.jsonl`:

```json
{
  "actor": "CEO",
  "event": "nick_gate",
  "task_id": "GATE-004",
  "task": "Short title of what Nick must decide",
  "status": "awaiting_nicholas",
  "gated_by_nick": true,
  "needs_nicholas": true,
  "nick_priority": 1,
  "priority": "high",
  "output": "Exactly what Nick needs to do or decide.",
  "what_nick_must_do": "Approve X / reply Y / flip flag Z"
}
```

**Priority:** `nick_priority` 1 = highest (or `priority`: `high` | `medium` | `low`).

`decision_needed` events are treated the same as `nick_gate`.

## How Nick clears a gate

```json
{
  "actor": "CEO",
  "event": "nick_gate_resolved",
  "task_id": "GATE-004",
  "task": "Same title",
  "status": "completed",
  "output": "Nick approved via Telegram on 2026-06-30.",
  "resolved_by": "Nicholas"
}
```

Alias: `decision_resolved` also clears the gate.

## What stays OUT of the gate

- Mechanical work with a runnable witness
- Tier-A auto-runs
- Optional improvements Nick might like but did not block on (note in queue memo, do not gate)

## Dashboard

- **Gated by Nick** — priority queue (sorted high → low)
- **Active Work Queue** — agents execute here; never includes gated items
- **Currently Working On** — always an ungated task

Memos: `memos/gated/{task_id}.md`

## WIP execution brief cadence (POL-002)

Any task in **Active Work Queue** (`queued`, `in_progress`, `approved`, `blocked`) must keep its execution brief honest:

1. Append a `task_updated` (or `task_progress`) line to `logs/ceo-ledger.jsonl` **at least every 30 minutes** while work is in flight, even if the update is “still running, no new artifacts.”
2. Run `python3 scripts/generate-memos.py` after material progress (or include in the same commit as the ledger append).
3. If nothing changed for **30+ minutes**, either:
   - post a heartbeat ledger event with current step + ETA/blocker, or
   - transition status to `idle` / `completed` / `blocked` with an explicit reason (do not leave `in_progress` with a stale timestamp).

Dashboard memos surface **Last Updated** from the ledger. Stale `in_progress` without a heartbeat is a policy violation — COO may flag in reconcile.

**Idle/sleep:** Autonomous sub-agents (e.g. `cro_lit_memory`) that choose to sleep must append `status: idle` and a one-line reason; they are not “Executing” on the dashboard.

## Bus–ledger coupling (POL-003)

The **CEO ledger** and **agent-bus** are two witnesses. The dashboard must not cite a bus job as “executing” after that job has `status: completed` on the bus.

### Automatic (no Nick action)

1. **On every bus job finish** — `agent-bus/scripts/bus.py` calls `nick2-dashboard/scripts/bus_finish_sync.py`:
   - Appends `bus-finish:JOB-…` heartbeat to any mission that cited the job
   - Runs `reconcile-ledger.py` + `export_bus_live.py`
2. **Every 15 minutes (droplet cron)** — `scripts/sync-dashboard-live.sh` reconciles, regenerates memos, pushes to `main`
3. **Every GitHub Pages deploy** — `reconcile-ledger.py` runs in CI before assemble
4. **Hourly** — `hourly-reconcile.yml` refreshes ledger + memos + `bus-live.json`

### Drift detection

`python3 scripts/witness_dashboard_honesty.py` must exit 0 (used as jesus-ralph gate). It runs `dashboard_honesty.detect_drift()` — fails if ledger cites completed jobs as active, or PMO is `in_progress` with no PMO worker on the bus.

### Agents

- Do not write “JOB-924 executing” in final reports after the job completes — `bus_finish_sync` owns the transition.
- Cite **mission IDs** (SYS-002, PMO-001) in ledger; bus job IDs are implementation detail.

## Execution brief format (POL-004)

**Queue / current / idle** memos (`memos/queue/*.md`, `memos/current.md`) use the McKinsey-style template from `scripts/execution_brief.py` — not the old progress-bar boilerplate.

Required sections (real content only — no `TBD`, `—`, `_None_` as the whole section):

1. **SITUATION** — why this mission is on the board (1–2 sentences)
2. **MECE DECOMPOSITION** — mutually exclusive branches with current state
3. **PATHS CONSIDERED** — options genuinely on the table
4. **CHOSEN PATH + WHY** — substantive tradeoff prose
5. **WHERE IT STANDS** — plain done/in-flight; blockers inline only when explaining state
6. **EFFORT & COST** — always all three: Time, Work, Budget
7. **LINKS** — working dashboard/ledger/GitHub links

**CEO Focus** (`dashboard/app.js`): one plain sentence — never a truncated title.

**Gate:** `python3 scripts/generate-memos.py` must exit 0. Rich briefs live in `EXECUTION_BRIEFS`; agents append ledger heartbeats (POL-002) when state changes.

## Bus job memo format (POL-005)

**Per-job** memos (`memos/jobs/JOB-*.md`) answer: *why does this packet exist, where is it, what should Nick know?* They are generated by `scripts/generate_job_memos.py` on every `export_bus_live.py` / `generate-memos.py` run — never hand-written boilerplate.

Required sections:

1. **SITUATION** — one sentence *why this packet exists* (the problem, not PMO boilerplate)
2. **WHAT IT'S DOING** — plain-language work plan from `job_work_catalog.json` (steps + done-when + files in scope) plus **live worktree** diff when running
3. **WHERE IT STANDS** — executing/held/queued narrative, active duplicate warning only, 15m stall watch
4. **EFFORT & COST** — time in state, worker/repo/branch, budget from ledger tail
5. **LINKS** — `ISSUE-*` queue brief, GitHub issue when known, ledger + bus packet pointers

**Catalog:** `job_work_catalog.json` is the durable “what is it trying to do” source — update at triage/dispatch time; generators refuse thin memos without steps + done-when.

Forbidden: memos that are only bus status bullets + raw objective dump.

**Gate:** `generate_job_memos.py` runs `validate_job_memo()` — non-zero exit if any active job memo fails POL-005.

**Duplicates:** PMO must not stack identical `feature_name` packets. Run `agent-bus/scripts/cancel_duplicate_jobs.py` after bad retry storms; prefer idempotent dispatch (see PMO SKILL).

## Dispatch deduplication (POL-006)

One active bus packet per `(repo, feature_name)`:

- Before `bus.py submit`, check `jobs.sqlite` for `running|queued|held` with the same slug.
- After retry/dispatch storms, run `python3 agent-bus/scripts/cancel_duplicate_jobs.py` on the droplet (keeps `running`, else earliest `queued`).
- Close extras as `closed-superseded`, not `completed`.

## Smoke and witness (POL-007)

**Smoke checks and acceptance witnesses are steps inside the job that owns the work** — not separate `JOB-*` rows on the dashboard.

- **Do:** run the witness command on the job branch before the worker report; cite `exit 0` in evidence.
- **Do not:** `bus.py submit` with `smoke` in the objective (rejected at submit unless `--allow-smoke` for infra harness only).
- **Dashboard:** `export_bus_live.py` and `generate_job_memos.py` hide smoke packets entirely.
- **Cleanup:** `python3 agent-bus/scripts/cancel_duplicate_jobs.py --smoke-only` on the droplet.