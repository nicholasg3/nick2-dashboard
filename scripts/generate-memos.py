#!/usr/bin/env python3
"""Generate dashboard memos from ceo-ledger.jsonl.

Memo types:
  - Execution Brief — active queue / WIP (in_progress, queued, …)
  - MKA Decision Memo — gated items awaiting Nicholas
  - Postmortem-style summary — completed (mka_memo completed body)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from md_page import write_html
from work_queue_ops import is_deferred_task
from execution_brief import ceo_focus_line, execution_brief_body
from mka_memo import (
    mka_completed_body,
    mka_gated_body,
    mka_gated_queue_body,
)

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
        and not is_deferred_task(t.get("task_id", ""))
    ]
    ungated_active = [
        t for t in tasks.values()
        if t.get("status") in ACTIVE
        and ungated(t)
        and t.get("last_event") not in SKIP_QUEUE
        and not is_deferred_task(t.get("task_id", ""))
    ]
    primary = in_prog[0] if in_prog else (ft if ungated(ft) else (ungated_active[0] if ungated_active else {}))
    pid = primary.get("task_id", focus_id if ungated(ft) else "—")
    now = datetime.now(SGT).strftime("%Y-%m-%d %H:%M SGT")
    spend = float(latest(events, "cumulative_weekly_spend_usd", 0) or 0)
    gated_count = sum(1 for tid, t in tasks.items() if is_gated(tid, t, resolved))

    if not primary or pid == "—":
        return f"""{_current_date()}

# Current focus — Nick2

_Updated {now}_

No active ungated work in queue. See [gated queue](gated-queue.html) or [roadmap](index.html#roadmap).

[Dashboard](https://nicholasg3.github.io/nick2-dashboard/)
"""

    rem = float(latest(events, "budget_remaining_usd", weekly - spend) or 0)
    body = execution_brief_body(
        pid,
        primary,
        events=events,
        weekly=weekly,
        spend=spend,
        remaining=rem,
        memo_context="current",
    )
    focus_line = (focus_ev or {}).get("focus_line") or ceo_focus_line(pid, primary)
    return (
        f"_Current focus → [{pid}](queue/{pid}.html) · "
        f"{gated_count} gated · {now}_\n\n"
        f"**{focus_line}**\n\n{body}"
    )


def _current_date() -> str:
    dt = datetime.now(SGT)
    return f"[{dt.strftime('%a %b')} {dt.day}, {dt.year}]"


def ledger_html(events: list[dict]) -> str:
    return f"""# CEO ledger (last 40 events)

Read-only view of `logs/ceo-ledger.jsonl`.

| Time | Actor | Event | Task ID | Task |
|------|-------|-------|---------|------|
{chr(10).join(
    f"| {(e.get('ts') or '')[:19]} | {e.get('actor', '')} | {e.get('event', '')} | {e.get('task_id', '')} | {(e.get('task') or '')[:50]} |"
    for e in reversed(events[-40:])
)}
"""


def html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def emit_pair(md_path: Path, md: str, title: str, back: str) -> None:
    write(md_path, md)
    write_html(md_path.with_suffix(".html"), md, title, back)


def main() -> None:
    events = load_events()
    tasks = task_state(events)
    weekly = float(latest(events, "weekly_budget_usd", 0) or 0)
    resolved = resolved_decisions(events)

    gated_items = sorted(
        [(tid, t) for tid, t in tasks.items() if is_gated(tid, t, resolved)],
        key=lambda x: (nick_rank(x[1]), x[1].get("ts", "")),
    )

    queue_written: set[str] = set()

    for tid, t in tasks.items():
        ev = t.get("event", "")
        status = t.get("status", "")
        if status == "completed" or ev == "task_completed":
            body = mka_completed_body(tid, t)
            emit_pair(MEMOS / "completed" / f"{tid}.md", body, f"{tid} completed", "../../index.html")
        elif status == "idle":
            spend = float(latest(events, "cumulative_weekly_spend_usd", 0) or 0)
            rem = float(latest(events, "budget_remaining_usd", weekly - spend) or 0)
            body = execution_brief_body(
                tid,
                t,
                events=events,
                weekly=weekly,
                spend=spend,
                remaining=rem,
                memo_context="queue",
            )
            emit_pair(
                MEMOS / "completed" / f"{tid}.md",
                body,
                f"{tid} idle",
                "../../index.html",
            )
        elif is_gated(tid, t, resolved):
            rank = next((i + 1 for i, (g, _) in enumerate(gated_items) if g == tid), 0)
            body = mka_gated_body(tid, t, rank)
            emit_pair(MEMOS / "gated" / f"{tid}.md", body, f"{tid} gated", "../../index.html")
        elif status in ACTIVE and is_deferred_task(tid):
            spend = float(latest(events, "cumulative_weekly_spend_usd", 0) or 0)
            rem = float(latest(events, "budget_remaining_usd", weekly - spend) or 0)
            idle_row = {**t, "status": "idle"}
            body = execution_brief_body(
                tid,
                idle_row,
                events=events,
                weekly=weekly,
                spend=spend,
                remaining=rem,
                memo_context="queue",
            )
            emit_pair(
                MEMOS / "completed" / f"{tid}.md",
                body,
                f"{tid} deferred",
                "../../index.html",
            )
        elif status in ACTIVE and t.get("last_event", ev) not in SKIP_QUEUE:
            spend = float(latest(events, "cumulative_weekly_spend_usd", 0) or 0)
            rem = float(latest(events, "budget_remaining_usd", weekly - spend) or 0)
            body = execution_brief_body(
                tid,
                t,
                events=events,
                weekly=weekly,
                spend=spend,
                remaining=rem,
                memo_context="queue",
            )
            emit_pair(
                MEMOS / "queue" / f"{tid}.md",
                body,
                f"{tid} execution brief",
                "../../index.html",
            )
            queue_written.add(tid)

    queue_dir = MEMOS / "queue"
    if queue_dir.is_dir():
        for path in queue_dir.glob("*.md"):
            if path.stem not in queue_written:
                path.unlink(missing_ok=True)
                path.with_suffix(".html").unlink(missing_ok=True)

    current = current_memo(events, tasks, weekly)
    emit_pair(MEMOS / "current.md", current, "Current focus", "../index.html")

    gated_md = mka_gated_queue_body(gated_items)
    emit_pair(MEMOS / "gated-queue.md", gated_md, "Gated queue", "../index.html")

    policy_path = MEMOS / "policy.md"
    if policy_path.exists():
        policy_md = policy_path.read_text(encoding="utf-8")
        write_html(MEMOS / "policy.html", policy_md, "Nick gate policy", "../index.html")

    ledger_md = ledger_html(events)
    emit_pair(MEMOS / "ledger.md", ledger_md, "CEO ledger", "../index.html")

    try:
        from generate_job_memos import main as gen_job_memos

        gen_job_memos()
    except Exception as exc:
        print(f"generate_job_memos skipped: {exc}", file=sys.stderr)

    print(f"generate-memos: wrote memos (.md + .html) under {MEMOS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()