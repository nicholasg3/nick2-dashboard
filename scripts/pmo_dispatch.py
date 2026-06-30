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
import re
import sqlite3
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
BUS_DB = BUS_ROOT / "jobs.sqlite"
WORKSPACE = BUS_ROOT.parent
ACTIVE_BUS = ("running", "queued", "held")

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


def _feature_slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:max_len] or "job").strip("-")


def _issue_needle(task_id: str, item: dict) -> str | None:
    """Match ledger ISSUE-80 to objective fragments (#80, ISSUE-080)."""
    num = item.get("issue_number")
    if num is not None:
        return f"#{int(num)}"
    m = re.match(r"^ISSUE-(\d+)$", task_id or "")
    if m:
        return f"#{int(m.group(1))}"
    return task_id if task_id.startswith("ISSUE-") else None


def active_bus_job(
    *,
    repo: str,
    objective: str,
    task_id: str = "",
    item: dict | None = None,
) -> str | None:
    """POL-006 — return existing active job_id for same repo+objective (or same issue)."""
    if not BUS_DB.is_file():
        return None
    slug = _feature_slug(objective.split("\n")[0])
    needle = _issue_needle(task_id, item or {})
    conn = sqlite3.connect(BUS_DB)
    try:
        rows = conn.execute(
            f"""SELECT job_id, objective FROM jobs
                WHERE repo=? AND status IN ({",".join("?" * len(ACTIVE_BUS))})
                ORDER BY CASE status
                  WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
                  created_at ASC""",
            (repo, *ACTIVE_BUS),
        ).fetchall()
        for job_id, obj in rows:
            if obj == objective or _feature_slug((obj or "").split("\n")[0]) == slug:
                return job_id
            if needle and needle in (obj or ""):
                return job_id
            if task_id and task_id in (obj or ""):
                return job_id
        return None
    finally:
        conn.close()


def _parse_bus_submit(stdout: str, stderr: str, returncode: int) -> dict:
    out = (stdout or "").strip()
    if returncode != 0:
        err = (stderr or out or "bus submit failed")[:800]
        return {"error": err, "stderr": (stderr or "")[:800], "returncode": returncode}
    if not out:
        return {"error": (stderr or "empty bus response")[:400], "returncode": returncode}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"error": out[:400], "returncode": returncode}
    if data.get("action") == "split_multi_repo" and data.get("jobs"):
        jobs = data["jobs"]
        return jobs[-1] if jobs else {"error": "split_multi_repo empty"}
    if data.get("job_id"):
        return data
    return {"error": out[:400], "returncode": returncode}


def submit_bus_job(
    *,
    session: str,
    objective: str,
    repo: str,
    task_type: str = "repo_edit",
    after: str | None = None,
    dry_run: bool = False,
    task_id: str = "",
    item: dict | None = None,
) -> dict | None:
    if dry_run or not BUS.is_file():
        return {"dry_run": True, "session": session, "repo": repo, "objective": objective[:120]}
    existing = active_bus_job(
        repo=repo, objective=objective, task_id=task_id, item=item
    )
    if existing:
        return {
            "job_id": existing,
            "status": "linked-existing",
            "reason": "POL-006 active bus job already covers this issue",
        }
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
        return _parse_bus_submit(r.stdout or "", r.stderr or "", r.returncode)
    except Exception as e:
        return {"error": str(e)}


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
        if item.get("dispatch") is False:
            continue
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

    prior_chain: dict[str, str] = {}
    job_rows: list[dict] = []
    for item in queued:
        tid = item["task_id"]
        title = item.get("title") or tid
        worker = (item.get("worker") or "coding_worker").strip()
        repo = (item.get("repo") or "ai-agents-workspace").strip()
        objective = build_objective(item, tid)
        chain_key = f"{repo}:{worker}"
        after = prior_chain.get(chain_key)

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
            task_type="repo_edit" if worker == "coding_worker" else "memo_draft",
            after=after,
            dry_run=dry_run,
            task_id=tid,
            item=item,
        )
        job_id = None
        if isinstance(bus_out, dict):
            job_id = bus_out.get("job_id")
            if bus_out.get("jobs"):
                job_id = bus_out["jobs"][-1].get("job_id")
        if job_id:
            prior_chain[chain_key] = job_id
        job_rows.append({"task_id": tid, "job_id": job_id, "bus": bus_out})

        if not dry_run and job_id:
            bus_status = (bus_out or {}).get("status", "queued")
            if bus_status in ("running", "linked-existing"):
                status = "in_progress"
            elif bus_status == "held":
                status = "queued"
            else:
                status = "queued"
            note = f"dispatched {job_id} to {worker} ({bus_status})"
            if bus_status == "linked-existing":
                note = f"linked existing {job_id} ({bus_out.get('reason', 'POL-006')})"
            append_ledger(
                {
                    **base,
                    "actor": "PMO",
                    "role": "Program Management Office",
                    "event": "task_updated",
                    "task_id": tid,
                    "task": title,
                    "status": status,
                    "owner": worker.replace("_worker", ""),
                    "output": f"{DISPATCH_MARKER}{note}.",
                    "artifacts": [f"agent-bus {job_id}"],
                },
                append_fn,
            )
        elif not dry_run and isinstance(bus_out, dict) and bus_out.get("error"):
            append_ledger(
                {
                    **base,
                    "actor": "PMO",
                    "role": "Program Management Office",
                    "event": "task_updated",
                    "task_id": tid,
                    "task": title,
                    "status": "queued",
                    "owner": worker.replace("_worker", ""),
                    "output": (
                        f"{DISPATCH_MARKER}bus submit failed (will retry): "
                        f"{str(bus_out.get('error'))[:180]}"
                    ),
                    "artifacts": [],
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


def _item_lookup() -> dict[str, dict]:
    data = load_triage_result() or {}
    out: dict[str, dict] = {}
    for item in data.get("top_issues") or []:
        out[issue_task_id(item)] = item
    return out


def retry_undispatched(*, dry_run: bool = False) -> dict:
    """Submit bus jobs for ISSUE-* rows queued/blocked without agent-bus artifacts."""
    events = load_events()
    tasks = task_state(events)
    base = ledger_base(events)
    retried: list[dict] = []
    prior_chain: dict[str, str] = {}
    catalog = _item_lookup()

    for tid in sorted(tasks):
        if not tid.startswith("ISSUE-"):
            continue
        item = catalog.get(tid, {})
        if item.get("dispatch") is False:
            continue
        t = tasks[tid]
        if (t.get("status") or "") not in ("queued", "blocked"):
            continue
        arts = t.get("artifacts") or []
        if any("agent-bus JOB-" in str(a) for a in arts):
            continue
        out_txt = t.get("output") or ""
        submit_failed = "bus submit failed" in out_txt
        if not submit_failed and DISPATCH_MARKER not in out_txt:
            continue
        owner = (t.get("owner") or "coding").lower()
        worker = (item.get("worker") or ("research_worker" if owner == "research" else "coding_worker"))
        repo = (item.get("repo") or "ai-agents-workspace").strip()
        item = {
            **item,
            "task_id": tid,
            "title": t.get("task") or item.get("title"),
            "issue_number": t.get("issue_number") if t.get("issue_number") is not None else item.get("issue_number"),
            "roi": t.get("roi") if t.get("roi") is not None else item.get("roi"),
            "worker": worker,
            "repo": repo,
        }
        chain_key = f"{repo}:{worker}"
        bus_out = submit_bus_job(
            session=worker,
            objective=build_objective(item, tid),
            repo=repo,
            task_type="repo_edit" if worker == "coding_worker" else "memo_draft",
            after=prior_chain.get(chain_key),
            dry_run=dry_run,
            task_id=tid,
            item=item,
        )
        job_id = (bus_out or {}).get("job_id") if isinstance(bus_out, dict) else None
        if job_id:
            prior_chain[chain_key] = job_id
            if not dry_run:
                bus_status = (bus_out or {}).get("status", "queued")
                if bus_status in ("running", "linked-existing"):
                    row_status = "in_progress"
                elif bus_status == "held":
                    row_status = "queued"
                else:
                    row_status = "queued"
                note = f"retry dispatched {job_id}"
                if bus_status == "linked-existing":
                    note = f"retry linked existing {job_id}"
                append_ledger(
                    {
                        **base,
                        "actor": "PMO",
                        "role": "Program Management Office",
                        "event": "task_updated",
                        "task_id": tid,
                        "task": t.get("task"),
                        "status": row_status,
                        "owner": t.get("owner"),
                        "output": f"{DISPATCH_MARKER}{note}.",
                        "artifacts": [f"agent-bus {job_id}"],
                    }
                )
        retried.append({"task_id": tid, "job_id": job_id, "bus": bus_out})
    return {"retried": len(retried), "jobs": retried}


def main() -> int:
    p = argparse.ArgumentParser(description="PMO post-triage dispatch")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-issues", type=int, default=None)
    p.add_argument("--retry", action="store_true", help="Retry ISSUE-* without bus jobs")
    args = p.parse_args()
    if args.retry:
        out = retry_undispatched(dry_run=args.dry_run)
    else:
        out = run_dispatch(dry_run=args.dry_run, max_issues=args.max_issues)
    print(json.dumps(out, indent=2))
    if out.get("skipped"):
        return 0
    if out.get("dispatched", 0) == 0 and out.get("retried", 0) == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())