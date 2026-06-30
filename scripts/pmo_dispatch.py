#!/usr/bin/env python3
"""PMO post-triage dispatch — queue ranked issues and submit agent-bus jobs.

Standing PMO duty after PMO-001 triage completes:
  1. Read pmo_001_result.json top-N
  2. Append task_queued ledger events (DISPATCH-001 + per-issue)
  3. Dispatch coding_worker / research_worker jobs within weekly budget
  4. Append focus_snapshot on the first queued issue

Idempotent: skips if DISPATCH-001 already queued/in_progress/completed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = ROOT / "scripts"
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
RESULT_CANDIDATES = [
    ROOT / "pmo_001_result.json",
    ROOT.parent / "ai-agents-workspace" / "pmo_001_result.json",
]
BUS_ROOT = Path(
    os.environ.get(
        "AGENT_BUS_ROOT",
        ROOT.parent / "ai-agents-workspace" / "agent-bus",
    )
)
BUS = BUS_ROOT / "scripts" / "bus.py"
WORKSPACE = BUS_ROOT.parent

SGT = timezone(timedelta(hours=8))
DISPATCH_MARKER = "pmo-dispatch:"
DISPATCH_TASK_ID = "DISPATCH-001"


def now_sgt() -> str:
    return datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return sorted(out, key=lambda e: e.get("ts", ""))


def task_state(events: list[dict]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for ev in events:
        tid = ev.get("task_id")
        if tid:
            tasks[tid] = {**tasks.get(tid, {}), **ev}
    return tasks


def latest(events: list[dict], key: str, default: Any = None) -> Any:
    for ev in reversed(events):
        if key in ev and ev[key] is not None:
            return ev[key]
    return default


def ledger_base(events: list[dict]) -> dict:
    weekly = latest(events, "weekly_budget_usd", 0) or 0
    cumulative = latest(events, "cumulative_weekly_spend_usd", 0) or 0
    remaining = max(0, float(weekly) - float(cumulative)) if weekly else 0
    return {
        "cumulative_weekly_spend_usd": cumulative,
        "budget_remaining_usd": remaining,
        "weekly_budget_usd": weekly,
        "budget_mode": latest(events, "budget_mode", "off"),
        "needs_nicholas": False,
        "cost_usd": 0,
    }


def find_result_path() -> Path | None:
    for p in RESULT_CANDIDATES:
        if p.is_file():
            return p
    return None


def load_triage_result() -> dict | None:
    path = find_result_path()
    if not path:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    issues = data.get("top_issues") or data.get("ranked") or []
    if not issues:
        return None
    data["_path"] = str(path)
    return data


def issue_task_id(item: dict) -> str:
    if item.get("task_id"):
        return str(item["task_id"])
    num = item.get("issue_number")
    if num is not None:
        return f"ISSUE-{int(num)}"
    rank = item.get("rank", 0)
    return f"ISSUE-R{rank}"


def dispatch_already_done(tasks: dict[str, dict]) -> bool:
    disp = tasks.get(DISPATCH_TASK_ID, {})
    status = (disp.get("status") or "").lower()
    if status in ("queued", "in_progress", "completed"):
        return True
    out = disp.get("output") or ""
    return DISPATCH_MARKER in out


def append_ledger(event: dict, append_fn: Callable[[dict], bool] | None = None) -> bool:
    if append_fn:
        return append_fn(event)
    sys.path.insert(0, str(SCRIPTS))
    import ledger_write_guard as lwg  # noqa: E402

    event.setdefault("ts", now_sgt())
    guarded = lwg.guard_ledger_event(event)
    if guarded is None:
        return False
    event = guarded
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    prefix = ""
    if LEDGER.exists() and LEDGER.stat().st_size > 0:
        if not LEDGER.read_bytes().endswith(b"\n"):
            prefix = "\n"
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")
    return True


def submit_bus_job(
    *,
    session: str,
    objective: str,
    repo: str,
    task_type: str = "implementation",
    after: str | None = None,
    dry_run: bool = False,
) -> dict | None:
    if dry_run or not BUS.is_file():
        return {"dry_run": True, "session": session, "repo": repo, "objective": objective[:120]}
    cmd = [
        "python3",
        str(BUS),
        "submit",
        "--to",
        session,
        "--task-type",
        task_type,
        "--from-harness",
        "pmo-dispatch",
        "--repo",
        repo,
        "--objective",
        objective,
    ]
    if after:
        cmd.extend(["--after", after])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=str(WORKSPACE))
        out = (r.stdout or "").strip()
        if r.returncode != 0:
            err = (r.stderr or out or "bus submit failed")[:300]
            return {"error": err, "returncode": r.returncode}
        if out:
            return json.loads(out)
    except Exception as e:
        return {"error": str(e)}
    return None


def build_objective(item: dict, task_id: str) -> str:
    if item.get("objective"):
        return str(item["objective"])
    num = item.get("issue_number")
    title = item.get("title") or task_id
    roi = item.get("roi")
    roi_s = f" ROI={roi}." if roi is not None else ""
    if num:
        return (
            f"{task_id}: Implement GitHub issue #{num} — {title}.{roi_s} "
            f"Closes #{num} when witness passes. PMO dispatch from PMO-001 triage."
        )
    return (
        f"{task_id}: {title}.{roi_s} PMO dispatch from PMO-001 triage. "
        "Runnable witness required before marking done."
    )


def run_dispatch(
    *,
    dry_run: bool = False,
    append_fn: Callable[[dict], bool] | None = None,
    max_issues: int | None = None,
) -> dict:
    events = load_events()
    tasks = task_state(events)
    base = ledger_base(events)

    pmo = tasks.get("PMO-001", {})
    if (pmo.get("status") or "").lower() != "completed":
        return {"skipped": True, "reason": "PMO-001 not completed"}

    if dispatch_already_done(tasks):
        return {"skipped": True, "reason": "DISPATCH-001 already recorded"}

    result = load_triage_result()
    if not result:
        return {"skipped": True, "reason": "pmo_001_result.json not found"}

    weekly = float(base.get("weekly_budget_usd") or 0)
    if weekly <= 0:
        return {"skipped": True, "reason": "weekly budget is OFF"}

    issues = list(result.get("top_issues") or [])
    if max_issues:
        issues = issues[:max_issues]

    budget_cap = float(result.get("dispatch_budget_usd") or weekly)
    budget_left = min(float(base.get("budget_remaining_usd") or weekly), budget_cap)

    queued: list[dict] = []
    spent_plan = 0.0
    for item in sorted(issues, key=lambda x: x.get("rank", 99)):
        est = float(item.get("est_cost_usd") or 1.0)
        if spent_plan + est > budget_left:
            break
        tid = issue_task_id(item)
        if tasks.get(tid, {}).get("status") in ("queued", "in_progress", "completed"):
            continue
        queued.append({**item, "task_id": tid, "est_cost_usd": est})
        spent_plan += est

    if not queued:
        return {"skipped": True, "reason": "no issues fit budget or all already queued"}

    first = queued[0]
    first_id = first["task_id"]
    summary = ", ".join(f"{q['task_id']}(#{q.get('issue_number', '?')})" for q in queued)

    if not dry_run:
        append_ledger(
            {
                **base,
                "actor": "PMO",
                "role": "Program Management Office",
                "event": "task_queued",
                "task_id": DISPATCH_TASK_ID,
                "task": f"Dispatch top-{len(queued)} from PMO-001 triage",
                "status": "in_progress",
                "owner": "PMO",
                "output": (
                    f"{DISPATCH_MARKER}queued {len(queued)} issues within "
                    f"${spent_plan:.1f} planned spend. Queue: {summary}"
                ),
                "artifacts": [str(find_result_path() or "pmo_001_result.json")],
            },
            append_fn,
        )

    prior_job: str | None = None
    job_rows: list[dict] = []
    for item in queued:
        tid = item["task_id"]
        title = item.get("title") or tid
        worker = (item.get("worker") or "coding_worker").strip()
        repo = (item.get("repo") or "ai-agents-workspace").strip()
        objective = build_objective(item, tid)

        if not dry_run:
            append_ledger(
                {
                    **base,
                    "actor": "PMO",
                    "role": "Program Management Office",
                    "event": "task_queued",
                    "task_id": tid,
                    "task": title,
                    "status": "queued",
                    "owner": worker.replace("_worker", ""),
                    "parent_task_id": DISPATCH_TASK_ID,
                    "issue_number": item.get("issue_number"),
                    "roi": item.get("roi"),
                    "output": (
                        f"{DISPATCH_MARKER}rank {item.get('rank')} queued for {worker}. "
                        f"Est ${item.get('est_cost_usd', 1):.1f}."
                    ),
                    "artifacts": [],
                },
                append_fn,
            )

        bus_out = submit_bus_job(
            session=worker,
            objective=objective,
            repo=repo,
            task_type="implementation" if worker == "coding_worker" else "research",
            after=prior_job,
            dry_run=dry_run,
        )
        job_id = None
        if isinstance(bus_out, dict):
            job_id = bus_out.get("job_id")
            if bus_out.get("jobs"):
                job_id = bus_out["jobs"][-1].get("job_id")
        if job_id:
            prior_job = job_id
        job_rows.append({"task_id": tid, "job_id": job_id, "bus": bus_out})

        if not dry_run and job_id:
            append_ledger(
                {
                    **base,
                    "actor": "PMO",
                    "role": "Program Management Office",
                    "event": "task_updated",
                    "task_id": tid,
                    "task": title,
                    "status": "in_progress",
                    "owner": worker.replace("_worker", ""),
                    "output": f"{DISPATCH_MARKER}dispatched {job_id} to {worker}.",
                    "artifacts": [f"agent-bus {job_id}"],
                },
                append_fn,
            )

    if not dry_run:
        append_ledger(
            {
                **base,
                "actor": "PMO",
                "role": "Program Management Office",
                "event": "focus_snapshot",
                "task_id": "FOCUS-001",
                "focus_task_id": first_id,
                "task": first.get("title") or first_id,
                "status": "queued",
                "owner": "PMO",
                "focus_line": f"Dispatching {first_id} — {first.get('title', '')[:60]}",
                "focus_detail": (
                    f"PMO-001 triage complete. {len(queued)} issues queued; "
                    f"focus on highest-ROI item first."
                ),
                "output": f"{DISPATCH_MARKER}focus → {first_id}",
            },
            append_fn,
        )

    return {
        "dispatched": len(queued),
        "first_focus": first_id,
        "planned_spend_usd": spent_plan,
        "jobs": job_rows,
        "dry_run": dry_run,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="PMO post-triage dispatch")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-issues", type=int, default=None)
    args = p.parse_args()
    out = run_dispatch(dry_run=args.dry_run, max_issues=args.max_issues)
    print(json.dumps(out, indent=2))
    if out.get("skipped"):
        return 0
    if out.get("dispatched", 0) == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())