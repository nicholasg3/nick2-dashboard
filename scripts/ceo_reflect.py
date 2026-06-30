#!/usr/bin/env python3
"""CEO reflection cycle — bottleneck awareness, unstick, bounded delegation (POL-010).

Gathers bus + ledger + triage context, detects org bottlenecks, takes mechanical
unstick actions when admission allows, and writes reflection artifacts for the
dashboard.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ceo_reflect_llm as crl  # noqa: E402
import pmo_dispatch as pd  # noqa: E402
import work_queue_ops as wqo  # noqa: E402

BUS_ROOT = pd.BUS_ROOT
BUS_DB = pd.BUS_DB
BUS_LIVE = ROOT / "reports" / "bus-live.json"
BUS_JANITOR = BUS_ROOT / "scripts" / "bus_janitor.py"
MEMORIES = BUS_ROOT / "sessions" / "ceo" / "memories.jsonl"
REPORT_PATH = ROOT / "reports" / "ceo-queue.json"
MEMO_DIR = ROOT / "memos" / "ceo-reflect"
MEMO_LATEST = MEMO_DIR / "latest.md"

MARKER = "ceo-reflect:"
ACTIVE_BUS = ("running", "queued", "held")
WAITING_RE = re.compile(r"waiting for (JOB-\S+)", re.I)
CLAIM_RE = re.compile(r"claimed by (JOB-\S+)|repo claimed", re.I)
MAX_CODING_PARALLEL = int(os.environ.get("CEO_MAX_CODING_PARALLEL", "2"))
MAX_PARALLEL = int(os.environ.get("BUS_MAX_PARALLEL", "4"))
STALE_WIP_MIN = 30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        raw = (ts or "").replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _age_minutes(ts: str | None) -> float | None:
    dt = _parse_ts(ts)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60.0


def load_bus_live() -> dict:
    if not BUS_LIVE.is_file():
        return {}
    try:
        return json.loads(BUS_LIVE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_recent_memories(limit: int = 5) -> list[dict]:
    if not MEMORIES.is_file():
        return []
    rows: list[dict] = []
    for line in MEMORIES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def query_bus_rows() -> list[dict]:
    if not BUS_DB.is_file():
        return []
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" * len(ACTIVE_BUS))
        rows = conn.execute(
            f"""SELECT job_id, status, hold_reason, repo, to_session, updated_at,
                       worker_status, objective, feature_name
                FROM jobs WHERE status IN ({placeholders}, 'blocked')
                ORDER BY CASE status
                  WHEN 'running' THEN 0 WHEN 'queued' THEN 1
                  WHEN 'held' THEN 2 ELSE 3 END,
                  updated_at ASC""",
            ACTIVE_BUS,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_repo_claims() -> list[dict]:
    if not BUS_DB.is_file():
        return []
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT rc.repo, rc.job_id, j.status, j.worker_status, j.hold_reason
               FROM repo_claims rc
               JOIN jobs j ON j.job_id = rc.job_id
               WHERE rc.released_at IS NULL"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def gather_context() -> dict:
    events = pd.load_events()
    tasks = pd.task_state(events)
    base = pd.ledger_base(events)
    triage = pd.load_triage_result() or {}
    live = load_bus_live()
    bus_rows = query_bus_rows()
    claims = query_repo_claims()
    memories = load_recent_memories()

    running = [r for r in bus_rows if r["status"] == "running"]
    held = [r for r in bus_rows if r["status"] == "held"]
    queued = [r for r in bus_rows if r["status"] == "queued"]
    # A job that ended in status=blocked but whose worker_status is done has
    # finished (work was a no-op or landed elsewhere) — it is not a live blocker.
    # Counting these produced the misleading "blocked: N / fully stalled" drift.
    blocked = [
        r for r in bus_rows
        if r["status"] == "blocked" and (r.get("worker_status") or "") != "done"
    ]
    coding_running = [r for r in running if (r.get("to_session") or "") == "coding_worker"]

    issue_tasks = {
        tid: t
        for tid, t in tasks.items()
        if tid.startswith("ISSUE-") and (t.get("status") or "") in ("queued", "blocked", "in_progress")
    }

    return {
        "ts": _now(),
        "ledger_base": base,
        "tasks": tasks,
        "triage": triage,
        "bus_live": live,
        "bus_rows": bus_rows,
        "repo_claims": claims,
        "counts": {
            "running": len(running),
            "held": len(held),
            "queued": len(queued),
            "blocked": len(blocked),
            "coding_running": len(coding_running),
        },
        "issue_tasks": issue_tasks,
        "memories_tail": memories,
    }


def detect_bottlenecks(ctx: dict) -> list[dict]:
    """Rule-based bottleneck detection — ordered by severity."""
    out: list[dict] = []
    counts = ctx["counts"]
    base = ctx["ledger_base"]
    tasks = ctx["tasks"]
    claims = ctx["repo_claims"]
    held = [r for r in ctx["bus_rows"] if r["status"] == "held"]

    if float(base.get("budget_remaining_usd") or 0) <= 0 and float(base.get("weekly_budget_usd") or 0) > 0:
        out.append({
            "type": "budget_exhausted",
            "severity": "high",
            "detail": "Weekly budget exhausted — no new dispatches until reset or Nick raises cap.",
            "unstick": "Wait for week rollover or Nick gate to raise weekly_budget_usd.",
        })

    if counts["running"] >= MAX_PARALLEL:
        out.append({
            "type": "capacity_full",
            "severity": "high",
            "detail": f"Bus at max_parallel ({counts['running']}/{MAX_PARALLEL}) — queue admits no new runners.",
            "unstick": "Let running jobs finish; avoid stacking submits until slots free.",
        })

    if counts["coding_running"] >= MAX_CODING_PARALLEL:
        out.append({
            "type": "coding_saturation",
            "severity": "medium",
            "detail": (
                f"{counts['coding_running']} coding_worker jobs running "
                f"(cap {MAX_CODING_PARALLEL}) — defer extra coding dispatches."
            ),
            "unstick": "Finish or supersede stale coding jobs before queuing more.",
        })

    for claim in claims:
        if claim.get("status") == "running":
            continue
        out.append({
            "type": "repo_claim",
            "severity": "high",
            "detail": (
                f"Repo `{claim.get('repo')}` claimed by {claim.get('job_id')} "
                f"({claim.get('status')}) — blocks same-repo admits."
            ),
            "unstick": "Run POL-008 janitor (release stale claims) or supersede zombie claim holder.",
            "target": claim.get("job_id"),
        })

    for row in held:
        hr = row.get("hold_reason") or ""
        dep = None
        m = WAITING_RE.search(hr)
        if m:
            dep = m.group(1)
        out.append({
            "type": "held_job",
            "severity": "medium",
            "detail": f"{row['job_id']} held: {hr[:120]}",
            "unstick": "Clear dependency or release repo claim; then promote_held.",
            "target": row["job_id"],
            "dependency": dep,
        })

    live_at = _parse_ts((ctx.get("bus_live") or {}).get("generated_at"))
    if live_at and BUS_DB.is_file():
        conn = sqlite3.connect(BUS_DB)
        try:
            row = conn.execute("SELECT MAX(updated_at) AS m FROM jobs").fetchone()
            db_at = _parse_ts(row[0] if row else None)
            if db_at and db_at > live_at + timedelta(minutes=2):
                out.append({
                    "type": "bus_live_stale",
                    "severity": "low",
                    "detail": "reports/bus-live.json lags jobs.sqlite — dashboard may misstate fleet.",
                    "unstick": "Run export_bus_live.py (POL-003 sync path).",
                })
        finally:
            conn.close()

    for tid, t in ctx["issue_tasks"].items():
        if wqo.is_deferred_task(tid):
            continue
        arts = t.get("artifacts") or []
        has_bus = any("agent-bus JOB-" in str(a) for a in arts)
        out_txt = t.get("output") or ""
        if not has_bus and ("bus submit failed" in out_txt or pd.DISPATCH_MARKER in out_txt):
            out.append({
                "type": "dispatch_blocked",
                "severity": "high",
                "detail": f"{tid} queued in ledger without active bus job (submit failed or never linked).",
                "unstick": f"Retry bus submit for {tid} once admission allows.",
                "target": tid,
            })
        elif (t.get("status") or "") == "in_progress" and not has_bus:
            out.append({
                "type": "ledger_drift",
                "severity": "medium",
                "detail": f"{tid} in_progress on ledger but no agent-bus artifact cited.",
                "unstick": "Reconcile ledger or dispatch worker (POL-003).",
                "target": tid,
            })

        stale = _age_minutes(t.get("ts"))
        if (t.get("status") or "") == "in_progress" and stale is not None and stale >= STALE_WIP_MIN:
            if not _executing_heartbeat_recent(task_id=tid):
                out.append({
                    "type": "stale_wip",
                    "severity": "medium",
                    "detail": f"{tid} in_progress {stale:.0f}m without POL-002 heartbeat.",
                    "unstick": "Append task_updated heartbeat or transition to blocked/idle.",
                    "target": tid,
                })

    pmo = tasks.get("PMO-001", {})
    if (pmo.get("status") or "").lower() not in ("completed", "idle"):
        running_sessions = {r.get("to_session") for r in ctx["bus_rows"] if r["status"] == "running"}
        if "pmo" not in running_sessions and counts["running"] == 0:
            out.append({
                "type": "pmo_stalled",
                "severity": "high",
                "detail": "PMO-001 not complete and no PMO worker on bus.",
                "unstick": "Dispatch PMO triage worker or set PMO-001 idle with reason.",
            })

    return out


def _executing_heartbeat_recent(*, task_id: str) -> bool:
    events = pd.load_events()
    for ev in reversed(events):
        if ev.get("task_id") != task_id:
            continue
        if ev.get("event") not in ("task_updated", "task_progress", "focus_snapshot"):
            continue
        age = _age_minutes(ev.get("ts"))
        if age is not None and age < STALE_WIP_MIN:
            return True
    return False


def compute_admission(ctx: dict, bottlenecks: list[dict]) -> dict:
    counts = ctx["counts"]
    base = ctx["ledger_base"]
    types = {b["type"] for b in bottlenecks}
    high = {b["type"] for b in bottlenecks if b.get("severity") == "high"}

    budget_ok = (
        float(base.get("weekly_budget_usd") or 0) <= 0
        or float(base.get("budget_remaining_usd") or 0) > 0
    )
    capacity_ok = counts["running"] < MAX_PARALLEL
    coding_ok = counts["coding_running"] < MAX_CODING_PARALLEL
    claim_block = "repo_claim" in types and counts["held"] > 0

    max_new = 0
    max_retry = 0
    reasons: list[str] = []

    if not budget_ok:
        reasons.append("budget exhausted")
    elif not capacity_ok:
        reasons.append(f"bus full ({counts['running']}/{MAX_PARALLEL})")
    elif not coding_ok:
        reasons.append(f"coding saturated ({counts['coding_running']}/{MAX_CODING_PARALLEL})")
    elif claim_block and counts["running"] > 0:
        reasons.append("held jobs behind repo claims while runners active — unstick first")
    else:
        max_new = 1
        reasons.append("one delegation slot available")

    if "dispatch_blocked" in types and max_new >= 1 and capacity_ok:
        max_retry = 1
        reasons.append("may retry one undispatched ISSUE-*")

    if "capacity_full" in high or "budget_exhausted" in high:
        max_new = 0
        max_retry = 0

    return {
        "max_new_delegations": max_new,
        "max_retries": max_retry,
        "budget_ok": budget_ok,
        "capacity_ok": capacity_ok,
        "coding_ok": coding_ok,
        "claim_block": claim_block,
        "reasons": reasons,
    }


def _run_promote_only(*, dry_run: bool) -> dict:
    if not BUS_JANITOR.is_file():
        return {"skipped": True, "reason": "no bus_janitor"}
    import subprocess

    cmd = [sys.executable, str(BUS_JANITOR), "--dry-run"] if dry_run else [sys.executable, str(BUS_JANITOR)]
    # Janitor always promotes; re-run is cheap after supervisor janitor pass.
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BUS_ROOT.parent), timeout=120)
    parsed = None
    for block in reversed((r.stdout or "").strip().split("\n\n")):
        block = block.strip()
        if block.startswith("{"):
            try:
                parsed = json.loads(block)
                break
            except json.JSONDecodeError:
                continue
    return parsed or {"returncode": r.returncode, "raw": (r.stdout or "")[:500]}


def _issue_item(ctx: dict, task_id: str) -> dict:
    triage = ctx.get("triage") or {}
    for item in triage.get("top_issues") or []:
        if pd.issue_task_id(item) == task_id:
            return item
    t = ctx["tasks"].get(task_id, {})
    return {
        "task_id": task_id,
        "title": t.get("task"),
        "issue_number": t.get("issue_number"),
        "worker": "coding_worker",
        "repo": "ai-agents-workspace",
    }


def execute_unstick(
    ctx: dict,
    bottlenecks: list[dict],
    admission: dict,
    *,
    dry_run: bool = False,
    append_fn: Callable[[dict], bool] | None = None,
) -> list[dict]:
    actions: list[dict] = []
    base = ctx["ledger_base"]

    stuck_types = {b["type"] for b in bottlenecks}
    if stuck_types & {"repo_claim", "held_job"} and not dry_run:
        jan = _run_promote_only(dry_run=False)
        if int(jan.get("promoted") or 0) or int(jan.get("claims_released") or 0):
            actions.append({"action": "janitor_repass", "result": jan})

    if admission.get("max_retries", 0) > 0:
        retried = _retry_one_undispatched(
            ctx, bottlenecks, dry_run=dry_run, append_fn=append_fn
        )
        if retried:
            actions.append(retried)

    if not dry_run and admission.get("max_new_delegations", 0) > 0:
        delegated = _maybe_delegate_top(ctx, dry_run=False, append_fn=append_fn)
        if delegated:
            actions.append(delegated)

    return actions


def _retry_one_undispatched(
    ctx: dict,
    bottlenecks: list[dict],
    *,
    dry_run: bool,
    append_fn: Callable[[dict], bool] | None,
) -> dict | None:
    targets = [
        b["target"]
        for b in bottlenecks
        if b["type"] == "dispatch_blocked" and b.get("target")
    ]
    if not targets:
        return None
    tid = targets[0]
    t = ctx["tasks"].get(tid, {})
    item = _issue_item(ctx, tid)
    if item.get("dispatch") is False or wqo.is_deferred_task(tid):
        return None
    worker = (item.get("worker") or "coding_worker").strip()
    repo = (item.get("repo") or "ai-agents-workspace").strip()
    objective = pd.build_objective({**item, "task_id": tid}, tid)

    if dry_run:
        return {"action": "retry_dispatch", "task_id": tid, "dry_run": True}

    bus_out = pd.submit_bus_job(
        session=worker,
        objective=objective,
        repo=repo,
        task_id=tid,
        item=item,
        from_harness="ceo-reflect",
    )
    job_id = (bus_out or {}).get("job_id") if isinstance(bus_out, dict) else None
    if job_id and not dry_run:
        bus_status = (bus_out or {}).get("status", "queued")
        status = "in_progress" if bus_status in ("running", "linked-existing") else "queued"
        pd.append_ledger(
            {
                **ctx["ledger_base"],
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "task_updated",
                "task_id": tid,
                "task": t.get("task") or item.get("title"),
                "status": status,
                "owner": worker.replace("_worker", ""),
                "output": f"{MARKER}retry dispatched {job_id} ({bus_status}).",
                "artifacts": [f"agent-bus {job_id}"],
            },
            append_fn,
        )
        pd.append_ledger(
            {
                **ctx["ledger_base"],
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "focus_snapshot",
                "task_id": "FOCUS-001",
                "focus_task_id": tid,
                "task": t.get("task") or item.get("title"),
                "status": status,
                "owner": "CEO",
                "focus_line": f"Unblocking {tid} — retried bus dispatch after bottleneck pass",
                "focus_detail": "CEO reflect retried undispatched issue within admission cap.",
                "output": f"{MARKER}focus → {tid}",
            },
            append_fn,
        )
    return {"action": "retry_dispatch", "task_id": tid, "job_id": job_id, "bus": bus_out}


def _maybe_delegate_top(
    ctx: dict,
    *,
    dry_run: bool,
    append_fn: Callable[[dict], bool] | None,
) -> dict | None:
    """Queue one ranked issue not yet on ledger — only when PMO dispatch already ran."""
    tasks = ctx["tasks"]
    if not pd.dispatch_already_done(tasks):
        return None
    triage = ctx.get("triage") or {}
    base = ctx["ledger_base"]
    for item in sorted(triage.get("top_issues") or [], key=lambda x: x.get("rank", 99)):
        if item.get("dispatch") is False or wqo.is_deferred_task(pd.issue_task_id(item)):
            continue
        tid = pd.issue_task_id(item)
        if tasks.get(tid, {}).get("status") in ("queued", "in_progress", "completed"):
            continue
        est = float(item.get("est_cost_usd") or 1.0)
        if est > float(base.get("budget_remaining_usd") or 0):
            continue
        worker = (item.get("worker") or "coding_worker").strip()
        repo = (item.get("repo") or "ai-agents-workspace").strip()
        objective = pd.build_objective({**item, "task_id": tid}, tid)
        if dry_run:
            return {"action": "delegate", "task_id": tid, "dry_run": True}
        pd.append_ledger(
            {
                **base,
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "task_queued",
                "task_id": tid,
                "task": item.get("title") or tid,
                "status": "queued",
                "owner": worker.replace("_worker", ""),
                "output": (
                    f"{MARKER}CEO queued rank-{item.get('rank')} issue within admission slot."
                ),
            },
            append_fn,
        )
        bus_out = pd.submit_bus_job(
            session=worker,
            objective=objective,
            repo=repo,
            task_id=tid,
            item=item,
            from_harness="ceo-reflect",
        )
        job_id = (bus_out or {}).get("job_id") if isinstance(bus_out, dict) else None
        return {"action": "delegate", "task_id": tid, "job_id": job_id, "bus": bus_out}
    return None


def build_proposals(ctx: dict, bottlenecks: list[dict], admission: dict) -> list[dict]:
    proposals: list[dict] = []
    for b in bottlenecks:
        proposals.append({
            "kind": "unstick",
            "bottleneck": b["type"],
            "detail": b.get("detail"),
            "suggested": b.get("unstick"),
            "target": b.get("target"),
            "auto_eligible": b["type"] in ("dispatch_blocked", "repo_claim", "held_job", "bus_live_stale"),
        })
    if admission.get("max_new_delegations", 0) == 0:
        proposals.append({
            "kind": "defer_dispatch",
            "detail": "No delegation slots — resolve bottlenecks before queuing more ISSUE-* work.",
            "suggested": "; ".join(admission.get("reasons") or []),
        })
    triage = ctx.get("triage") or {}
    for item in triage.get("top_issues") or []:
        if item.get("dispatch") is False and item.get("defer_reason"):
            proposals.append({
                "kind": "already_deferred",
                "task_id": pd.issue_task_id(item),
                "detail": item.get("defer_reason"),
            })
    return proposals


def write_artifacts(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# CEO reflection — {report.get('ts', '')}",
        "",
        "## Situation",
        f"- Running: {report['context']['counts']['running']} | "
        f"Held: {report['context']['counts']['held']} | "
        f"Queued: {report['context']['counts']['queued']}",
        f"- Budget remaining: ${report['context']['budget_remaining_usd']:.1f}",
        "",
    ]
    if report.get("bottlenecks"):
        lines.append("## Bottlenecks")
        for b in report["bottlenecks"]:
            lines.append(f"- **{b['type']}** ({b.get('severity', '?')}): {b.get('detail', '')}")
            if b.get("unstick"):
                lines.append(f"  - Unstick: {b['unstick']}")
        lines.append("")
    else:
        lines.append("## Bottlenecks\n- None detected this cycle.\n")

    lines.append("## Admission")
    adm = report.get("admission") or {}
    lines.append(f"- New delegations allowed: **{adm.get('max_new_delegations', 0)}**")
    lines.append(f"- Retries allowed: **{adm.get('max_retries', 0)}**")
    for r in adm.get("reasons") or []:
        lines.append(f"- {r}")
    lines.append("")

    if report.get("actions"):
        lines.append("## Actions taken")
        for a in report["actions"]:
            lines.append(f"- {a.get('action')}: {json.dumps(a, default=str)[:200]}")
        lines.append("")

    if report.get("proposals"):
        lines.append("## Proposals")
        for p in report["proposals"][:12]:
            lines.append(f"- [{p.get('kind')}] {p.get('detail', p.get('suggested', ''))[:160]}")
        lines.append("")

    llm = report.get("llm") or {}
    reflection = llm.get("reflection") or {}
    if reflection.get("situation_summary"):
        lines.append("## LLM reflection")
        lines.append(reflection["situation_summary"])
        lines.append("")
        if reflection.get("root_causes"):
            lines.append("### Root causes")
            for rc in reflection["root_causes"]:
                lines.append(f"- {rc}")
            lines.append("")
    if llm.get("skip_reason") and not llm.get("ran"):
        lines.append(f"_LLM reflect skipped: {llm['skip_reason']}_\n")

    MEMO_DIR.mkdir(parents=True, exist_ok=True)
    MEMO_LATEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _focus_from_report(report: dict, ctx: dict) -> tuple[str, str, str]:
    """Return (focus_task_id, focus_line, focus_detail)."""
    llm = (report.get("llm") or {}).get("reflection") or {}
    summary = (llm.get("situation_summary") or "").strip()
    counts = (report.get("context") or {}).get("counts") or {}
    running = int(counts.get("running") or 0)
    bn = int(report.get("bottleneck_count") or 0)

    for row in ctx.get("bus_rows") or []:
        if row.get("status") == "running":
            tid = row.get("job_id") or ""
            line = (row.get("feature_name") or row.get("objective") or tid)[:100]
            return tid, line, (row.get("objective") or "")[:220]

    issue_tasks = ctx.get("issue_tasks") or {}
    active = sorted(
        issue_tasks.items(),
        key=lambda kv: (kv[1].get("ts") or "") if isinstance(kv[1], dict) else "",
        reverse=True,
    )
    for tid, _t in active:
        if not wqo.is_deferred_task(tid):
            if summary:
                line = summary.split(".")[0].strip()
                return tid, line[:120], summary[:220]
            return tid, f"Unblocking {tid}", f"CEO reflect: {bn} bottleneck(s)"

    if summary:
        line = summary.split(".")[0].strip()[:120]
        return "SYS-002", line, summary[:220]
    if running:
        return "SYS-002", f"Supervising {running} running job(s)", ""
    if bn:
        return "SYS-002", f"CEO reflect — {bn} bottleneck(s) to unstick", ""
    return "SYS-002", "CEO supervision — portfolio idle", ""


def run_reflect(
    *,
    dry_run: bool = False,
    append_ledger: bool = False,
    llm: bool = False,
    force_llm: bool = False,
) -> dict:
    ctx = gather_context()
    bottlenecks = detect_bottlenecks(ctx)
    admission = compute_admission(ctx, bottlenecks)
    append_fn = pd.append_ledger if append_ledger and not dry_run else None
    actions = execute_unstick(ctx, bottlenecks, admission, dry_run=dry_run, append_fn=append_fn)
    proposals = build_proposals(ctx, bottlenecks, admission)

    llm_out: dict = {"enabled": crl.llm_enabled()}
    if llm or crl.llm_enabled():
        llm_out = crl.run_llm_reflect(
            ctx,
            bottlenecks,
            admission,
            proposals,
            force=force_llm or llm,
            dry_run=dry_run,
            append_fn=append_fn,
        )
        if llm_out.get("llm_proposals"):
            proposals = proposals + llm_out["llm_proposals"]
        if llm_out.get("actions"):
            actions = actions + llm_out["actions"]

    report = {
        "ts": ctx["ts"],
        "mode": "ceo_reflect",
        "context": {
            "counts": ctx["counts"],
            "budget_remaining_usd": float(ctx["ledger_base"].get("budget_remaining_usd") or 0),
            "weekly_budget_usd": float(ctx["ledger_base"].get("weekly_budget_usd") or 0),
        },
        "bottlenecks": bottlenecks,
        "admission": admission,
        "actions": actions,
        "proposals": proposals,
        "bottleneck_count": len(bottlenecks),
        "llm": llm_out,
    }

    if not dry_run:
        write_artifacts(report)

    if append_fn and not dry_run:
        fid, fline, fdetail = _focus_from_report(report, ctx)
        pd.append_ledger(
            {
                **ctx["ledger_base"],
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "focus_snapshot",
                "task_id": "FOCUS-001",
                "focus_task_id": fid,
                "task": "CEO supervision",
                "status": "in_progress" if bottlenecks else "completed",
                "owner": "CEO",
                "focus_line": fline,
                "focus_detail": fdetail or f"Reflect {report['ts']}",
                "output": f"{MARKER}focus → {fid}",
            },
            append_fn,
        )

    if append_fn and not dry_run and (actions or bottlenecks):
        parts = []
        if actions:
            parts.append(f"actions={len(actions)}")
        if bottlenecks:
            parts.append(f"bottlenecks={len(bottlenecks)}")
        pd.append_ledger(
            {
                **ctx["ledger_base"],
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "ceo_reflect",
                "task_id": "FOCUS-001",
                "focus_task_id": "SYS-002",
                "task": "CEO reflection and bottleneck pass",
                "status": "completed" if not bottlenecks else "in_progress",
                "owner": "CEO",
                "output": f"{MARKER} {'; '.join(parts) or 'reflect only'}",
                "artifacts": [
                    "reports/ceo-queue.json",
                    "memos/ceo-reflect/latest.md",
                ],
            },
            append_fn,
        )

    report["healthy"] = not any(b.get("severity") == "high" for b in bottlenecks)
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="CEO reflection — POL-010")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ledger", action="store_true")
    p.add_argument("--llm", action="store_true", help="Run LLM reflection (respects interval)")
    p.add_argument("--force-llm", action="store_true", help="Run LLM reflection ignoring interval")
    args = p.parse_args()
    report = run_reflect(
        dry_run=args.dry_run,
        append_ledger=args.ledger,
        llm=args.llm or args.force_llm,
        force_llm=args.force_llm,
    )
    print(json.dumps(report, indent=2))
    return 0 if report.get("healthy") else 1


if __name__ == "__main__":
    raise SystemExit(main())