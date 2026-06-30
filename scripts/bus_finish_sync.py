#!/usr/bin/env python3
"""POL-003 — run on every agent-bus job finish (droplet).

Appends proactive ledger heartbeat, reconciles drift, refreshes bus-live export.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dashboard_honesty as dh  # noqa: E402

LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
BUS = Path(
    os.environ.get(
        "AGENT_BUS_ROOT",
        ROOT.parent / "ai-agents-workspace" / "agent-bus",
    )
)


def append_ledger(event: dict) -> None:
    event.setdefault("ts", __import__("datetime").datetime.now(
        __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
    ).strftime("%Y-%m-%dT%H:%M:%S+08:00"))
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    prefix = ""
    if LEDGER.exists() and LEDGER.stat().st_size > 0:
        if not LEDGER.read_bytes().endswith(b"\n"):
            prefix = "\n"
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")
    print(f"bus_finish_sync: ledger + {event.get('event')} {event.get('task_id')}")


def load_packet_report(job_id: str) -> tuple[dict, dict]:
    packet_path = BUS / "logs" / f"{job_id}.packet.json"
    report_path = BUS / "outbox" / f"{job_id}.json"
    packet = {}
    report = {}
    if packet_path.is_file():
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    packet.setdefault("job_id", job_id)
    return packet, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, help="JOB-YYYYMMDD-NNN")
    ap.add_argument("--skip-push", action="store_true")
    args = ap.parse_args()

    packet, report = load_packet_report(args.job)
    events = dh.load_events()

    ev = dh.ledger_event_for_job_finish(args.job, packet, report, events)
    if ev:
        append_ledger(ev)
        events = dh.load_events()

    # Full reconcile pass (idempotent markers)
    subprocess.run(
        [sys.executable, str(SCRIPTS / "reconcile-ledger.py")],
        cwd=str(ROOT),
        check=False,
    )
    subprocess.run(
        [sys.executable, str(SCRIPTS / "export_bus_live.py")],
        cwd=str(ROOT),
        check=False,
    )

    if not args.skip_push and os.environ.get("BUS_FINISH_PUSH", "1") not in ("0", "false"):
        sync = SCRIPTS / "sync-dashboard-live.sh"
        if sync.is_file():
            subprocess.run(["bash", str(sync)], cwd=str(ROOT), check=False)

    issues = dh.detect_drift()
    if issues:
        print("bus_finish_sync: residual drift after sync:", file=sys.stderr)
        for i in issues:
            print(f"  - {i}", file=sys.stderr)
        return 1
    print("bus_finish_sync: ok", args.job)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())