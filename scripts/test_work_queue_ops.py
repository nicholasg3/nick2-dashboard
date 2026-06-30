#!/usr/bin/env python3
"""Tests for work queue remove / defer detection."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import work_queue_ops as wqo  # noqa: E402


class WorkQueueOpsTests(unittest.TestCase):
    def test_looks_remove_take_out(self) -> None:
        self.assertTrue(wqo.looks_remove_instruction("please take it out of the queue"))

    def test_looks_remove_negative(self) -> None:
        self.assertFalse(wqo.looks_remove_instruction("prioritize issue 42 first"))

    def test_deferred_includes_issue_24(self) -> None:
        self.assertIn("ISSUE-24", wqo.deferred_task_ids())


if __name__ == "__main__":
    unittest.main()