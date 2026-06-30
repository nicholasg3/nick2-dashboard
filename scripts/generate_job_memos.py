#!/usr/bin/env python3
"""Generate memos/jobs/{job_id}.md from agent-bus jobs.sqlite — one brief per bus job."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMOS = ROOT / "memos" / "jobs"
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
PMO_RESULT = ROOT / "pmo_001_result.json"
BUS_DB = Path(
    os.environ.get(
        "AGENT_BUS_DB",
        Path.home() / "ai-agents-workspace" / "agent-bus" / "jobs.sqlite",
    )
)
BUS_ROOT = BUS_DB.parent
DASHBOARD = "https://nicholasg3.github.io/nick2-dashboard/"
ACTIVE_STATUSES = {"running", "queued", "held", "blocked"}
MISSION_ID_RE = re.compile(r"^(SYS|PMO|P-|POL-|LIT-|DEC-|DISPATCH-|ISSUE-)")


def short_job_id(job_id: str) -> str:
    m = re.match(r"^JOB-(\d{8})-(\d+)$", job_id or "")
    return f"JOB-{m.group(2)}" if m else (job_id or "")


def load_ledger() -> list[dict]:
    if not LEDGER.is_file():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def task_state(events: list[dict]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for ev in events:
        tid = ev.get("task_id")
        if tid:
            tasks[tid] = {**tasks.get(tid, {}), **ev}
    return tasks


def ledger_task_for_job(job_id: str, events: list[dict]) -> str | None:
    """Resolve ISSUE-* / DISPATCH-* ledger row tied to this bus job."""
    short = short_job_id(job_id)
    needles = (job_id, short, f"`{job_id}`", f"agent-bus {job_id}")
    for ev in reversed(events):
        tid = ev.get("task_id") or ""
        if not tid or tid.startswith("FOCUS-"):
            continue
        if not MISSION_ID_RE.match(tid):
            continue
        blob = " ".join(str(ev.get(k) or "") for k in ("output", "task", "artifacts"))
        arts = ev.get("artifacts") or []
        if isinstance(arts, list):
            blob += " " + " ".join(str(a) for a in arts)
        if any(n in blob for n in needles):
            return tid
    return None


def mission_for_job(job_id: str, events: list[dict]) -> str | None:
    return ledger_task_for_job(job_id, events)


def load_pmo_index() -> dict[str, dict]:
    if not PMO_RESULT.is_file():
        return {}
    try:
        data = json.loads(PMO_RESULT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, dict] = {}
    for item in data.get("top_issues") or []:
        tid = item.get("task_id")
        if not tid:
            num = item.get("issue_number")
            tid = f"ISSUE-{int(num)}" if num is not None else f"ISSUE-R{item.get('rank', 0)}"
        out[tid] = item
        obj = (item.get("objective") or "").strip()
        if obj:
            out[obj[:80]] = item
    return out


def resolve_ledger_task(
    job_id: str,
    objective: str,
    events: list[dict],
    tasks: dict[str, dict],
    pmo_item: dict | None,
    feature: str,
) -> tuple[str | None, dict]:
    """Best-effort ledger row for this bus job (artifact link, PMO index, or objective match)."""
    tid = ledger_task_for_job(job_id, events)
    if tid:
        return tid, tasks.get(tid, {})
    if pmo_item:
        if pmo_item.get("task_id") and pmo_item["task_id"] in tasks:
            return str(pmo_item["task_id"]), tasks[str(pmo_item["task_id"])]
        num = pmo_item.get("issue_number")
        if num is not None:
            cand = f"ISSUE-{int(num)}"
            if cand in tasks:
                return cand, tasks[cand]
    m = re.search(r"ISSUE-([A-Z0-9-]+)", objective, re.I)
    if m:
        for cand in (f"ISSUE-{m.group(1).upper()}", f"ISSUE-{m.group(1)}"):
            if cand in tasks:
                return cand, tasks[cand]
        num_m = re.match(r"^(\d+)$", m.group(1))
        if num_m:
            cand = f"ISSUE-{int(num_m.group(1))}"
            if cand in tasks:
                return cand, tasks[cand]
    if feature:
        fm = re.search(r"issue-(\d+)", feature)
        if fm:
            cand = f"ISSUE-{int(fm.group(1))}"
            if cand in tasks:
                return cand, tasks[cand]
    obj_head = objective.split("\n")[0][:60]
    for tid, t in tasks.items():
        if not tid.startswith("ISSUE-"):
            continue
        if obj_head and obj_head in (t.get("output") or ""):
            return tid, t
    return None, {}


def pmo_item_for_job(objective: str, ledger_tid: str | None, pmo_index: dict) -> dict | None:
    if ledger_tid and ledger_tid in pmo_index:
        return pmo_index[ledger_tid]
    obj = objective.strip()
    for key, item in pmo_index.items():
        if key in obj or obj.startswith(key):
            return item
    for item in pmo_index.values():
        if isinstance(item, dict) and (item.get("objective") or "").strip() in obj:
            return item
    return None


def load_packet(job_id: str, packet_path: str | None) -> dict:
    candidates = []
    if packet_path:
        candidates.append(Path(packet_path))
    candidates.extend(
        [
            BUS_ROOT / "logs" / f"{job_id}.packet.json",
            BUS_ROOT / "hold" / f"{job_id}.json",
        ]
    )
    for p in candidates:
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def running_started_at(job_id: str) -> str | None:
    run_file = BUS_ROOT / "running" / f"{job_id}.json"
    if not run_file.is_file():
        return None
    try:
        data = json.loads(run_file.read_text(encoding="utf-8"))
        return data.get("started_at") or None
    except (json.JSONDecodeError, OSError):
        return None


def parse_utc(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def elapsed_phrase(ts: str) -> str:
    dt = parse_utc(ts)
    if not dt:
        return "—"
    delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    mins = int(delta.total_seconds() / 60)
    if mins < 2:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    rem = mins % 60
    return f"{hours}h {rem}m ago" if rem else f"{hours}h ago"


def duplicate_siblings(
    conn: sqlite3.Connection, feature: str, job_id: str
) -> list[tuple[str, str]]:
    if not feature:
        return []
    rows = conn.execute(
        """SELECT job_id, status FROM jobs
           WHERE feature_name=? AND job_id!=?
           ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'held' THEN 1
                                WHEN 'queued' THEN 2 ELSE 3 END, updated_at DESC""",
        (feature, job_id),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def repo_claim_job(conn: sqlite3.Connection, repo: str, exclude: str) -> str | None:
    if not repo:
        return None
    row = conn.execute(
        """SELECT job_id FROM jobs
           WHERE repo=? AND status='running' AND job_id!=?
           ORDER BY updated_at DESC LIMIT 1""",
        (repo, exclude),
    ).fetchone()
    return row[0] if row else None


def load_report_snippet(report_path: str | None, limit: int = 600) -> str | None:
    if not report_path:
        return None
    p = Path(report_path)
    if not p.is_file():
        p = BUS_ROOT / "reports" / f"{Path(report_path).name}"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text[:limit] + ("…" if len(text) > limit else "")


def objective_text(row: sqlite3.Row, packet: dict) -> str:
    obj = (row["objective"] or packet.get("objective") or "").strip()
    return obj or "(no objective text in bus record)"


def spoken_title(objective: str, feature: str, pmo_item: dict | None) -> str:
    if pmo_item and pmo_item.get("title"):
        return str(pmo_item["title"])
    first = objective.split("\n")[0].strip()
    if ":" in first:
        first = first.split(":", 1)[1].strip()
    if first and first != "(no objective text in bus record)":
        return first[:80] + ("…" if len(first) > 80 else "")
    return feature.replace("-", " ")


def situation_paragraph(
    *,
    objective: str,
    pmo_item: dict | None,
    ledger_tid: str | None,
    ledger_task: dict | None,
    parent_dispatch: dict | None,
) -> str:
    parts: list[str] = []
    if pmo_item:
        rank = pmo_item.get("rank")
        roi = pmo_item.get("roi")
        area = pmo_item.get("area") or "—"
        parts.append(
            f"PMO-001 triage ranked this **#{rank}** (ROI {roi:.2f}, area `{area}`) "
            f"after JOB-792 completed analysis."
        )
    elif ledger_tid:
        parts.append(f"Ledger mission **{ledger_tid}** was dispatched to the agent-bus.")
    else:
        parts.append("Agent-bus worker job — see objective for scope.")

    if parent_dispatch:
        out = (parent_dispatch.get("output") or "")[:120]
        parts.append(f"Part of **DISPATCH-001** batch ({out or 'PMO post-triage dispatch'}).")

    if ledger_task:
        task_name = ledger_task.get("task") or ledger_tid
        parts.append(f"Portfolio task: *{task_name}*.")

    gist = objective.split("\n\n")[0].replace("\n", " ").strip()
    if gist and gist != "(no objective text in bus record)":
        parts.append(gist)
    return " ".join(parts)


def where_it_stands(
    *,
    row: sqlite3.Row,
    started: str | None,
    siblings: list[tuple[str, str]],
    repo_claim: str | None,
    report: str | None,
) -> str:
    status = row["status"] or "unknown"
    worker = row["worker_status"] or status
    updated = row["updated_at"] or ""
    hold = (row["hold_reason"] or "").strip()
    lines: list[str] = []

    if status == "running":
        since = started or updated
        lines.append(
            f"**Executing** on `{row['repo'] or '—'}` — worker phase `{worker}`, "
            f"last bus touch **{elapsed_phrase(updated)}**"
            + (f" (started {elapsed_phrase(since)})." if since else ".")
        )
        if elapsed_phrase(updated) not in ("just now",) and parse_utc(updated):
            age = datetime.now(timezone.utc) - parse_utc(updated).astimezone(timezone.utc)
            if age > timedelta(minutes=12):
                lines.append(
                    f"> **Watch:** no bus heartbeat in **{int(age.total_seconds() / 60)}m** — "
                    "coding_worker timeout is 15m; may stall or block without report."
                )
    elif status == "held":
        lines.append(f"**Held** — not executing. {hold or 'Waiting on dependency or repo lock.'}")
    elif status == "queued":
        if hold:
            lines.append(f"**Queued** — {hold}")
        elif repo_claim:
            lines.append(
                f"**Queued** — `{row['repo']}` is claimed by **{short_job_id(repo_claim)}** "
                f"(`{repo_claim}`) until that job finishes."
            )
        else:
            lines.append("**Queued** — waiting for scheduler slot.")
    else:
        lines.append(f"Bus status **{status}** (worker `{worker}`).")

    if siblings:
        dup = ", ".join(f"{short_job_id(j)} ({s})" for j, s in siblings[:6])
        extra = f" (+{len(siblings) - 6} more)" if len(siblings) > 6 else ""
        lines.append(
            f"**Duplicate packets:** {len(siblings) + 1} jobs share this feature — "
            f"this memo is `{short_job_id(row['job_id'])}`; siblings: {dup}{extra}. "
            "Only one should run per repo; cancel extras via PMO/bus cleanup."
        )

    if report:
        lines.append(f"**Latest worker report:**\n\n{report}")
    return "\n\n".join(lines)


def effort_block(row: sqlite3.Row, started: str | None, events: list[dict]) -> str:
    updated = row["updated_at"] or ""
    since = started or row["created_at"] or updated
    weekly = 0.0
    remaining = 0.0
    for ev in reversed(events):
        if ev.get("weekly_budget_usd"):
            weekly = float(ev["weekly_budget_usd"])
            remaining = float(ev.get("budget_remaining_usd") or weekly)
            break
    time_line = f"Time in state: **{elapsed_phrase(since)}** · last touch **{elapsed_phrase(updated)}**"
    work_line = (
        f"Work: `{row['to_session'] or '—'}` on `{row['repo'] or '—'}`"
        f" · branch `{row['branch'] or '—'}`"
    )
    budget_line = (
        f"Budget: spent $0.00 · remaining ${remaining:.2f} · limit ${weekly:.2f}/week"
        if weekly > 0
        else "Budget: weekly cap not set on ledger tail"
    )
    return f"- **Time:** {time_line}\n- **Work:** {work_line}\n- **Budget:** {budget_line}"


def job_memo_body(
    row: sqlite3.Row,
    packet: dict,
    *,
    events: list[dict],
    tasks: dict[str, dict],
    pmo_index: dict[str, dict],
    conn: sqlite3.Connection,
) -> str:
    job_id = row["job_id"]
    short = short_job_id(job_id)
    feature = row["feature_name"] or packet.get("feature_name") or "job"
    objective = objective_text(row, packet)
    pmo_item = pmo_item_for_job(objective, None, pmo_index)
    ledger_tid, ledger_task = resolve_ledger_task(
        job_id, objective, events, tasks, pmo_item, feature
    )
    if not pmo_item and ledger_tid:
        pmo_item = pmo_item_for_job(objective, ledger_tid, pmo_index)
    parent_dispatch = tasks.get("DISPATCH-001", {})
    title = spoken_title(objective, feature, pmo_item)
    started = running_started_at(job_id) if row["status"] == "running" else None
    siblings = duplicate_siblings(conn, feature, job_id)
    repo_claim = repo_claim_job(conn, row["repo"] or "", job_id)
    report = load_report_snippet(row["report_path"])
    hold = (row["hold_reason"] or "").strip()

    back = DASHBOARD + "index.html"
    lines = [
        f"# {short} — {title}",
        "",
        f"**Full ID:** `{job_id}` · [← Dashboard]({back})",
        "",
        "## SITUATION",
        "",
        situation_paragraph(
            objective=objective,
            pmo_item=pmo_item,
            ledger_tid=ledger_tid,
            ledger_task=ledger_task,
            parent_dispatch=parent_dispatch,
        ),
        "",
        "## WHERE IT STANDS",
        "",
        where_it_stands(
            row=row,
            started=started,
            siblings=siblings,
            repo_claim=repo_claim,
            report=report,
        ),
        "",
        "## EFFORT & COST",
        "",
        effort_block(row, started, events),
        "",
    ]

    if hold and row["status"] != "held":
        lines += ["## BLOCKERS", "", hold, ""]

    if ledger_tid:
        queue_path = f"{DASHBOARD}memos/queue/{ledger_tid}.html"
        lines += [
            "## LINKS",
            "",
            f"- Portfolio brief: [{ledger_tid}]({queue_path})",
        ]
        if pmo_item and pmo_item.get("issue_number"):
            num = pmo_item["issue_number"]
            lines.append(
                f"- GitHub issue: [nicholasg3/ai-agents-workspace#{num}]"
                f"(https://github.com/nicholasg3/ai-agents-workspace/issues/{num})"
            )
        ledger_ref = (
            str(LEDGER.relative_to(ROOT))
            if LEDGER.is_relative_to(ROOT)
            else str(LEDGER)
        )
        lines += [
            f"- CEO ledger: `{ledger_ref}` (search `{ledger_tid}` or `{job_id}`)",
            f"- Bus packet: `agent-bus/logs/{job_id}.packet.json`",
            "",
        ]
    else:
        ledger_ref = (
            str(LEDGER.relative_to(ROOT))
            if LEDGER.is_relative_to(ROOT)
            else str(LEDGER)
        )
        lines += [
            "## LINKS",
            "",
            f"- CEO ledger: `{ledger_ref}`",
            f"- Bus packet: `agent-bus/logs/{job_id}.packet.json`",
            "",
        ]

    lines += ["## OBJECTIVE (full)", "", "```", objective, "```", ""]
    constraints = packet.get("constraints") or []
    if constraints:
        lines += ["## CONSTRAINTS", ""] + [f"- {c}" for c in constraints[:8]] + [""]
    return "\n".join(lines)


def active_job_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT job_id FROM jobs
           WHERE status IN ('running','queued','held','blocked')
           ORDER BY updated_at DESC"""
    ).fetchall()
    done = conn.execute(
        """SELECT job_id FROM jobs WHERE status='completed'
           ORDER BY updated_at DESC LIMIT 8"""
    ).fetchall()
    seen: set[str] = set()
    out: list[str] = []
    for (jid,) in list(rows) + list(done):
        if jid not in seen:
            seen.add(jid)
            out.append(jid)
    return out


JOB_MEMO_REQUIRED = (
    "## SITUATION",
    "## WHERE IT STANDS",
    "## EFFORT & COST",
    "## LINKS",
)
JOB_MEMO_FORBIDDEN = (
    "## STATUS\n\n- **Bus status:**",
    "(no objective text in bus record)",
)


def validate_job_memo(body: str, job_id: str) -> list[str]:
    """POL-005 gate — refuse empty/boilerplate job briefs."""
    errors: list[str] = []
    for section in JOB_MEMO_REQUIRED:
        if section not in body:
            errors.append(f"{job_id}: missing {section}")
    for bad in JOB_MEMO_FORBIDDEN:
        if bad in body:
            errors.append(f"{job_id}: boilerplate marker {bad!r}")
    situation = ""
    if "## SITUATION" in body:
        situation = body.split("## SITUATION", 1)[1].split("##", 1)[0].strip()
    if len(situation) < 40:
        errors.append(f"{job_id}: SITUATION too thin ({len(situation)} chars)")
    return errors


def main() -> int:
    if not BUS_DB.is_file():
        print("generate_job_memos: no jobs.sqlite — skipped")
        return 0
    events = load_ledger()
    tasks = task_state(events)
    pmo_index = load_pmo_index()
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    MEMOS.mkdir(parents=True, exist_ok=True)
    keep: set[str] = set()
    validation_errors: list[str] = []
    for job_id in active_job_ids(conn):
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            continue
        packet = load_packet(job_id, row["packet_path"])
        body = job_memo_body(
            row,
            packet,
            events=events,
            tasks=tasks,
            pmo_index=pmo_index,
            conn=conn,
        )
        validation_errors.extend(validate_job_memo(body, job_id))
        path = MEMOS / f"{job_id}.md"
        path.write_text(body + "\n", encoding="utf-8")
        keep.add(job_id)
    if validation_errors:
        for err in validation_errors:
            print(f"generate_job_memos: POL-005 {err}", file=sys.stderr)
        conn.close()
        return 1
    for path in MEMOS.glob("JOB-*.md"):
        if path.stem not in keep:
            path.unlink(missing_ok=True)
    print(f"generate_job_memos: wrote {len(keep)} under {MEMOS.relative_to(ROOT)}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())