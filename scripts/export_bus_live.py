#!/usr/bin/env python3
"""Export reports/bus-live.json from agent-bus jobs.sqlite (run on droplet)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "bus-live.json"
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
BUS_DB = Path(
    os.environ.get(
        "AGENT_BUS_DB",
        Path.home() / "ai-agents-workspace" / "agent-bus" / "jobs.sqlite",
    )
)


def short_job_id(job_id: str) -> str:
    m = re.match(r"^JOB-(\d{8})-(\d+)$", job_id or "")
    return f"JOB-{m.group(2)}" if m else (job_id or "")


def load_ledger_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def mission_for_job(job_id: str, events: list[dict]) -> str | None:
    short = short_job_id(job_id)
    needles = (job_id, short, f"`{job_id}`")
    for ev in reversed(events):
        tid = ev.get("task_id") or ""
        if not tid or tid.startswith("FOCUS-"):
            continue
        blob = " ".join(
            str(ev.get(k) or "")
            for k in ("output", "task", "artifacts")
        )
        if not any(n in blob for n in needles):
            continue
        if re.match(r"^(SYS|PMO|P-|POL-|LIT-|DEC-)", tid):
            return tid
    return None


def load_pmo_focus() -> dict:
    if not LEDGER.exists():
        return {}
    pmo = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("task_id") == "PMO-001":
            pmo = ev
    if not pmo:
        return {}
    return {
        "task_id": "PMO-001",
        "task": pmo.get("task"),
        "ledger_status": pmo.get("status"),
        "since": pmo.get("ts"),
    }


def running_started_at(job_id: str) -> str | None:
    run_file = BUS_DB.parent / "running" / f"{job_id}.json"
    if not run_file.is_file():
        return None
    try:
        data = json.loads(run_file.read_text(encoding="utf-8"))
        return data.get("started_at") or None
    except (json.JSONDecodeError, OSError):
        return None


def row_job(row: sqlite3.Row, events: list[dict]) -> dict:
    lane = (row["display_name"] or "").split("[")[-1].split("]")[0].strip() if row["display_name"] else ""
    job_id = row["job_id"]
    feature = (row["feature_name"] or "").strip()
    if not feature and row["display_name"]:
        feature = row["display_name"].split("[")[0].strip()
    objective = (row["objective"] or "").strip()
    preview = objective.split("\n\n")[0].replace("\n", " ")[:160] if objective else ""
    mission_id = mission_for_job(job_id, events)
    started = running_started_at(job_id) if row["status"] == "running" else None
    return {
        "job_id": job_id,
        "short_job_id": short_job_id(job_id),
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "started_at": started or row["created_at"] or "",
        "display_name": row["display_name"] or job_id,
        "feature_name": feature,
        "objective_preview": preview,
        "lane": lane or row["to_session"],
        "repo": row["repo"] or "",
        "to_session": row["to_session"],
        "worker_status": row["worker_status"] or row["status"],
        "hold_reason": row["hold_reason"] or "",
        "status": row["status"],
        "branch": row["branch"] or "",
        "mission_id": mission_id or "",
        "memo_path": f"memos/jobs/{job_id}.md",
    }


def _visible_rows(conn: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from generate_job_memos import is_dashboard_visible_row  # noqa: E402
    except ImportError:
        is_dashboard_visible_row = lambda r: True  # type: ignore[assignment,misc]
    return [r for r in conn.execute(sql) if is_dashboard_visible_row(r)]


def export_from_db(db: Path) -> dict:
    events = load_ledger_events()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    running = [row_job(r, events) for r in _visible_rows(
        conn, "SELECT * FROM jobs WHERE status='running' ORDER BY updated_at DESC"
    )]
    queued = [row_job(r, events) for r in _visible_rows(
        conn, "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at ASC"
    )]
    held = [row_job(r, events) for r in _visible_rows(
        conn, "SELECT * FROM jobs WHERE status='held' ORDER BY updated_at DESC"
    )]
    recent_completed = [row_job(r, events) for r in conn.execute(
        """SELECT * FROM jobs WHERE status='completed' ORDER BY updated_at DESC LIMIT 6"""
    )]
    conn.close()

    pmo_focus = load_pmo_focus()
    pmo_jobs = [j for j in running + queued + held if j.get("to_session") == "pmo"]
    if pmo_focus:
        if any(j["status"] == "running" for j in pmo_jobs):
            pmo_focus["bus_state"] = "executing"
            pmo_focus["note"] = "PMO worker running on agent-bus"
        elif held and any(j["to_session"] == "pmo" for j in held):
            pmo_focus["bus_state"] = "held"
            pmo_focus["note"] = held[0].get("hold_reason") or "Waiting on repo lock or dependency"
        elif queued and any(j["to_session"] == "pmo" for j in queued):
            pmo_focus["bus_state"] = "queued"
            pmo_focus["note"] = "PMO job queued — not executing yet"
        elif pmo_focus.get("ledger_status") == "in_progress":
            pmo_focus["bus_state"] = "stale"
            pmo_focus["note"] = "Ledger says in_progress but no PMO job on the bus — triage not actively running"
        else:
            pmo_focus["bus_state"] = "idle"

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "running": running,
        "queued": queued,
        "held": held,
        "recent_completed": recent_completed,
        "pmo_focus": pmo_focus,
    }


def main() -> None:
    if BUS_DB.is_file():
        payload = export_from_db(BUS_DB)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {OUT.relative_to(ROOT)}")
        try:
            from generate_job_memos import main as gen_job_memos

            gen_job_memos()
        except Exception as exc:
            print(f"generate_job_memos skipped: {exc}", file=sys.stderr)
        return
    if OUT.is_file():
        print(
            f"Skipped {OUT.relative_to(ROOT)} — no agent-bus DB; keeping existing export"
        )
        return
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "running": [],
        "queued": [],
        "held": [],
        "recent_completed": [],
        "pmo_focus": load_pmo_focus(),
        "note": "agent-bus DB not found — run on droplet",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} (empty stub — no DB, no prior file)")


if __name__ == "__main__":
    main()