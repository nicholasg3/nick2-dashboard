"""POL-003 — ledger ↔ agent-bus honesty: detect drift and reconcile.

The dashboard lies when the ledger cites a bus job as executing after that job
completed, or when in_progress missions have no matching worker on the bus.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
BUS_LIVE = ROOT / "reports" / "bus-live.json"
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


def _bus_live_generated_at() -> datetime | None:
    if not BUS_LIVE.is_file():
        return None
    try:
        data = json.loads(BUS_LIVE.read_text(encoding="utf-8"))
        return parse_ts(data.get("generated_at") or "")
    except (json.JSONDecodeError, OSError):
        return None


def _sqlite_max_updated_age_min(conn: sqlite3.Connection) -> float | None:
    row = conn.execute("SELECT MAX(updated_at) AS m FROM jobs").fetchone()
    if not row or not row["m"]:
        return None
    dt = parse_ts(row["m"])
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60.0


def refresh_bus_live_export() -> bool:
    """Re-export reports/bus-live.json from jobs.sqlite."""
    script = SCRIPTS / "export_bus_live.py"
    if not script.is_file() or not BUS_DB.is_file():
        return False
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=90,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _running_jobs_from_db(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    sel = ["job_id", "status", "to_session", "updated_at"]
    if "display_name" in cols:
        sel.append("display_name")
    rows = conn.execute(
        "SELECT %s FROM jobs WHERE status='running' ORDER BY updated_at DESC"
        % ", ".join(sel)
    ).fetchall()
    out = []
    for r in rows:
        jid = r["job_id"] or ""
        m = re.match(r"^JOB-\d{8}-(\d+)$", jid)
        out.append(
            {
                "job_id": jid,
                "short_job_id": f"JOB-{m.group(1)}" if m else jid,
                "to_session": r["to_session"] or "",
                "updated_at": r["updated_at"] or "",
                "display_name": (r["display_name"] if "display_name" in cols else "") or "",
            }
        )
    return out


def ensure_fresh_bus_truth(
    *,
    required_fresh_min: float = 0.0,
    bus_db: Path | None = None,
) -> dict[str, Any]:
    """Load bus truth; refresh export if snapshot older than required_fresh_min."""
    global BUS_DB
    if bus_db:
        BUS_DB = bus_db

    def _measure() -> tuple[float | None, float | None, list[dict[str, Any]]]:
        live_dt = _bus_live_generated_at()
        live_age = None
        if live_dt:
            if live_dt.tzinfo is None:
                live_dt = live_dt.replace(tzinfo=timezone.utc)
            live_age = (
                datetime.now(timezone.utc) - live_dt.astimezone(timezone.utc)
            ).total_seconds() / 60.0
        sql_age = None
        running: list[dict[str, Any]] = []
        conn = _bus_conn()
        if conn:
            sql_age = _sqlite_max_updated_age_min(conn)
            running = _running_jobs_from_db(conn)
            conn.close()
        ages = [a for a in (live_age, sql_age) if a is not None]
        worst = max(ages) if ages else None
        return worst, live_age, running

    worst, live_age, running = _measure()
    if worst is not None and worst > required_fresh_min:
        refresh_bus_live_export()
        worst, live_age, running = _measure()

    if required_fresh_min <= 0 and BUS_DB.is_file():
        fresh = True
    elif worst is None:
        fresh = False
    else:
        fresh = worst <= required_fresh_min

    return {
        "fresh": fresh,
        "age_min": worst,
        "live_age_min": live_age,
        "running_jobs": running,
        "generated_at": _bus_live_generated_at(),
    }


def _session_running_truth(truth: dict[str, Any], session: str) -> bool:
    return any(
        (j.get("to_session") or "") == session
        for j in truth.get("running_jobs") or []
    )


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
            if age is not None and age > WIP_STALE_MIN and not has_output_marker(
                events, tid, marker
            ):
                truth = ensure_fresh_bus_truth(required_fresh_min=age, bus_db=bus_db)
                if not truth.get("fresh"):
                    continue
                if not _session_running_truth(truth, "pmo"):
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
    pmo_status = (pmo.get("status") or "").lower()
    if pmo_status in ("in_progress", "blocked"):
        age = minutes_since(pmo.get("ts", ""))
        stale_marker = f"{MARKER_PREFIX}pmo-stale-no-worker"
        unblocked_marker = f"{MARKER_PREFIX}pmo-unblocked-running"
        if age is not None and age > WIP_STALE_MIN:
            truth = ensure_fresh_bus_truth(required_fresh_min=age, bus_db=bus_db)
            if not truth.get("fresh"):
                pass  # stale snapshot — never emit "no job for Xm" from old data
            elif _session_running_truth(truth, "pmo"):
                pmo_jobs = [
                    j
                    for j in truth.get("running_jobs") or []
                    if (j.get("to_session") or "") == "pmo"
                ]
                short = (
                    pmo_jobs[0].get("short_job_id")
                    or pmo_jobs[0].get("job_id", "")
                    if pmo_jobs
                    else ""
                )
                if pmo_status == "blocked" and not has_output_marker(
                    events, "PMO-001", unblocked_marker
                ):
                    append({
                        **base,
                        "event": "task_updated",
                        "task_id": "PMO-001",
                        "task": pmo.get("task", "PMO triage"),
                        "status": "in_progress",
                        "owner": "PMO",
                        "output": (
                            f"{unblocked_marker} {short} executing on bus "
                            f"(fresh snapshot age {truth.get('age_min', 0):.1f}m)."
                        ),
                    })
                    n += 1
            elif (
                pmo_status == "in_progress"
                and not has_output_marker(events, "PMO-001", stale_marker)
            ):
                append({
                    **base,
                    "event": "task_updated",
                    "task_id": "PMO-001",
                    "task": pmo.get("task", "PMO triage"),
                    "status": "blocked",
                    "owner": "PMO",
                    "output": (
                        f"{stale_marker} No PMO job on bus for {int(age)}m (POL-002). "
                        f"Bus snapshot age {truth.get('age_min', 0):.1f}m. "
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