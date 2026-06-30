"""POL-003 — ledger ↔ agent-bus honesty: detect drift and reconcile.

The dashboard lies when the ledger cites a bus job as executing after that job
completed, or when in_progress missions have no matching worker on the bus.
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

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
ACTIVE_STATUSES = frozenset({"in_progress", "queued", "approved"})
EXECUTING_RE = re.compile(r"\b(executing|running|still running|in flight)\b", re.I)
MARKER_PREFIX = "reconcile-bus:"


def cited_job_suffixes(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"JOB-(\d+)", text or "")))


def parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        raw = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def minutes_since(ts: str) -> float | None:
    dt = parse_ts(ts)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SGT)
    return (datetime.now(SGT) - dt.astimezone(SGT)).total_seconds() / 60.0


def load_events(path: Path | None = None) -> list[dict]:
    path = path or LEDGER
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(__import__("json").loads(line))
    return sorted(out, key=lambda e: e.get("ts", ""))


def task_state(events: list[dict]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for ev in events:
        tid = ev.get("task_id")
        if tid:
            tasks[tid] = {**tasks.get(tid, {}), **ev}
    return tasks


def has_output_marker(events: list[dict], task_id: str, marker: str) -> bool:
    for ev in reversed(events):
        if ev.get("task_id") == task_id and marker in (ev.get("output") or ""):
            return True
    return False


def _bus_conn() -> sqlite3.Connection | None:
    if not BUS_DB.is_file():
        return None
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def detect_drift(
    events: list[dict] | None = None,
    *,
    ledger_path: Path | None = None,
    bus_db: Path | None = None,
) -> list[str]:
    """Return human-readable drift issues (empty = honest)."""
    global BUS_DB
    if bus_db:
        BUS_DB = bus_db
    events = events if events is not None else load_events(ledger_path)
    tasks = task_state(events)
    conn = _bus_conn()
    if not conn:
        return []

    issues: list[str] = []

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

    for tid, t in tasks.items():
        status = (t.get("status") or "").lower()
        output = t.get("output") or ""
        if status not in ACTIVE_STATUSES and status != "approved":
            continue
        for suffix in cited_job_suffixes(output):
            row = job_for_suffix(suffix)
            if not row or row["status"] != "completed":
                continue
            marker = f"{MARKER_PREFIX}{tid}-job-{suffix}-done"
            if has_output_marker(events, tid, marker):
                continue
            if status == "in_progress" or EXECUTING_RE.search(output):
                issues.append(
                    f"{tid} cites completed {row['job_id']} as still active "
                    f"(ledger status={status})"
                )

        if tid == "PMO-001" and status == "in_progress":
            age = minutes_since(t.get("ts", ""))
            marker = f"{MARKER_PREFIX}pmo-stale-no-worker"
            if (
                age is not None
                and age > WIP_STALE_MIN
                and not session_running("pmo")
                and not has_output_marker(events, tid, marker)
            ):
                issues.append(
                    f"PMO-001 in_progress {int(age)}m with no PMO worker on bus"
                )

        if tid == "P-001" and status == "approved":
            age = minutes_since(t.get("ts", ""))
            marker = f"{MARKER_PREFIX}p001-stale-approved"
            if (
                age is not None
                and age > WIP_STALE_MIN
                and not has_output_marker(events, tid, marker)
            ):
                issues.append(f"P-001 approved {int(age)}m without heartbeat")

    conn.close()
    return issues


def reconcile_bus(
    events: list[dict],
    tasks: dict[str, dict],
    base: dict,
    append: Callable[[dict], bool],
    *,
    bus_db: Path | None = None,
) -> int:
    """Append corrective ledger events for bus/ledger drift. Returns count."""
    global BUS_DB
    if bus_db:
        BUS_DB = bus_db
    conn = _bus_conn()
    if not conn:
        return 0
    n = 0

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

    for tid, t in list(tasks.items()):
        status = (t.get("status") or "").lower()
        output = t.get("output") or ""
        if status not in ACTIVE_STATUSES:
            continue
        for suffix in cited_job_suffixes(output):
            row = job_for_suffix(suffix)
            if not row or row["status"] != "completed":
                continue
            marker = f"{MARKER_PREFIX}{tid}-job-{suffix}-done"
            if has_output_marker(events, tid, marker):
                continue
            if status != "in_progress" and not EXECUTING_RE.search(output):
                continue

            owner = t.get("owner") or t.get("actor") or "worker"
            session = {
                "dashboard_worker": "dashboard_worker",
                "PMO": "pmo",
                "CEO": "CEO",
            }.get(owner, owner)

            replacement = conn.execute(
                "SELECT job_id FROM jobs WHERE status='running' "
                "AND to_session=? ORDER BY updated_at DESC LIMIT 1",
                (session.lower() if session != "CEO" else session,),
            ).fetchone()
            if not replacement and session == "dashboard_worker":
                replacement = conn.execute(
                    "SELECT job_id FROM jobs WHERE status='running' "
                    "AND to_session='dashboard_worker' LIMIT 1"
                ).fetchone()

            if replacement:
                short = re.search(r"-(\d+)$", replacement["job_id"])
                short_id = f"JOB-{short.group(1)}" if short else replacement["job_id"]
                append({
                    **base,
                    "event": "task_updated",
                    "task_id": tid,
                    "task": t.get("task", tid),
                    "status": "in_progress",
                    "owner": owner,
                    "output": (
                        f"{marker} Prior {row['job_id']} completed; now {short_id} on bus."
                    ),
                })
            else:
                append({
                    **base,
                    "event": "task_updated",
                    "task_id": tid,
                    "task": t.get("task", tid),
                    "status": "completed",
                    "owner": owner,
                    "output": (
                        f"{marker} {row['job_id']} completed on bus — no {session} job running."
                    ),
                })
                if tid.startswith(("SYS-", "FOCUS-")) or tid == "SYS-002":
                    append({
                        **base,
                        "event": "focus_snapshot",
                        "task_id": "FOCUS-001",
                        "focus_task_id": tid if tid != "FOCUS-001" else "SYS-002",
                        "task": t.get("task", tid),
                        "focus_line": f"{t.get('task', tid)} — bus job done, no worker running",
                        "focus_detail": f"{row['job_id']} completed; reconcile updated {tid}.",
                        "status": "completed",
                        "owner": owner,
                        "output": marker,
                    })
            n += 1
            break

    pmo = tasks.get("PMO-001", {})
    if pmo.get("status") == "in_progress":
        age = minutes_since(pmo.get("ts", ""))
        marker = f"{MARKER_PREFIX}pmo-stale-no-worker"
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
                    "Dispatch PMO worker or set idle."
                ),
            })
            n += 1

    prop = tasks.get("P-001", {})
    if prop.get("status") == "approved":
        age = minutes_since(prop.get("ts", ""))
        marker = f"{MARKER_PREFIX}p001-stale-approved"
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
                    f"{marker} Tier B proposal approved {int(age)}m ago — "
                    "handoff to PMO-001 or close."
                ),
            })
            n += 1

    conn.close()
    return n


def missions_citing_job(job_id: str, events: list[dict]) -> list[str]:
    """Task IDs whose latest ledger output mentions this job."""
    short_m = re.match(r"^JOB-\d{8}-(\d+)$", job_id or "")
    short = f"JOB-{short_m.group(1)}" if short_m else job_id
    needles = {job_id, short, f"`{job_id}`"}
    tasks = task_state(events)
    found = []
    for tid, t in tasks.items():
        if tid.startswith("DEC-") or tid.startswith("GATE-"):
            continue
        blob = " ".join(str(t.get(k) or "") for k in ("output", "task", "artifacts"))
        if any(n in blob for n in needles):
            found.append(tid)
    return found


def ledger_event_for_job_finish(
    job_id: str,
    packet: dict[str, Any],
    report: dict[str, Any],
    events: list[dict] | None = None,
) -> dict[str, Any] | None:
    """Proactive POL-003 heartbeat when a bus job finishes."""
    events = events or load_events()
    missions = missions_citing_job(job_id, events)
    if not missions:
        return None
    status = report.get("status", "completed")
    final = "completed" if status == "completed" else "blocked"
    mission = missions[0]
    tasks = task_state(events)
    t = tasks.get(mission, {})
    marker = f"bus-finish:{job_id}"
    if has_output_marker(events, mission, marker):
        return None
    short_m = re.match(r"^JOB-\d{8}-(\d+)$", job_id or "")
    short = f"JOB-{short_m.group(1)}" if short_m else job_id
    return {
        "actor": "COO",
        "role": "Chief Operating Officer",
        "event": "task_updated",
        "task_id": mission,
        "task": t.get("task", packet.get("objective", mission)[:80]),
        "status": final,
        "owner": packet.get("to", t.get("owner", "worker")),
        "output": (
            f"{marker} {short} finished on bus ({status}). "
            f"{(report.get('bottom_line') or '')[:200]}"
        ),
        "needs_nicholas": False,
        "cost_usd": 0,
    }