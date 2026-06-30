#!/usr/bin/env python3
"""Unit tests for generate_job_memos narrative sections."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import generate_job_memos as gjm


class GenerateJobMemosTests(unittest.TestCase):
    def test_situation_includes_pmo_rank(self):
        pmo = {
            "ISSUE-80": {
                "rank": 2,
                "roi": 0.75,
                "area": "agent-infra",
                "title": "Dashboard reconcile + memos",
                "objective": "ISSUE-080: Harden POL-003",
            }
        }
        text = gjm.situation_paragraph(
            objective="ISSUE-080: Harden POL-003 dashboard-live sync",
            pmo_item=pmo["ISSUE-80"],
            ledger_tid="ISSUE-80",
            ledger_task={"task": "Nick2 dashboard reconcile"},
            parent_dispatch={"output": "pmo-dispatch:queued 3 issues"},
        )
        self.assertIn("#2", text)
        self.assertIn("0.75", text)
        self.assertIn("DISPATCH-001", text)

    def test_where_it_stands_flags_duplicates(self):
        row = {
            "job_id": "JOB-20260630-573",
            "status": "running",
            "worker_status": "executing",
            "repo": "nick2-dashboard",
            "updated_at": "2026-06-30T14:33:37Z",
            "hold_reason": "",
            "to_session": "coding_worker",
            "branch": "job/573",
            "created_at": "2026-06-30T14:30:00Z",
            "report_path": None,
        }
        siblings = [
            ("JOB-20260630-574", "queued"),
            ("JOB-20260630-584", "held"),
        ]
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE jobs (job_id TEXT, status TEXT, worker_status TEXT, repo TEXT,
               updated_at TEXT, hold_reason TEXT, to_session TEXT, branch TEXT,
               created_at TEXT, report_path TEXT)"""
        )
        conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
        db_row = conn.execute("SELECT * FROM jobs").fetchone()
        text = gjm.where_it_stands(
            row=db_row,
            started="2026-06-30T14:30:00Z",
            siblings=siblings,
            repo_claim=None,
            report=None,
        )
        self.assertIn("Duplicate packets", text)
        self.assertIn("JOB-574", text)

    def test_ledger_task_for_job_finds_issue(self):
        events = [
            {
                "task_id": "ISSUE-80",
                "output": "pmo-dispatch:dispatched JOB-20260630-573 to coding_worker",
                "artifacts": ["agent-bus JOB-20260630-573"],
            }
        ]
        tid = gjm.ledger_task_for_job("JOB-20260630-573", events)
        self.assertEqual(tid, "ISSUE-80")

    def test_job_memo_body_writes_mission_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "logs" / "ceo-ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                json.dumps(
                    {
                        "task_id": "ISSUE-80",
                        "task": "Dashboard reconcile",
                        "output": "dispatched JOB-20260630-573",
                        "artifacts": ["agent-bus JOB-20260630-573"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            pmo = root / "pmo_001_result.json"
            pmo.write_text(
                json.dumps(
                    {
                        "top_issues": [
                            {
                                "rank": 2,
                                "issue_number": 80,
                                "roi": 0.75,
                                "area": "agent-infra",
                                "title": "Dashboard reconcile",
                                "objective": "ISSUE-080: Harden POL-003",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            db = root / "jobs.sqlite"
            conn = sqlite3.connect(db)
            conn.execute(
                """CREATE TABLE jobs (
                    job_id TEXT, objective TEXT, status TEXT, worker_status TEXT,
                    to_session TEXT, repo TEXT, branch TEXT, updated_at TEXT,
                    created_at TEXT, hold_reason TEXT, packet_path TEXT,
                    report_path TEXT, feature_name TEXT)"""
            )
            conn.execute(
                """INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "JOB-20260630-573",
                    "ISSUE-080: Harden POL-003 dashboard-live sync",
                    "running",
                    "executing",
                    "coding_worker",
                    "nick2-dashboard",
                    "job/573",
                    "2026-06-30T14:33:37Z",
                    "2026-06-30T14:30:00Z",
                    "",
                    "",
                    "",
                    "issue-080-harden-pol-003-dashboard-live",
                ),
            )
            conn.commit()
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM jobs").fetchone()

            old_ledger, old_pmo, old_db = gjm.LEDGER, gjm.PMO_RESULT, gjm.BUS_DB
            gjm.LEDGER = ledger
            gjm.PMO_RESULT = pmo
            gjm.BUS_DB = db
            try:
                events = gjm.load_ledger()
                body = gjm.job_memo_body(
                    row,
                    {},
                    events=events,
                    tasks=gjm.task_state(events),
                    pmo_index=gjm.load_pmo_index(),
                    conn=conn,
                )
            finally:
                gjm.LEDGER, gjm.PMO_RESULT, gjm.BUS_DB = old_ledger, old_pmo, old_db

            self.assertIn("PMO-001 triage ranked this **#2**", body)
            self.assertIn("ISSUE-80", body)
            self.assertIn("WHERE IT STANDS", body)
            conn.close()


    def test_validate_job_memo_rejects_boilerplate(self):
        bad = "# JOB-1\n\n## STATUS\n\n- **Bus status:** running\n"
        errs = gjm.validate_job_memo(bad, "JOB-1")
        self.assertTrue(any("missing" in e for e in errs))

    def test_validate_job_memo_accepts_rich_body(self):
        good = (
            "# JOB-1\n\n## SITUATION\n\n"
            + "PMO-001 triage ranked this #2 after analysis completed.\n\n"
            "## WHERE IT STANDS\n\nExecuting on nick2-dashboard.\n\n"
            "## EFFORT & COST\n\n- **Time:** x\n\n## LINKS\n\n- ledger\n"
        )
        self.assertEqual(gjm.validate_job_memo(good, "JOB-1"), [])


if __name__ == "__main__":
    unittest.main()