#!/usr/bin/env python3
"""Append-only ledger reconciliation — fix stale queue/decision drift.

Rules (each emits at most one corrective event per run per rule):
- Budget authorized (weekly_budget_usd > 0) → resolve DEC-001 convention decision
- Budget authorized → refresh PMO-001 if still waiting on budget
- Budget authorized + worker still disabled → note SYS-001 blocker is worker flag, not budget
- Superseded open decisions → decision_resolved when ledger already answers them

Never edits existing lines. Idempotent: skips if corrective event already present this week.
- agent-bus reality → refresh SYS-002 / PMO-001 when ledger cites completed jobs or goes stale
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
BUS_DB = Path(
    os.environ.get(
        "AGENT_BUS_DB",
        ROOT.parent / "ai-agents-workspace" / "agent-bus" / "jobs.sqlite",
    )
)
SGT = timezone(timedelta(hours=8))
WIP_STALE_MIN = 30


def now_sgt() -> str:
    return datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return sorted(out, key=lambda e: e.get("ts", ""))


def latest(events: list[dict], key: str, default=None):
    for ev in reversed(events):
        if key in ev and ev[key] is not None:
            return ev[key]
    return default


def task_state(events: list[dict]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for ev in events:
        tid = ev.get("task_id")
        if tid:
            tasks[tid] = {**tasks.get(tid, {}), **ev}
    return tasks


def has_event(events: list[dict], *, event: str, task_id: str | None = None) -> bool:
    for ev in reversed(events):
        if ev.get("event") == event and (task_id is None or ev.get("task_id") == task_id):
            return True
    return False


def has_output_marker(events: list[dict], task_id: str, marker: str) -> bool:
    for ev in reversed(events):
        if ev.get("task_id") == task_id and marker in (ev.get("output") or ""):
            return True
    return False


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        raw = ts.replace("Z", "+00:00")
        if raw.endswith("+08:00"):
            return datetime.fromisoformat(raw)
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def minutes_since(ts: str) -> float | None:
    dt = _parse_ts(ts)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SGT)
    return (datetime.now(SGT) - dt.astimezone(SGT)).total_seconds() / 60.0


def cited_job_suffixes(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"JOB-(\d+)", text or "")))


def reconcile_bus(events: list[dict], tasks: dict[str, dict], base: dict) -> int:
    """Align ledger missions with agent-bus — POL-002 honesty."""
    if not BUS_DB.is_file():
        return 0
    n = 0
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row

    def job_for_suffix(suffix: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT job_id, status, updated_at, to_session, repo FROM jobs "
            "WHERE job_id LIKE ? ORDER BY updated_at DESC LIMIT 1",
            (f"%-{suffix}",),
        ).fetchone()

    def session_running(session: str) -> bool:
        return bool(
            conn.execute(
                "SELECT 1 FROM jobs WHERE status='running' AND to_session=? LIMIT 1",
                (session,),
            ).fetchone()
        )

    # SYS-002 still cites a completed bus job as "executing"
    sys = tasks.get("SYS-002", {})
    if sys.get("status") == "in_progress":
        for suffix in cited_job_suffixes(sys.get("output", "")):
            row = job_for_suffix(suffix)
            if not row or row["status"] != "completed":
                continue
            marker = f"reconcile-bus:sys002-job-{suffix}-done"
            if has_output_marker(events, "SYS-002", marker):
                continue
            dash_running = conn.execute(
                "SELECT job_id FROM jobs WHERE status='running' "
                "AND to_session='dashboard_worker' AND repo='nick2-dashboard' LIMIT 1"
            ).fetchone()
            if dash_running:
                new_job = dash_running["job_id"]
                short = re.search(r"-(\d+)$", new_job)
                short_id = f"JOB-{short.group(1)}" if short else new_job
                append({
                    **base,
                    "event": "task_updated",
                    "task_id": "SYS-002",
                    "task": sys.get("task", "Make the dashboard live"),
                    "status": "in_progress",
                    "owner": "dashboard_worker",
                    "output": (
                        f"{marker} Prior {row['job_id']} completed; now {short_id} executing on bus."
                    ),
                })
            else:
                append({
                    **base,
                    "event": "task_updated",
                    "task_id": "SYS-002",
                    "task": sys.get("task", "Make the dashboard live"),
                    "status": "completed",
                    "owner": "dashboard_worker",
                    "output": (
                        f"{marker} {row['job_id']} completed on bus — live dashboard mission landed. "
                        "No dashboard_worker job running."
                    ),
                })
                append({
                    **base,
                    "event": "focus_snapshot",
                    "task_id": "FOCUS-001",
                    "focus_task_id": "SYS-002",
                    "task": sys.get("task", "Make the dashboard live"),
                    "focus_line": "Dashboard live mission complete — no dashboard worker on bus",
                    "focus_detail": f"{row['job_id']} completed; reconcile marked SYS-002 done.",
                    "status": "completed",
                    "owner": "dashboard_worker",
                    "output": marker,
                })
            n += 1
            events = load_events()
            break

    # PMO-001 in_progress but no PMO worker on bus (POL-002 stale)
    pmo = tasks.get("PMO-001", {})
    if pmo.get("status") == "in_progress":
        age = minutes_since(pmo.get("ts", ""))
        marker = "reconcile-bus:pmo-stale-no-worker"
        if (
            age is not None
            and age > WIP_STALE_MIN
            and not session_running("pmo")
            and not has_output_marker(events, "PMO-001", marker)
        ):
            append({
                **base,
                "event": "task_updated",
                "task_id": "PMO-001",
                "task": pmo.get("task", "PMO triage"),
                "status": "blocked",
                "owner": "PMO",
                "output": (
                    f"{marker} No PMO job on bus for {int(age)}m (POL-002). "
                    "Triage stalled — dispatch PMO worker or set idle."
                ),
            })
            n += 1
            events = load_events()

    # P-001 approved proposal stale >30m with no CEO activity
    prop = tasks.get("P-001", {})
    if prop.get("status") == "approved":
        age = minutes_since(prop.get("ts", ""))
        marker = "reconcile-bus:p001-stale-approved"
        if (
            age is not None
            and age > WIP_STALE_MIN
            and not has_output_marker(events, "P-001", marker)
        ):
            append({
                **base,
                "event": "task_updated",
                "task_id": "P-001",
                "task": prop.get("task", "PMO triage proposal"),
                "status": "idle",
                "owner": "CEO",
                "output": (
                    f"{marker} Tier B proposal approved {int(age)}m ago with no heartbeat — "
                    "handoff to PMO-001 or close."
                ),
            })
            n += 1

    conn.close()
    return n


def append(event: dict) -> bool:
    event.setdefault("ts", now_sgt())
    event.setdefault("actor", "COO")
    event.setdefault("role", "Chief Operating Officer")
    event.setdefault("event", "reconcile")
    event.setdefault("cost_usd", 0)
    weekly = event.get("weekly_budget_usd")
    if weekly is None:
        # inherit from ledger context in caller
        pass
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    prefix = ""
    if LEDGER.exists() and LEDGER.stat().st_size > 0:
        raw = LEDGER.read_bytes()
        if not raw.endswith(b"\n"):
            prefix = "\n"
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")
    print(f"reconcile: appended {event.get('event')} {event.get('task_id', '')}")
    return True


def reconcile(events: list[dict]) -> int:
    n = 0
    weekly_budget = latest(events, "weekly_budget_usd", 0) or 0
    budget_mode = latest(events, "budget_mode", "off")
    cumulative = latest(events, "cumulative_weekly_spend_usd", 0) or 0
    remaining = max(0, float(weekly_budget) - float(cumulative)) if weekly_budget else 0
    tasks = task_state(events)

    base = {
        "cumulative_weekly_spend_usd": cumulative,
        "budget_remaining_usd": remaining,
        "weekly_budget_usd": weekly_budget,
        "budget_mode": budget_mode,
        "needs_nicholas": False,
    }

    # DEC-001: budget convention — resolved once budget is set positively
    dec = tasks.get("DEC-001", {})
    if (
        weekly_budget > 0
        and dec.get("event") == "decision_needed"
        and not has_event(events, event="decision_resolved", task_id="DEC-001")
        and not has_event(events, event="nick_gate_resolved", task_id="DEC-001")
    ):
        append({
            **base,
            "event": "decision_resolved",
            "task_id": "DEC-001",
            "task": "Confirm budget convention: 0 = OFF",
            "status": "completed",
            "output": "Resolved by reconcile: Nicholas authorized "
            f"${weekly_budget}/week. Convention locked: 0=OFF, positive=cap.",
            "resolved_by": "reconcile-ledger.py",
            "resolution": "convention_confirmed",
        })
        n += 1
        events = load_events()

    # PMO-001: stale 'waiting for budget' after authorization
    pmo = tasks.get("PMO-001", {})
    if weekly_budget > 0 and pmo.get("status") == "queued":
        stale = "budget" in (pmo.get("output") or "").lower()
        if stale and not has_event(events, event="task_updated", task_id="PMO-001"):
            append({
                **base,
                "event": "task_updated",
                "task_id": "PMO-001",
                "task": pmo.get("task", "PMO triage"),
                "status": "queued",
                "owner": "PMO",
                "output": f"Budget authorized (${weekly_budget}/week). "
                "Blocked on worker.enabled=false — enable in lane.json to dispatch.",
            })
            n += 1
            events = load_events()

    # SYS-001: clarify blocker after budget set
    sys = tasks.get("SYS-001", {})
    if (
        weekly_budget > 0
        and sys.get("status") == "blocked"
        and "budget" in (sys.get("output") or "").lower()
        and not has_event(events, event="task_updated", task_id="SYS-001")
    ):
        append({
            **base,
            "event": "task_updated",
            "task_id": "SYS-001",
            "task": sys.get("task", "Frontier worker configuration"),
            "status": "blocked",
            "output": "Budget is set. Remaining blocker: worker.enabled=false in lane.json.",
        })
        n += 1

    # Current focus marker for hourly memo pipeline
    if not has_event(events, event="focus_snapshot"):
        focus_task = "PMO-001"
        ft = tasks.get(focus_task, {})
        append({
            **base,
            "event": "focus_snapshot",
            "task_id": "FOCUS-001",
            "task": ft.get("task", "Awaiting next dispatch"),
            "status": ft.get("status", "queued"),
            "owner": ft.get("owner", "CEO"),
            "focus_task_id": focus_task,
            "output": "Hourly focus: PMO triage queued; enable frontier worker to start.",
        })
        n += 1

    n += reconcile_bus(events, tasks, base)

    return n


def main() -> None:
    events = load_events()
    count = reconcile(events)
    print(f"reconcile: {count} event(s) appended")


if __name__ == "__main__":
    main()