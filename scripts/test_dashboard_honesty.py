#!/usr/bin/env python3
"""Unit tests for POL-003 dashboard_honesty drift detection."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import dashboard_honesty as dh  # noqa: E402


def _make_bus(db: Path, jobs: list[tuple]) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE jobs (
        job_id TEXT PRIMARY KEY, status TEXT, updated_at TEXT,
        to_session TEXT, repo TEXT, created_at TEXT)"""
    )
    for row in jobs:
        conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?)",
            (*row, row[2]),
        )
    conn.commit()
    conn.close()


def test_detects_completed_job_cited_as_executing() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        ledger = td_path / "ledger.jsonl"
        bus = td_path / "bus.sqlite"
        ledger.write_text(
            json.dumps(
                {
                    "task_id": "SYS-002",
                    "status": "in_progress",
                    "output": "JOB-924 executing on droplet",
                    "ts": "2026-06-30T20:00:00+08:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        _make_bus(
            bus,
            [
                (
                    "JOB-20260630-924",
                    "completed",
                    "2026-06-30T12:14:00Z",
                    "dashboard_worker",
                    "nick2-dashboard",
                ),
            ],
        )
        issues = dh.detect_drift(
            dh.load_events(ledger), ledger_path=ledger, bus_db=bus
        )
        assert issues, f"expected drift, got {issues}"


def test_no_drift_after_marker() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        ledger = td_path / "ledger.jsonl"
        bus = td_path / "bus.sqlite"
        ledger.write_text(
            json.dumps(
                {
                    "task_id": "SYS-002",
                    "status": "completed",
                    "output": "reconcile-bus:SYS-002-job-924-done JOB done",
                    "ts": "2026-06-30T20:34:00+08:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        _make_bus(
            bus,
            [
                (
                    "JOB-20260630-924",
                    "completed",
                    "2026-06-30T12:14:00Z",
                    "dashboard_worker",
                    "nick2-dashboard",
                ),
            ],
        )
        issues = dh.detect_drift(
            dh.load_events(ledger), ledger_path=ledger, bus_db=bus
        )
        assert not issues, issues


def test_ledger_event_for_job_finish() -> None:
    events = [
        {
            "task_id": "SYS-002",
            "task": "Make the dashboard live",
            "output": "Dispatched JOB-20260630-924",
            "owner": "dashboard_worker",
        }
    ]
    ev = dh.ledger_event_for_job_finish(
        "JOB-20260630-924",
        {"to": "dashboard_worker", "objective": "live sync"},
        {"status": "completed", "bottom_line": "Shipped live API."},
        events,
    )
    assert ev is not None
    assert "bus-finish:JOB-20260630-924" in ev["output"]
    assert ev["status"] == "completed"


def main() -> int:
    test_detects_completed_job_cited_as_executing()
    test_no_drift_after_marker()
    test_ledger_event_for_job_finish()
    print("test_dashboard_honesty: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())