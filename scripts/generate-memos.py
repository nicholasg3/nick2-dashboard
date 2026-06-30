#!/usr/bin/env python3
"""Generate markdown memos from ceo-ledger.jsonl for dashboard deep-links."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
MEMOS = ROOT / "memos"
SGT = timezone(timedelta(hours=8))


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return sorted(out, key=lambda e: e.get("ts", ""))


def task_state(events: list[dict]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for ev in events:
        tid = ev.get("task_id")
        if tid:
            tasks[tid] = {**tasks.get(tid, {}), **ev, "last_event": ev.get("event")}
    return tasks


def resolved_decisions(events: list[dict]) -> set[str]:
    resolved = set()
    for ev in events:
        if ev.get("event") == "decision_resolved":
            resolved.add(ev.get("task_id", ""))
    return resolved


def latest(events: list[dict], key: str, default=None):
    for ev in reversed(events):
        if key in ev and ev[key] is not None:
            return ev[key]
    return default


ACTIVE = {"queued", "in_progress", "blocked", "approved"}
SKIP_QUEUE = {
    "decision_needed", "decision_resolved", "nick_gate", "nick_gate_resolved",
    "roadmap_item", "trust_snapshot", "focus_snapshot", "policy_set",
}


def is_gated(tid: str, t: dict, resolved: set[str]) -> bool:
    if tid in resolved:
        return False
    if t.get("gated_by_nick") or t.get("needs_nicholas"):
        return True
    if t.get("status") == "awaiting_nicholas":
        return True
    if t.get("event") in {"nick_gate", "decision_needed"}:
        return True
    return False


def nick_rank(t: dict) -> int:
    if isinstance(t.get("nick_priority"), (int, float)):
        return int(t["nick_priority"])
    return {"high": 1, "medium": 2, "low": 3}.get(t.get("priority", ""), 99)


def write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def queue_memo(tid: str, t: dict, weekly: float) -> str:
    needs = "Yes" if t.get("needs_nicholas") else "No"
    nicholas_section = ""
    if t.get("needs_nicholas"):
        nicholas_section = f"\n## What Nicholas needs to do\n\n{t.get('output', 'Review and approve.')}\n"
    elif tid == "PMO-001" and weekly > 0:
        nicholas_section = (
            "\n## What Nicholas needs to do\n\n"
            "Optional: set `worker.enabled: true` in "
            "`ai-agents-workspace/Projects-for-agents/frontier-orchestrator/lane.json` "
            "to allow autonomous PMO dispatch. Budget is already authorized.\n"
        )
    elif tid == "SYS-001":
        nicholas_section = (
            "\n## What Nicholas needs to do\n\n"
            "Enable frontier worker in `lane.json` when ready for auto-dispatch.\n"
        )

    return f"""# {tid}: {t.get('task', 'Task')}

**Status:** {t.get('status', '—')}  
**Owner:** {t.get('owner') or t.get('actor', '—')}  
**Updated:** {(t.get('ts') or '')[:16]}

## What this is

{t.get('output', 'No detail recorded yet.')}

## Needs Nicholas?

{needs}
{nicholas_section}
## Links

- [Dashboard](https://nicholasg3.github.io/nick2-dashboard/)
- Ledger: `logs/ceo-ledger.jsonl` (task_id `{tid}`)
"""


def completed_memo(tid: str, t: dict) -> str:
    arts = t.get("artifacts") or []
    art_block = "\n".join(f"- `{a}`" for a in arts) if arts else "_None listed._"
    return f"""# {tid}: {t.get('task', 'Task')} — Completed

**Owner:** {t.get('actor', '—')}  
**Completed:** {(t.get('ts') or '')[:16]}  
**Cost:** ${float(t.get('cost_usd') or 0):.2f}

## Summary

{t.get('output', 'Task completed.')}

## Artifacts

{art_block}
"""


def gated_memo(tid: str, t: dict, rank: int) -> str:
    what = t.get("what_nick_must_do") or t.get("output", "Review and respond.")
    return f"""# {tid}: Gated by Nick (priority #{rank})

**Priority:** {t.get('priority', 'medium')}  
**Status:** {t.get('status', 'awaiting_nicholas')}  
**Queue rank:** #{rank}

## Waiting on Nicholas

{t.get('task', '')}

## What Nicholas must do

{what}

## Context for agents

This item is **gated**. Agents must not idle on it — continue ungated work in the Active Work Queue.

## How Nick clears this

Append `nick_gate_resolved` or `decision_resolved` for `{tid}`.

[Policy](../policy.md)
"""


def current_memo(events: list[dict], tasks: dict[str, dict], weekly: float) -> str:
    focus_ev = next((e for e in reversed(events) if e.get("event") == "focus_snapshot"), None)
    focus_id = (focus_ev or {}).get("focus_task_id") or "PMO-001"
    ft = tasks.get(focus_id, {})
    resolved = resolved_decisions(events)

    def ungated(t: dict) -> bool:
        tid = t.get("task_id", "")
        return not is_gated(tid, t, resolved)

    in_prog = [
        t for t in tasks.values()
        if t.get("status") == "in_progress"
        and t.get("event") not in SKIP_QUEUE
        and ungated(t)
    ]
    ungated_active = [
        t for t in tasks.values()
        if t.get("status") in ACTIVE and ungated(t) and t.get("last_event") not in SKIP_QUEUE
    ]
    primary = in_prog[0] if in_prog else (ft if ungated(ft) else (ungated_active[0] if ungated_active else {}))
    pid = primary.get("task_id", focus_id if ungated(ft) else "—")
    now = datetime.now(SGT).strftime("%Y-%m-%d %H:%M SGT")

    return f"""# Current focus — Nick2

_Updated {now} (hourly cadence)_

## Working on now

**{primary.get('owner') or primary.get('actor', 'CEO')}:** {primary.get('task', 'Idle')}

{primary.get('output', '')}

**Task ID:** `{pid}` · **Status:** {primary.get('status', '—')}

[Full memo](queue/{pid}.md)

## Executive context

| Metric | Value |
|--------|-------|
| Weekly budget | ${weekly:.2f} |
| Spend | ${float(latest(events, 'cumulative_weekly_spend_usd', 0) or 0):.2f} |
| Mode | {latest(events, 'budget_mode', '—')} |

## Next unblocked step

{"PMO triage is queued — enable `worker.enabled` in lane.json to dispatch." if weekly > 0 else "Authorize weekly budget in ledger."}
"""


def main() -> None:
    events = load_events()
    tasks = task_state(events)
    weekly = float(latest(events, "weekly_budget_usd", 0) or 0)
    resolved = resolved_decisions(events)

    gated_items = sorted(
        [(tid, t) for tid, t in tasks.items() if is_gated(tid, t, resolved)],
        key=lambda x: (nick_rank(x[1]), x[1].get("ts", "")),
    )

    for tid, t in tasks.items():
        ev = t.get("event", "")
        status = t.get("status", "")
        if status == "completed" or ev == "task_completed":
            write(MEMOS / "completed" / f"{tid}.md", completed_memo(tid, t))
        elif is_gated(tid, t, resolved):
            rank = next((i + 1 for i, (g, _) in enumerate(gated_items) if g == tid), 0)
            write(MEMOS / "gated" / f"{tid}.md", gated_memo(tid, t, rank))
        elif status in ACTIVE and t.get("last_event", ev) not in SKIP_QUEUE:
            write(MEMOS / "queue" / f"{tid}.md", queue_memo(tid, t, weekly))

    write(MEMOS / "current.md", current_memo(events, tasks, weekly))
    write(
        MEMOS / "gated-queue.md",
        "# Gated by Nick — priority queue\n\n"
        + (
            "\n".join(
                f"{i + 1}. **{t.get('task', tid)}** (`{tid}`) — "
                f"[memo](gated/{tid}.md) — {t.get('priority', 'medium')}"
                for i, (tid, t) in enumerate(gated_items)
            )
            if gated_items
            else "_No items gated. Agents: keep executing ungated work._"
        )
        + "\n",
    )
    print(f"generate-memos: wrote memos under {MEMOS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()