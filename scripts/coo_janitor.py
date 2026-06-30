#!/usr/bin/env python3
"""COO bus hygiene — POL-008 janitor before PMO dispatch/retry.

Loads dispatch:false rows from pmo_001_result.json, runs agent-bus bus_janitor,
optionally appends a ledger event when actions were taken.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pmo_dispatch as pd  # noqa: E402

BUS_JANITOR = Path(
    os.environ.get(
        "BUS_JANITOR",
        ROOT.parent / "ai-agents-workspace" / "agent-bus" / "scripts" / "bus_janitor.py",
    )
)
MARKER = "coo-janitor:"


def deferred_tasks_from_triage() -> dict[str, str]:
    """task_id → defer_reason for PMO-ranked issues with dispatch: false."""
    data = pd.load_triage_result() or {}
    out: dict[str, str] = {}
    for item in data.get("top_issues") or []:
        if item.get("dispatch") is False:
            tid = pd.issue_task_id(item)
            out[tid] = str(item.get("defer_reason") or "dispatch: false in pmo_001_result.json")
    return out


def run_janitor(
    *,
    dry_run: bool = False,
    stale_min: float = 10.0,
    append_fn: Callable[[dict], bool] | None = None,
) -> dict:
    deferred = deferred_tasks_from_triage()
    cmd = [
        sys.executable,
        str(BUS_JANITOR),
        "--stale-min",
        str(stale_min),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if deferred:
        cmd.extend(["--deferred-json", json.dumps(deferred)])

    if not BUS_JANITOR.is_file():
        return {"error": f"missing {BUS_JANITOR}", "deferred": deferred}

    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT.parent / "ai-agents-workspace"))
    summary: dict = {"deferred": deferred, "returncode": r.returncode}
    if r.stdout.strip():
        parsed = None
        for block in reversed(r.stdout.strip().split("\n\n")):
            block = block.strip()
            if block.startswith("{"):
                try:
                    parsed = json.loads(block)
                    break
                except json.JSONDecodeError:
                    continue
        if parsed:
            summary.update(parsed)
        else:
            summary["raw_stdout"] = r.stdout[:2000]
    if r.stderr.strip():
        summary["stderr"] = r.stderr[:800]

    total = int(summary.get("total") or 0)
    if not dry_run and total > 0 and append_fn:
        events = pd.load_events()
        base = pd.ledger_base(events)
        parts = []
        for key in (
            "smoke_closed",
            "duplicates_closed",
            "deferred_superseded",
            "stale_holds_superseded",
            "claims_released",
            "orphan_holds_removed",
            "promoted",
        ):
            v = int(summary.get(key) or 0)
            if v:
                parts.append(f"{key}={v}")
        append_fn(
            {
                **base,
                "actor": "COO",
                "role": "Chief Operating Officer",
                "event": "bus_janitor",
                "task_id": "SYS-002",
                "task": "Bus queue hygiene (POL-008)",
                "status": "completed",
                "owner": "COO",
                "output": f"{MARKER} {'; '.join(parts) or 'actions=0'}",
                "artifacts": ["agent-bus/scripts/bus_janitor.py"],
            }
        )

    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="COO POL-008 bus janitor")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stale-min", type=float, default=10.0)
    p.add_argument("--ledger", action="store_true", help="Append ledger event when actions taken")
    args = p.parse_args()

    append_fn = pd.append_ledger if args.ledger else None
    out = run_janitor(dry_run=args.dry_run, stale_min=args.stale_min, append_fn=append_fn)
    print(json.dumps(out, indent=2))
    if out.get("error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())