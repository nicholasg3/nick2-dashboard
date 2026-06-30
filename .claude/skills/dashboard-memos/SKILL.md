---
name: dashboard-memos
description: >-
  Nick2 dashboard memo discipline — McKinsey queue briefs (POL-004) and bus job
  narratives (POL-005). Use when generating memos, job briefs, execution briefs,
  or when Nick cannot tell what is going on from the dashboard.
---

# Dashboard memos — POL-004 + POL-005

Canonical policy: `nick2-dashboard/memos/policy.md`.

## Two memo layers

| Layer | Path | Generator | Policy |
|-------|------|-----------|--------|
| Portfolio / WIP | `memos/queue/{task_id}.md` | `generate-memos.py` + `execution_brief.py` | POL-004 |
| Bus job packet | `memos/jobs/{job_id}.md` | `generate_job_memos.py` | POL-005 |

Nick reads **SITUATION** + **WHERE IT STANDS** first. Raw objectives and bus status bullets alone are a policy violation.

## POL-004 — queue / current briefs

McKinsey sections: Situation → MECE → Paths → Chosen path + why → Where it stands → Effort (Time/Work/Budget) → Links.

Update `EXECUTION_BRIEFS` in `execution_brief.py` when mission reality changes; append ledger `task_updated` (POL-002).

```bash
cd nick2-dashboard && python3 scripts/generate-memos.py
```

## POL-005 — bus job briefs

Each running/held/queued job gets a narrative memo: PMO rank, duplicate warnings, portfolio link to `ISSUE-*`, stall watch.

```bash
cd nick2-dashboard && python3 scripts/generate_job_memos.py
# or via live sync:
python3 scripts/export_bus_live.py
```

Gate: `validate_job_memo()` — script exits 1 if any active memo is thin/boilerplate.

## POL-006 — no duplicate bus packets

Before PMO dispatch retry, check bus DB. After storms:

```bash
python3 agent-bus/scripts/cancel_duplicate_jobs.py --dry-run
python3 agent-bus/scripts/cancel_duplicate_jobs.py
```

## Agents

- **dashboard_worker** — owns generators + policy.md; never ship memo template regressions.
- **PMO** — dispatch idempotent; McKinsey assessments in ledger, not file dumps in objectives.
- **coding_worker** — cite mission ID in reports; bus job ID is implementation detail.