#!/usr/bin/env python3
"""Unit tests for job_catalog landed + witness parsing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import job_catalog as jc  # noqa: E402


class JobCatalogTests(unittest.TestCase):
    def test_witness_commands_or_alternative(self) -> None:
        w = (
            "python3 agent-bus/scripts/test_worker_model.py (or test_dispatch_policy.py) "
            "exits 0"
        )
        cmds = jc.witness_commands(w)
        self.assertIn("python3 agent-bus/scripts/test_worker_model.py", cmds)
        self.assertIn("python3 agent-bus/scripts/test_dispatch_policy.py", cmds)

    def test_skip_decision_gated(self) -> None:
        entry = {"doing": "**Nick's queue — not running on agents.**", "witness": "Decision recorded"}
        self.assertTrue(jc.is_decision_gated({}, entry))

    def test_assess_landed_routing_mock(self) -> None:
        item = {"repo": "ai-agents-workspace", "task_id": "ISSUE-ROUTING-001"}
        entry = {
            "shipped_on_main": True,
            "witness": "python3 agent-bus/scripts/test_dispatch_policy.py exits 0",
            "touch_paths": [
                "agent-bus/scripts/worker_model.py",
                "references/model-routing.yaml",
            ],
        }
        with mock.patch.object(jc, "paths_exist", return_value=(True, [])):
            with mock.patch.object(jc, "run_witness", return_value=(True, "exit 0")):
                v = jc.assess_landed("ISSUE-ROUTING-001", item, entry)
        self.assertTrue(v["landed"])


if __name__ == "__main__":
    unittest.main()