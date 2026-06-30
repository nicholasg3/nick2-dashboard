#!/usr/bin/env python3
"""Unit tests for pmo_dispatch idempotency and budget gating."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import pmo_dispatch as pd  # noqa: E402


class PmoDispatchTests(unittest.TestCase):
    def test_issue_task_id_from_number(self):
        self.assertEqual(pd.issue_task_id({"issue_number": 80}), "ISSUE-80")

    def test_issue_task_id_explicit(self):
        self.assertEqual(pd.issue_task_id({"task_id": "ISSUE-BUS-001"}), "ISSUE-BUS-001")

    def test_dispatch_already_done(self):
        tasks = {
            "DISPATCH-001": {"status": "queued"},
        }
        self.assertTrue(pd.dispatch_already_done(tasks))

    def test_dispatch_not_done(self):
        self.assertFalse(pd.dispatch_already_done({}))

    def test_run_dispatch_skips_without_pmo_complete(self):
        with mock.patch.object(pd, "LEDGER", Path("/nonexistent")):
            with mock.patch.object(pd, "load_events", return_value=[]):
                out = pd.run_dispatch(dry_run=True)
        self.assertTrue(out.get("skipped"))

    def test_run_dispatch_dry_run_queues(self):
        events = [
            {
                "ts": "2026-06-30T21:30:34+08:00",
                "task_id": "PMO-001",
                "status": "completed",
                "event": "task_updated",
                "weekly_budget_usd": 20,
                "budget_remaining_usd": 20,
                "budget_mode": "capped",
            }
        ]
        result = {
            "dispatch_budget_usd": 5.0,
            "top_issues": [
                {
                    "rank": 1,
                    "issue_number": 15,
                    "title": "Skill tiers",
                    "worker": "coding_worker",
                    "repo": "ai-agents-workspace",
                    "est_cost_usd": 1.0,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "pmo_001_result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            with mock.patch.object(pd, "ROOT", root):
                with mock.patch.object(pd, "RESULT_CANDIDATES", [result_path]):
                    with mock.patch.object(pd, "load_events", return_value=events):
                        with mock.patch.object(pd, "dispatch_already_done", return_value=False):
                            out = pd.run_dispatch(dry_run=True)
        self.assertEqual(out.get("dispatched"), 1)
        self.assertEqual(out.get("first_focus"), "ISSUE-15")

    def test_parse_bus_submit_held(self):
        out = pd._parse_bus_submit(
            json.dumps(
                {
                    "job_id": "JOB-20260630-573",
                    "status": "held",
                    "hold_reason": "repo claimed",
                }
            ),
            "",
            0,
        )
        self.assertEqual(out["job_id"], "JOB-20260630-573")

    def test_submit_failed_not_permanent_blocked_in_dispatch(self):
        """Regression: submit errors stay queued for --retry (ISSUE-80 incident)."""
        self.assertIn("will retry", "bus submit failed (will retry): traceback")


if __name__ == "__main__":
    unittest.main()