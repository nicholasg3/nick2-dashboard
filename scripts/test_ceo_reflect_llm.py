#!/usr/bin/env python3
"""Tests for CEO LLM reflection parsing and admission validation."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import ceo_reflect_llm as crl  # noqa: E402


class CeoReflectLlmTests(unittest.TestCase):
    def test_parse_llm_json_plain(self) -> None:
        raw = json.dumps({"situation_summary": "Bus is full.", "root_causes": ["claims"]})
        out = crl.parse_llm_json(raw)
        self.assertEqual(out["situation_summary"], "Bus is full.")

    def test_parse_llm_json_fence(self) -> None:
        raw = '```json\n{"situation_summary": "ok"}\n```'
        out = crl.parse_llm_json(raw)
        self.assertEqual(out["situation_summary"], "ok")

    def test_validate_delegate_rejects_deferred(self) -> None:
        ctx = {
            "triage": {
                "top_issues": [
                    {
                        "task_id": "ISSUE-24",
                        "dispatch": False,
                        "defer_reason": "Nick personal queue",
                    }
                ]
            },
            "tasks": {},
        }
        err = crl.validate_delegate("ISSUE-24", ctx, {"max_new_delegations": 1})
        self.assertIsNotNone(err)
        self.assertIn("deferred", err.lower())

    def test_should_run_llm_forced(self) -> None:
        with mock.patch.object(crl, "llm_enabled", return_value=True):
            ok, _ = crl.should_run_llm(force=True)
        self.assertTrue(ok)

    def test_interval_blocks_second_run(self) -> None:
        with mock.patch.object(crl, "llm_enabled", return_value=True):
            with mock.patch.object(crl, "interval_minutes", return_value=60):
                with mock.patch.object(
                    crl,
                    "load_state",
                    return_value={"last_llm_at": crl._now()},
                ):
                    ok, reason = crl.should_run_llm(force=False)
        self.assertFalse(ok)
        self.assertIn("interval", reason)


if __name__ == "__main__":
    unittest.main()