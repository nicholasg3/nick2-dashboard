#!/usr/bin/env python3
"""Clear agent-bus zombie rows: running in DB but worker PID dead."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = Path.home() / "ai-agents-workspace"
sys.path.insert(0, str(AGENT_ROOT / "agent-bus" / "scripts"))
import scheduler as sched  # noqa: E402

BUS = AGENT_ROOT / "agent-bus"
DB = BUS / "jobs.sqlite"
RUNNING = BUS / "running"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def requeue(conn: sqlite3.Connection, job_id: str, session: str) -> None:
    packet_src = BUS / "logs" / f"{job_id}.packet.json"
    if not packet_src.is_file():
        hold_src = BUS / "hold" / f"{job_id}.json"
        if hold_src.is_file():
            packet_src = hold_src
        else:
            print(f"skip {job_id}: no packet to restore")
            return
    inbox = BUS / "inbox" / session / f"{job_id}.json"
    packet = json.loads(packet_src.read_text(encoding="utf-8"))
    packet["worker_status"] = "queued"
    packet["display_name"] = sched.display_name(
        packet.get("feature_name", "job"),
        packet.get("lane", "?"),
        "queued",
    )
    sched.write_packet(inbox, packet)
    sched.release_claim(conn, job_id)
    (RUNNING / f"{job_id}.json").unlink(missing_ok=True)
    conn.execute(
        """UPDATE jobs SET status='queued', worker_status='queued', hold_reason=NULL,
           packet_path=?, updated_at=?, report_path=NULL WHERE job_id=?""",
        (str(inbox), now(), job_id),
    )
    conn.commit()
    print(f"requeued {job_id} -> {inbox}")


def archive_stale_report(job_id: str) -> None:
    report_path = BUS / "outbox" / f"{job_id}.json"
    if not report_path.is_file():
        return
    archive = BUS / "outbox" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / f"{job_id}-{int(datetime.now(timezone.utc).timestamp())}.json"
    report_path.rename(dest)
    print(f"archived stale report {job_id}")


def main() -> int:
    if not DB.is_file():
        print("no jobs.sqlite", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB)
    sched.init_scheduler_schema(conn)
    rows = conn.execute(
        "SELECT job_id, to_session FROM jobs WHERE status='running'"
    ).fetchall()
    healed = 0
    for job_id, session in rows:
        meta_path = RUNNING / f"{job_id}.json"
        alive = False
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            alive = pid_alive(int(meta.get("pid") or 0))
        if alive:
            print(f"ok {job_id}: pid still running")
            continue
        archive_stale_report(job_id)
        requeue(conn, job_id, session)
        healed += 1
    # stale running markers for completed jobs
    for path in RUNNING.glob("JOB-*.json"):
        job_id = path.stem
        row = conn.execute(
            "SELECT status FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if not row or row[0] != "running":
            path.unlink(missing_ok=True)
            print(f"removed stale running marker {job_id}")
    promoted = sched.promote_held(conn, lambda s: BUS / "inbox" / s)
    if promoted:
        print("promoted held:", ", ".join(promoted))
    conn.close()
    print(f"healed {healed} zombie(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())