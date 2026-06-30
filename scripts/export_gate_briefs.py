#!/usr/bin/env python3
"""Export reports/gate-briefs.json for interactive gate rooms."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mka_memo import TASK_BRIEFS, _brief, _fallback_mece, _fallback_options

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
OUT = ROOT / "reports" / "gate-briefs.json"


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]


def task_state(events: list[dict]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for ev in events:
        tid = ev.get("task_id")
        if tid:
            tasks[tid] = {**tasks.get(tid, {}), **ev}
    return tasks


def resolved(events: list[dict]) -> set[str]:
    out = set()
    for ev in events:
        if ev.get("event") in {"decision_resolved", "nick_gate_resolved"}:
            out.add(ev.get("task_id", ""))
    return out


def is_gated(tid: str, t: dict, resolved_ids: set[str]) -> bool:
    if tid in resolved_ids:
        return False
    if t.get("gated_by_nick") or t.get("needs_nicholas"):
        return True
    if t.get("status") == "awaiting_nicholas":
        return True
    if t.get("event") in {"nick_gate", "decision_needed"}:
        return True
    return False


def nick_rank(t: dict) -> int:
    return {"high": 1, "medium": 2, "low": 3}.get(t.get("priority", ""), 99)


def export_brief(tid: str, t: dict, rank: int) -> dict:
    brief = _brief(tid, t)
    what = t.get("what_nick_must_do") or brief.get("nick_action") or t.get("output", "")
    return {
        "task_id": tid,
        "title": t.get("task", tid),
        "priority": t.get("priority", "medium"),
        "rank": rank,
        "objective": brief.get("objective", ""),
        "decision": brief.get("decision", ""),
        "mece": brief.get("mece") or _fallback_mece(tid, t),
        "root_cause": brief.get(
            "root_cause",
            "Human decision is on the critical path.",
        ),
        "options": brief.get("options") or _fallback_options(t, gated=True),
        "recommendation": brief.get("recommendation", ""),
        "what_nick_must_do": what,
    }


def main() -> None:
    events = load_events()
    tasks = task_state(events)
    resolved_ids = resolved(events)
    gated = sorted(
        [(tid, t) for tid, t in tasks.items() if is_gated(tid, t, resolved_ids)],
        key=lambda x: (nick_rank(x[1]), x[1].get("ts", "")),
    )
    out = {tid: export_brief(tid, t, i + 1) for i, (tid, t) in enumerate(gated)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"export_gate_briefs: {len(out)} brief(s) → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()