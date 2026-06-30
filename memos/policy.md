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