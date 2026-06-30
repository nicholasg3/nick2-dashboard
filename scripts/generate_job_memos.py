#!/usr/bin/env python3
"""Generate memos/jobs/{job_id}.md from agent-bus jobs.sqlite — one brief per bus job."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMOS = ROOT / "memos" / "jobs"
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
BUS_DB = Path(
    os.environ.get(
        "AGENT_BUS_DB",
        Path.home() / "ai-agents-workspace" / "agent-bus" / "jobs.sqlite",
    )
)
BUS_ROOT = BUS_DB.parent
ACTIVE_STATUSES = {"running", "queued", "held", "blocked"}


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


def mission_for_job(job_id: str, events: list[dict]) -> str | None:
    short = short_job_id(job_id)
    needles = (job_id, short, f"`{job_id}`")
    for ev in reversed(events):
        tid = ev.get("task_id") or ""
        if not tid or tid.startswith("FOCUS-"):
            continue
        blob = " ".join(
            str(ev.get(k) or "")
            for k in ("output", "task", "artifacts")
        )
        if not any(n in blob for n in needles):
            continue
        if re.match(r"^(SYS|PMO|P-|POL-|LIT-|DEC-)", tid):
            return tid
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


def objective_text(row: sqlite3.Row, packet: dict) -> str:
    obj = (row["objective"] or packet.get("objective") or "").strip()
    return obj or "(no objective text in bus record)"


def first_paragraph(text: str, limit: int = 400) -> str:
    chunk = text.strip().split("\n\n")[0].replace("\n", " ")
    return chunk[:limit] + ("…" if len(chunk) > limit else "")


def job_memo_body(row: sqlite3.Row, packet: dict, mission_id: str | None) -> str:
    job_id = row["job_id"]
    short = short_job_id(job_id)
    feature = row["feature_name"] or packet.get("feature_name") or "job"
    objective = objective_text(row, packet)
    status = row["status"] or "unknown"
    worker_status = row["worker_status"] or status
    session = row["to_session"] or packet.get("to") or "—"
    repo = row["repo"] or packet.get("repo") or "—"
    branch = row["branch"] or packet.get("branch") or "—"
    hold = (row["hold_reason"] or "").strip()
    updated = row["updated_at"] or "—"
    lines = [
        f"# {short} — {feature}",
        "",
        f"**Full ID:** `{job_id}`",
        "",
        "## SITUATION",
        "",
        first_paragraph(objective),
        "",
        "## STATUS",
        "",
        f"- **Bus status:** {status}",
        f"- **Worker phase:** {worker_status}",
        f"- **Session:** {session}",
        f"- **Repo:** {repo}",
        f"- **Branch:** `{branch}`" if branch != "—" else "- **Branch:** —",
        f"- **Last updated:** {updated}",
        "",
    ]
    if hold:
        lines += ["## BLOCKERS", "", hold, ""]
    if mission_id:
        lines += [
            "## MISSION LINK",
            "",
            f"Ledger mission **[{mission_id}](memo.html?p=memos/queue/{mission_id}.md)** — see queue brief for portfolio context.",
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


def main() -> int:
    if not BUS_DB.is_file():
        print("generate_job_memos: no jobs.sqlite — skipped")
        return 0
    events = load_ledger()
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    MEMOS.mkdir(parents=True, exist_ok=True)
    keep: set[str] = set()
    for job_id in active_job_ids(conn):
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            continue
        packet = load_packet(job_id, row["packet_path"])
        mission_id = mission_for_job(job_id, events)
        body = job_memo_body(row, packet, mission_id)
        path = MEMOS / f"{job_id}.md"
        path.write_text(body + "\n", encoding="utf-8")
        keep.add(job_id)
    for path in MEMOS.glob("JOB-*.md"):
        if path.stem not in keep:
            path.unlink(missing_ok=True)
    print(f"generate_job_memos: wrote {len(keep)} under {MEMOS.relative_to(ROOT)}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())