#!/usr/bin/env python3
"""Unit tests for CEO reflection admission and bottleneck rules (POL-010)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import ceo_reflect as cr  # noqa: E402


class CeoReflectTests(unittest.TestCase):
    def _ctx(
        self,
        *,
        running: int = 0,
        held: int = 0,
        coding: int = 0,
        budget_remaining: float = 20.0,
        weekly: float = 20.0,
    ) -> dict:
        return {
            "counts": {
                "running": running,
                "held": held,
                "queued": 0,
                "blocked": 0,
                "coding_running": coding,
            },
            "ledger_base": {
                "budget_remaining_usd": budget_remaining,
                "weekly_budget_usd": weekly,
            },
            "tasks": {},
            "triage": {},
            "bus_rows": [],
            "repo_claims": [],
            "bus_live": {},
            "issue_tasks": {},
            "memories_tail": [],
            "ts": "2026-06-30T12:00:00Z",
        }

    def test_admission_zero_when_capacity_full(self) -> None:
        ctx = self._ctx(running=cr.MAX_PARALLEL)
        bn = [{"type": "capacity_full", "severity": "high"}]
        adm = cr.compute_admission(ctx, bn)
        self.assertEqual(adm["max_new_delegations"], 0)
        self.assertEqual(adm["max_retries"], 0)

    def test_admission_one_slot_when_clear(self) -> None:
        ctx = self._ctx(running=1, coding=1)
        adm = cr.compute_admission(ctx, [])
        self.assertEqual(adm["max_new_delegations"], 1)

    def test_admission_zero_when_coding_saturated(self) -> None:
        ctx = self._ctx(running=2, coding=cr.MAX_CODING_PARALLEL)
        adm = cr.compute_admission(ctx, [])
        self.assertEqual(adm["max_new_delegations"], 0)

    def test_detect_dispatch_blocked(self) -> None:
        ctx = self._ctx()
        ctx["issue_tasks"] = {
            "ISSUE-80": {
                "status": "queued",
                "output": "pmo-dispatch:bus submit failed (will retry): timeout",
                "artifacts": [],
                "ts": "2026-06-30T12:00:00Z",
            }
        }
        types = {b["type"] for b in cr.detect_bottlenecks(ctx)}
        self.assertIn("dispatch_blocked", types)

    def test_admission_allows_retry_for_dispatch_blocked(self) -> None:
        ctx = self._ctx(running=0)
        bn = [{"type": "dispatch_blocked", "severity": "high", "target": "ISSUE-80"}]
        adm = cr.compute_admission(ctx, bn)
        self.assertEqual(adm["max_retries"], 1)

    def test_run_reflect_dry_run(self) -> None:
        with mock.patch.object(cr, "gather_context", return_value=self._ctx()):
            with mock.patch.object(cr, "detect_bottlenecks", return_value=[]):
                with mock.patch.object(cr, "write_artifacts") as wa:
                    out = cr.run_reflect(dry_run=True)
        self.assertEqual(out["mode"], "ceo_reflect")
        wa.assert_not_called()


if __name__ == "__main__":
    unittest.main()