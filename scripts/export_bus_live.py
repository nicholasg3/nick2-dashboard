#!/usr/bin/env python3
"""Export reports/bus-live.json from agent-bus jobs.sqlite (run on droplet)."""
from __future__ import annotations

import json
import os
import sqlite3
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


def row_job(row: sqlite3.Row) -> dict:
    lane = (row["display_name"] or "").split("[")[-1].split("]")[0].strip() if row["display_name"] else ""
    return {
        "job_id": row["job_id"],
        "display_name": row["display_name"] or row["job_id"],
        "lane": lane or row["to_session"],
        "repo": row["repo"] or "",
        "to_session": row["to_session"],
        "worker_status": row["worker_status"] or row["status"],
        "hold_reason": row["hold_reason"] or "",
        "status": row["status"],
    }


def export_from_db(db: Path) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    running = [row_job(r) for r in conn.execute(
        """SELECT * FROM jobs WHERE status='running' ORDER BY updated_at DESC"""
    )]
    queued = [row_job(r) for r in conn.execute(
        """SELECT * FROM jobs WHERE status='queued' ORDER BY created_at ASC"""
    )]
    held = [row_job(r) for r in conn.execute(
        """SELECT * FROM jobs WHERE status='held' ORDER BY updated_at DESC"""
    )]
    recent_completed = [row_job(r) for r in conn.execute(
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