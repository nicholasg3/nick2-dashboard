#!/usr/bin/env python3
"""Tests for cron_health heartbeat witness."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import cron_health as ch  # noqa: E402


def test_fresh_heartbeat_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        hb = Path(td) / "sync-heartbeat.txt"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        hb.write_text(ts, encoding="utf-8")
        old = ch.HEARTBEAT
        try:
            ch.HEARTBEAT = hb
            assert ch.check(max_age_min=20) == []
        finally:
            ch.HEARTBEAT = old


def test_stale_heartbeat_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        hb = Path(td) / "sync-heartbeat.txt"
        stale = datetime.now(timezone.utc) - timedelta(minutes=45)
        hb.write_text(stale.strftime("%Y-%m-%dT%H:%M:%SZ"), encoding="utf-8")
        old = ch.HEARTBEAT
        try:
            ch.HEARTBEAT = hb
            issues = ch.check(max_age_min=20)
            assert issues and "stale" in issues[0].lower()
        finally:
            ch.HEARTBEAT = old


def main() -> int:
    test_fresh_heartbeat_passes()
    test_stale_heartbeat_fails()
    print("test_cron_health: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())