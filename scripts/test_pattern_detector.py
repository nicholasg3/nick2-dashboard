#!/usr/bin/env python3
"""Tests for pattern_detector recurrence → pattern_flag."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import pattern_detector as pd  # noqa: E402

# Isolate the role-memory source so the live sessions dir cannot leak real
# memory flags into the isolated-ledger count assertions.
pd.SESSIONS_ROOT = Path(tempfile.mkdtemp(prefix="pd-test-sessions-"))

SGT = timezone(timedelta(hours=8))


def _ts(minutes_ago: int) -> str:
    return (
        datetime.now(SGT) - timedelta(minutes=minutes_ago)
    ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def test_flags_on_third_reconcile_marker() -> None:
    with tempfile.TemporaryDirectory() as td:
        ledger = Path(td) / "ledger.jsonl"
        lines = []
        for i in range(3):
            lines.append(
                {
                    "event": "task_updated",
                    "task_id": "PMO-001",
                    "output": f"reconcile-bus:pmo-stale-no-worker attempt {i}",
                    "ts": _ts(60 - i * 10),
                }
            )
        ledger.write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )
        events = pd.load_ledger(ledger)
        flags = pd.pattern_flags_to_emit(events)
        assert len(flags) == 1, flags
        assert flags[0]["signature"] == "pmo-stale-no-worker"
        assert flags[0]["count"] == 3


def test_skips_if_already_flagged() -> None:
    with tempfile.TemporaryDirectory() as td:
        ledger = Path(td) / "ledger.jsonl"
        lines = [
            {
                "event": "pattern_flag",
                "task_id": "PMO-001",
                "signature": "pmo-stale-no-worker",
                "ts": _ts(5),
            }
        ]
        for i in range(3):
            lines.append(
                {
                    "event": "task_updated",
                    "task_id": "PMO-001",
                    "output": "reconcile-bus:pmo-stale-no-worker",
                    "ts": _ts(30 - i),
                }
            )
        ledger.write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )
        events = pd.load_ledger(ledger)
        flags = pd.pattern_flags_to_emit(events)
        assert flags == []


def test_emit_appends_via_callback() -> None:
    with tempfile.TemporaryDirectory() as td:
        ledger = Path(td) / "ledger.jsonl"
        lines = [
            {
                "event": "task_updated",
                "task_id": "PMO-001",
                "output": "reconcile-bus:pmo-stale-no-worker",
                "ts": _ts(50),
            },
            {
                "event": "task_updated",
                "task_id": "PMO-001",
                "output": "reconcile-bus:pmo-stale-no-worker",
                "ts": _ts(40),
            },
            {
                "event": "task_updated",
                "task_id": "PMO-001",
                "output": "reconcile-bus:pmo-stale-no-worker",
                "ts": _ts(30),
            },
        ]
        ledger.write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
        )
        events = pd.load_ledger(ledger)
        appended: list[dict] = []

        def capture(ev: dict) -> bool:
            appended.append(ev)
            return True

        n = pd.emit_pattern_flags(events, {}, capture)
        assert n == 1
        assert appended[0]["event"] == "pattern_flag"


def main() -> int:
    test_flags_on_third_reconcile_marker()
    test_skips_if_already_flagged()
    test_emit_appends_via_callback()
    print("test_pattern_detector: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())