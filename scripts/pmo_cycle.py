#!/usr/bin/env python3
"""PMO always-on cycle — standing duties the PMO agent runs each reconcile tick.

1. Post-triage dispatch (pmo_dispatch) when PMO-001 is complete and queue empty
2. PMO heartbeat when portfolio is idle (ledger visibility)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pmo_dispatch as pd  # noqa: E402

import coo_janitor as cj  # noqa: E402


def main() -> int:
    janitor = cj.run_janitor(dry_run=False, append_fn=pd.append_ledger)
    if int(janitor.get("total") or 0):
        print("pmo_cycle: janitor", json.dumps(janitor))

    events = pd.load_events()
    tasks = pd.task_state(events)
    pmo_status = (tasks.get("PMO-001", {}).get("status") or "").lower()

    active_dispatch = any(
        (t.get("status") or "") in ("queued", "in_progress")
        for tid, t in tasks.items()
        if tid.startswith("ISSUE-") or tid == pd.DISPATCH_TASK_ID
    )

    if pmo_status == "completed" and not active_dispatch and not pd.dispatch_already_done(tasks):
        out = pd.run_dispatch(dry_run=False)
        print("pmo_cycle: dispatch", json.dumps(out))
        if out.get("dispatched"):
            return 0

    retry = pd.retry_undispatched(dry_run=False)
    if retry.get("retried"):
        print("pmo_cycle: retry", json.dumps(retry))
        return 0

    if pmo_status == "completed" and not active_dispatch:
        print("pmo_cycle: portfolio idle (triage done, dispatch recorded or no result file)")
        return 0

    print("pmo_cycle: no action (PMO=%s active_dispatch=%s)" % (pmo_status, active_dispatch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())