# ISSUE-BUS-001: Fix agent-bus worker_model crash — Completed

**Owner:** coding · **Status:** completed · **Updated:** 2026-06-30T23:37 · **Cost:** $0.00


## 1. Executive Framing

**Objective:** Advance: Fix agent-bus worker_model crash  
**Outcome:** work-queue:Fix already on main; worker_model collapses empty-string registry_model to None and falls back to DEFAULTS. Added permanent regression test test_worker_model.py (5 cases, exit 0) + verified worker dry-run shows model: line with no traceback. Witness green. Stale JOB-549 worktree left untouched. (commit 54a8e1a)

## 2. What shipped (MECE)

| Bucket | Scope | Current state |
|--------|-------|---------------|
| Work unit | Fix agent-bus worker_model crash | work-queue:Fix already on main; worker_model collapses empty-string registry_model to None and falls back to DEFAULTS. A |
| Status & owner | completed / coding | 2026-06-30T23:37 |
| Dependencies | Gates, budget, worker | See dashboard Gated queue and budget panel |
| Deliverable | Ledger event + artifacts | agent-bus/scripts/test_worker_model.py |

## 3. Root cause addressed

Work item reached completed status in ledger.

## 5. Recommendation

**Done.** No further action unless regression.

## Artifacts

- `agent-bus/scripts/test_worker_model.py`
