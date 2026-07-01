#!/usr/bin/env python3
"""launch_ceo_initiative.py — register + optionally spawn a tracked CEO autonomous sub-agent.

Usage (from CEO supervisor, chat role, or cron):
  python3 scripts/launch_ceo_initiative.py \
    --id CEO-INIT-20260701-001 \
    --title "Audit dashboard agent fleet visibility" \
    --why "CEO heartbeat idle; make spawns appear in org-fleet + work queue" \
    --first-step "claude -p --permission-mode bypassPermissions '...' " \
    --spawn   # optional: actually launch a background claude (tracked)

This ensures:
- Visible entry in Active Work Queue (via ledger task_*)
- Shows in Agent Fleet under CEO
- PMO / janitor see it (no redundant work)
- Cost is charged to weekly budget via ledger

The spawned sub-agent should append task_updated events using append-ledger-event.py
or the shared role_memory / infra patterns.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pmo_dispatch as pd  # noqa: E402

LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"


def now_sgt() -> str:
    from datetime import timedelta
    SGT = timezone(timedelta(hours=8))
    return datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")


def append_ledger(ev: dict) -> None:
    ev.setdefault("ts", now_sgt())
    ev.setdefault("actor", "CEO")
    ev.setdefault("role", "Chief Executive Officer")
    line = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
    prefix = ""
    if LEDGER.exists() and LEDGER.stat().st_size > 0:
        if not LEDGER.read_bytes().endswith(b"\n"):
            prefix = "\n"
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Launch/register a visible CEO initiative")
    p.add_argument("--id", required=True, help="e.g. CEO-INIT-20260701-003")
    p.add_argument("--title", required=True)
    p.add_argument("--why", default="")
    p.add_argument("--first-step", default="")
    p.add_argument("--est-cost", type=float, default=0.4)
    p.add_argument("--spawn", action="store_true", help="Actually run claude -p (background)")
    p.add_argument("--command", default="", help="Full command to run for the sub-agent (when --spawn)")
    args = p.parse_args()

    base = pd.ledger_base(pd.load_events())

    # Register as queued then in_progress so queue + fleet pick it up immediately
    append_ledger({
        **base,
        "event": "task_queued",
        "task_id": args.id,
        "task": args.title,
        "status": "queued",
        "owner": "CEO",
        "output": f"CEO initiative registered: {args.why[:200]}",
        "est_cost_usd": args.est_cost,
        "initiative": {"title": args.title, "why_now": args.why, "first_step": args.first_step},
    })
    append_ledger({
        **base,
        "event": "task_updated",
        "task_id": args.id,
        "task": args.title,
        "status": "in_progress",
        "owner": "CEO",
        "output": f"First step: {args.first_step or '(executing)'}",
    })

    if args.spawn and args.command:
        # Launch detached; the sub-agent is responsible for ledger heartbeats + completion
        try:
            # Use nohup + & so it survives the supervisor tick
            full = f"nohup {args.command} >> logs/ceo_initiatives.log 2>&1 &"
            subprocess.Popen(full, shell=True, cwd=str(ROOT))
            append_ledger({
                **base,
                "event": "task_updated",
                "task_id": args.id,
                "task": args.title,
                "status": "in_progress",
                "owner": "CEO",
                "output": f"Spawned tracked sub-agent (detached). Command started.",
            })
            print(f"Launched + registered {args.id}")
        except Exception as e:
            append_ledger({
                **base,
                "event": "task_updated",
                "task_id": args.id,
                "task": args.title,
                "status": "blocked",
                "owner": "CEO",
                "output": f"Spawn failed: {e}",
            })
            print("Spawn failed:", e, file=sys.stderr)
            return 2
    else:
        print(f"Registered (no spawn) {args.id} — {args.title}")

    # Refresh reports so dashboard sees it now
    try:
        subprocess.run([sys.executable, str(SCRIPTS / "export-json-reports.py")], cwd=str(ROOT), timeout=30)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
