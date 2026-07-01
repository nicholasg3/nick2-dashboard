#!/usr/bin/env python3
"""CEO supervisor cycle — corrective ops, not observe-only (POL-009 + POL-008).

Runs before frontier check-in / PMO dispatch:
  1. Catalog enrich + landed-on-main audit (updates pmo_001_result.json)
  2. COO bus janitor
  3. Dashboard honesty witness (non-fatal)
  4. Fleet check-in summary
  5. CEO reflection — bottleneck detect, unstick, bounded delegation (POL-010)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import coo_janitor as cj  # noqa: E402
import ceo_reflect as cr  # noqa: E402
import cron_health as ch  # noqa: E402
import job_catalog as jc  # noqa: E402
import pmo_dispatch as pd  # noqa: E402

MARKER = "ceo-supervisor:"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_witness_honesty() -> dict:
    script = SCRIPTS / "witness_dashboard_honesty.py"
    if not script.is_file():
        return {"skipped": True}
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        return {
            "exit_code": r.returncode,
            "ok": r.returncode == 0,
            "stderr": (r.stderr or "")[:400],
        }
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "error": str(e)[:200]}


def run_checkin_summary() -> dict:
    workspace = ROOT.parent / "ai-agents-workspace"
    checkin = workspace / "Projects-for-agents" / "frontier-orchestrator" / "ceo_checkin.py"
    if not checkin.is_file():
        return {"skipped": True}
    try:
        env = {**os.environ, "CEO_SUPERVISOR_CYCLE": "1"}
        r = subprocess.run(
            [sys.executable, str(checkin)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(workspace),
            env=env,
        )
        return {
            "exit_code": r.returncode,
            "summary": (r.stdout or "").strip()[:1500],
            "issues": r.returncode != 0,
        }
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"error": str(e)[:200]}


def run_cycle(
    *,
    dry_run: bool = False,
    append_ledger: bool = False,
) -> dict:
    landed = jc.audit_landed_on_main(dry_run=dry_run)
    enriched = jc.enrich_catalog_from_triage(dry_run=dry_run)

    janitor: dict = {}
    if not dry_run:
        janitor = cj.run_janitor(
            append_fn=pd.append_ledger if append_ledger else None
        )
    else:
        janitor = cj.run_janitor(dry_run=True)

    honesty = run_witness_honesty() if not dry_run else {"skipped": dry_run}
    cron_issues = [] if dry_run else ch.check()
    cron_alert = False
    if cron_issues and not dry_run:
        cron_alert = ch.maybe_alert(cron_issues)
    checkin = run_checkin_summary()

    # Heartbeat now drives full CEO reasoning (not just fixed scripted passes).
    # On idle: run the LLM reflect with open-initative mode enabled so CEO can
    # creatively decide high-EV autonomous improvements and register them visibly.
    idle = False
    try:
        # Peek at recent context cheaply
        import pmo_dispatch as pd  # noqa
        evs = pd.load_events()[-5:]
        # simple idle heuristic
        idle = all((e.get("event") or "").endswith("cycle") or "idle" in (e.get("output") or "").lower() for e in evs[-3:])
    except Exception:
        pass

    reflect = cr.run_reflect(
        dry_run=dry_run,
        append_ledger=append_ledger and not dry_run,
        llm=True,            # always attempt LLM layer
        force_llm=idle,      # force fresh open reasoning when heartbeat sees idle
    )

    corrective = (
        int(landed.get("updated") or 0)
        + int(enriched.get("enriched") or 0)
        + int(janitor.get("total") or 0)
        + len(reflect.get("actions") or [])
    )

    report = {
        "ts": _now(),
        "mode": "supervisor_corrective",
        "landed": landed,
        "catalog_enriched": enriched.get("enriched", 0),
        "janitor": janitor,
        "witness_honesty": honesty,
        "cron_health": {"issues": cron_issues, "alerted": cron_alert},
        "checkin": checkin,
        "reflect": reflect,
        "corrective_actions": corrective,
    }

    issues: list[str] = []
    if landed.get("tasks"):
        issues.append(
            "landed-on-main: %s"
            % ", ".join(t["task_id"] for t in landed["tasks"])
        )
    if int(janitor.get("total") or 0):
        issues.append("janitor: %s actions" % janitor["total"])
    if honesty.get("ok") is False:
        issues.append("dashboard witness failed")
    if cron_issues:
        issues.append("sync cron stale: " + cron_issues[0][:120])
    if checkin.get("issues"):
        issues.append("fleet check-in flagged issues")
    high_bn = [b for b in (reflect.get("bottlenecks") or []) if b.get("severity") == "high"]
    if high_bn:
        issues.append("reflect: %d high-severity bottleneck(s)" % len(high_bn))

    report["issues"] = issues
    report["healthy"] = not issues

    if append_ledger and not dry_run and (corrective or issues):
        events = pd.load_events()
        base = pd.ledger_base(events)
        parts = []
        if landed.get("updated"):
            parts.append(f"landed={landed['updated']}")
        if enriched.get("enriched"):
            parts.append(f"enriched={enriched['enriched']}")
        if janitor.get("total"):
            parts.append(f"janitor={janitor['total']}")
        if reflect.get("actions"):
            parts.append(f"reflect_actions={len(reflect['actions'])}")
        pd.append_ledger(
            {
                **base,
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "supervisor_cycle",
                "task_id": "FOCUS-001",
                "focus_task_id": "SYS-002",
                "task": "CEO supervisor corrective cycle",
                # A monitoring check-in is never itself "blocked" work — detected
                # issues are surfaced via pattern_flag / bottleneck events and the
                # CEO Focus block, not by parking FOCUS-001 in the active queue.
                "status": "completed",
                "owner": "CEO",
                "output": f"{MARKER} {'; '.join(parts) or 'check-in only'}",
                "artifacts": [
                    "scripts/ceo_supervisor.py",
                    "scripts/job_catalog.py",
                ],
            }
        )

    return report


def main() -> int:
    p = argparse.ArgumentParser(description="CEO supervisor corrective cycle")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ledger", action="store_true")
    args = p.parse_args()
    report = run_cycle(dry_run=args.dry_run, append_ledger=args.ledger)
    print(json.dumps(report, indent=2))
    return 0 if report.get("healthy") else 1


if __name__ == "__main__":
    raise SystemExit(main())