# Gated by Nick — priority queue

## 1. Executive Framing

**Objective:** Ordered inbox of decisions that block or shape autonomous operations.  
**Decision:** Nick works top-down; agents ignore this list for execution.

## 2. Queue (MECE)

| # | Priority | ID | Decision needed |
|---|----------|-----|-----------------|
| 1 | medium | `ISSUE-24` | [DECISION: revisit Telegram bot permission posture](../gate-room.html?task=ISSUE-24) |
| 2 | medium | `ISSUE-ROUTING-001` | [OpenRouter model routing policy in worker_model](../gate-room.html?task=ISSUE-ROUTING-001) |
| 3 | medium | `ISSUE-80` | [Nick2 dashboard: hourly ledger reconcile + memo generation on droplet](../gate-room.html?task=ISSUE-80) |

## 3. Root cause

Gates exist because framework, alerts, or explicit approval require Nick — not because agents are idle.

## 5. Recommendation

**Nick:** Start with **#1** (DECISION: revisit Telegram bot permission posture).  
**Agents:** Continue ungated queue — [policy](policy.html).
