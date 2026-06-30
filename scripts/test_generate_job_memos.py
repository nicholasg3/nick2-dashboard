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
        catalog = {
            "ISSUE-80": {
                "problem": "Dashboard lags reality and memos are too thin.",
                "doing": "Harden live sync.",
                "steps": ["Reconcile", "Export bus-live", "Witness"],
                "witness": "witness exits 0",
            }
        }
        text = gjm.situation_paragraph(
            pmo_item=pmo["ISSUE-80"],
            ledger_tid="ISSUE-80",
            work=catalog["ISSUE-80"],
        )
        self.assertIn("#2", text)
        self.assertIn("0.75", text)
        self.assertIn("Dashboard lags", text)

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
            catalog = root / "job_work_catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ISSUE-80": {
                                "problem": "Dashboard sync lags.",
                                "doing": "Harden reconcile path.",
                                "steps": ["Reconcile", "Export", "Witness"],
                                "witness": "witness exits 0",
                                "touch_paths": ["scripts/reconcile-ledger.py"],
                            }
                        }
                    }
                ),
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

            old_ledger, old_pmo, old_db, old_cat = (
                gjm.LEDGER,
                gjm.PMO_RESULT,
                gjm.BUS_DB,
                gjm.WORK_CATALOG,
            )
            gjm.LEDGER = ledger
            gjm.PMO_RESULT = pmo
            gjm.BUS_DB = db
            gjm.WORK_CATALOG = catalog
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
                gjm.LEDGER, gjm.PMO_RESULT, gjm.BUS_DB, gjm.WORK_CATALOG = (
                    old_ledger,
                    old_pmo,
                    old_db,
                    old_cat,
                )

            self.assertIn("WHAT IT'S DOING", body)
            self.assertIn("Harden reconcile", body)
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
            + "PMO dispatched worker_model fix. Rank #1.\n\n"
            "## WHAT IT'S DOING\n\n"
            + "Patch bus.py model resolution.\n\n**Steps:**\n1. Reproduce\n2. Patch\n\n"
            + "**Done when:** `pytest exits 0`\n\n"
            "## WHERE IT STANDS\n\nExecuting on nick2-dashboard.\n\n"
            "## EFFORT & COST\n\n- **Time:** x\n\n## LINKS\n\n- ledger\n"
        )
        self.assertEqual(gjm.validate_job_memo(good, "JOB-1"), [])


if __name__ == "__main__":
    unittest.main()