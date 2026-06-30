#!/usr/bin/env python3
"""Runnable witness for POL-003 dashboard honesty (jesus-ralph gate)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import cron_health as ch  # noqa: E402
import dashboard_honesty as dh  # noqa: E402

REQUIRED_SNIPPETS = [
    (ROOT / "memos" / "policy.md", "POL-003"),
    (SCRIPTS / "dashboard_honesty.py", "bus-finish:"),
    (SCRIPTS / "bus_finish_sync.py", "bus_finish_sync"),
    (SCRIPTS / "sync-dashboard-live.sh", "reconcile-ledger.py"),
    (ROOT.parent / "ai-agents-workspace" / "agent-bus" / "scripts" / "bus.py", "bus_finish_sync"),
]


def check_wiring() -> list[str]:
    errs = []
    for path, needle in REQUIRED_SNIPPETS:
        if not path.is_file():
            errs.append(f"missing file: {path}")
            continue
        if needle not in path.read_text(encoding="utf-8"):
            errs.append(f"{path.name} missing {needle!r}")
    return errs


def main() -> int:
    errs = check_wiring()
    if errs:
        for e in errs:
            print(f"WITNESS FAIL wiring: {e}", file=sys.stderr)
        return 1

    for test_name in (
        "test_dashboard_honesty.py",
        "test_pattern_detector.py",
        "test_cron_health.py",
    ):
        test = SCRIPTS / test_name
        if test.is_file():
            r = subprocess.run([sys.executable, str(test)], cwd=str(ROOT))
            if r.returncode != 0:
                print(f"WITNESS FAIL {test_name}", file=sys.stderr)
                return r.returncode

    issues = dh.detect_drift()
    if issues:
        print("WITNESS: drift detected, running reconcile…", file=sys.stderr)
        subprocess.run([sys.executable, str(SCRIPTS / "reconcile-ledger.py")], cwd=str(ROOT))
        issues = dh.detect_drift()
    if issues:
        for i in issues:
            print(f"WITNESS FAIL drift: {i}", file=sys.stderr)
        return 1

    cron_issues = ch.check()
    if cron_issues:
        for i in cron_issues:
            print(f"WITNESS FAIL cron: {i}", file=sys.stderr)
        if os.environ.get("CRON_HEALTH_STRICT", "0") in ("1", "true"):
            ch.maybe_alert(cron_issues)
            return 1
        print("WITNESS: cron stale (non-strict — install cron on droplet)", file=sys.stderr)

    print("WITNESS PASS: dashboard honesty (POL-003)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())