#!/usr/bin/env python3
"""Unit tests for POL-003 dashboard_honesty drift detection."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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


def test_stale_snapshot_skips_pmo_blocked_verdict() -> None:
    """Never emit 'no job for Xm' when bus snapshot is older than X."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        ledger = td_path / "ledger.jsonl"
        bus = td_path / "bus.sqlite"
        live = td_path / "bus-live.json"
        now = datetime.now(timezone.utc)
        ledger_old = (now - timedelta(minutes=65)).astimezone(
            timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        stale_ts = (now - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ledger.write_text(
            json.dumps(
                {
                    "task_id": "PMO-001",
                    "status": "in_progress",
                    "task": "Triage issues",
                    "output": "Ranking backlog",
                    "ts": ledger_old,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        _make_bus(
            bus,
            [
                (
                    "JOB-20260630-792",
                    "running",
                    stale_ts,
                    "pmo",
                    "ai-agents-workspace",
                ),
            ],
        )
        live.write_text(
            json.dumps(
                {
                    "generated_at": stale_ts,
                    "running": [],
                    "queued": [],
                    "held": [],
                }
            ),
            encoding="utf-8",
        )
        events = dh.load_events(ledger)
        tasks = dh.task_state(events)
        appended: list[dict] = []

        def capture(ev: dict) -> bool:
            appended.append(ev)
            return True

        import dashboard_honesty as dh_mod

        old_live = dh_mod.BUS_LIVE
        old_db = dh_mod.BUS_DB
        try:
            dh_mod.BUS_LIVE = live
            dh_mod.BUS_DB = bus
            n = dh.reconcile_bus(events, tasks, {}, capture, bus_db=bus)
        finally:
            dh_mod.BUS_LIVE = old_live
            dh_mod.BUS_DB = old_db

        blocked = [e for e in appended if e.get("status") == "blocked"]
        assert n == 0 or not blocked, f"stale snapshot must not emit blocked: {appended}"


def test_fresh_snapshot_unblocks_when_pmo_running() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        ledger = td_path / "ledger.jsonl"
        bus = td_path / "bus.sqlite"
        live = td_path / "bus-live.json"
        now_dt = datetime.now(timezone.utc)
        now = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        ledger_old = (now_dt - timedelta(minutes=65)).astimezone(
            timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        ledger.write_text(
            json.dumps(
                {
                    "task_id": "PMO-001",
                    "status": "blocked",
                    "task": "Triage issues",
                    "output": "reconcile-bus:pmo-stale-no-worker stalled",
                    "ts": ledger_old,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        _make_bus(
            bus,
            [
                (
                    "JOB-20260630-792",
                    "running",
                    now,
                    "pmo",
                    "ai-agents-workspace",
                ),
            ],
        )
        live.write_text(
            json.dumps(
                {
                    "generated_at": now,
                    "running": [
                        {
                            "job_id": "JOB-20260630-792",
                            "short_job_id": "JOB-792",
                            "to_session": "pmo",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        events = dh.load_events(ledger)
        tasks = dh.task_state(events)
        appended: list[dict] = []

        def capture(ev: dict) -> bool:
            appended.append(ev)
            return True

        import dashboard_honesty as dh_mod

        old_live = dh_mod.BUS_LIVE
        old_db = dh_mod.BUS_DB
        try:
            dh_mod.BUS_LIVE = live
            dh_mod.BUS_DB = bus
            dh.reconcile_bus(events, tasks, {}, capture, bus_db=bus)
        finally:
            dh_mod.BUS_LIVE = old_live
            dh_mod.BUS_DB = old_db

        unblocked = [e for e in appended if e.get("status") == "in_progress"]
        assert unblocked, f"expected in_progress when JOB-792 running: {appended}"


def test_write_guard_blocked_vs_executing() -> None:
    import ledger_write_guard as lwg

    truth = {
        "fresh": True,
        "age_min": 0.5,
        "running_jobs": [
            {
                "job_id": "JOB-20260630-792",
                "short_job_id": "JOB-792",
                "to_session": "pmo",
            }
        ],
    }
    ev = {
        "event": "task_updated",
        "task_id": "PMO-001",
        "status": "blocked",
        "output": "reconcile-bus:pmo-stale-no-worker No PMO job on bus for 63m",
    }
    out = lwg.guard_ledger_event(ev, bus_truth=truth)
    assert out is not None
    assert out["status"] == "in_progress"
    assert "JOB-792" in out["output"]


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
    test_stale_snapshot_skips_pmo_blocked_verdict()
    test_fresh_snapshot_unblocks_when_pmo_running()
    test_write_guard_blocked_vs_executing()
    test_ledger_event_for_job_finish()
    print("test_dashboard_honesty: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())