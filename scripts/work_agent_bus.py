#!/usr/bin/env python3
"""Bridge work-room chat to agent-bus — routes queue tasks by owner."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import work_queue_ops as wqo  # noqa: E402

BUS = Path(
    os.environ.get(
        "AGENT_BUS_ROOT",
        ROOT.parent / "ai-agents-workspace" / "agent-bus",
    )
)
CHATS = ROOT / "logs" / "work-chats"


def worker_for_meta(meta: dict, message: str) -> str:
    owner = (meta.get("owner") or meta.get("actor") or "").lower()
    msg = (message or "").lower()
    if "dashboard" in owner:
        return "dashboard_worker"
    if owner == "pmo":
        return "pmo"
    if owner == "ceo":
        return "pmo"
    if "dashboard" in msg:
        return "dashboard_worker"
    return "pmo"


def load_chat_history(task_id: str) -> list[dict]:
    path = CHATS / f"{task_id}.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def format_history(history: list[dict], limit: int = 30) -> list[str]:
    lines: list[str] = []
    for m in history[-limit:]:
        who = m.get("actor") or m.get("role") or "?"
        text = (m.get("text") or "").replace("\n", " ").strip()
        if text:
            lines.append(f"[{who}] {text}")
    return lines


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print("No work payload on stdin.", file=sys.stderr)
        return 1
    payload = json.loads(raw)
    task_id = payload.get("task_id") or ""
    message = (payload.get("message") or "").strip()
    meta = payload.get("meta") or {}
    history = load_chat_history(task_id)

    if wqo.looks_remove_instruction(message):
        result = wqo.remove_from_active_queue(task_id, message, actor="Nicholas")
        print(
            f"Removed **{task_id}** from the active work queue (idle). "
            f"No new worker dispatched.\n\n"
            f"Nick: \"{message[:280]}\""
            + (
                "\n\nDecision-gated — stays on Nick's queue, not agents."
                if result.get("deferred")
                else ""
            )
        )
        return 0

    session = worker_for_meta(meta, message)
    title = meta.get("task") or task_id
    objective = f"Work task {task_id} ({title}): Nick instructs — {message[:400]}"

    context = [
        f"Source: nick2-dashboard work room for {task_id}.",
        f"Owner: {meta.get('owner') or meta.get('actor', '')}",
        f"Status: {meta.get('status', '')}",
        f"Latest output: {(meta.get('output') or '')[:500]}",
        "Append task_updated to the ledger when you act. Do not ask Nick to merge branches — auto-merge handles that.",
        "Work chat history:",
        *format_history(history),
    ]

    bus_script = BUS / "scripts" / "bus.py"
    if not bus_script.is_file():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"agent-bus not found at {bus_script}",
                    "session": session,
                }
            )
        )
        return 0

    repo = "nick2-dashboard"
    if task_id.startswith("PMO") or "github issues" in title.lower():
        repo = "ai-agents-workspace"

    cmd = [
        "python3",
        str(bus_script),
        "submit",
        "--to",
        session,
        "--task-type",
        "situation_assessment",
        "--from-harness",
        "work-bridge",
        "--repo",
        repo,
        "--objective",
        objective,
    ]
    for line in context:
        cmd.extend(["--context", line])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(BUS.parent))
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        job_id = None
        if out:
            try:
                job_id = json.loads(out).get("job_id")
            except json.JSONDecodeError:
                pass
        reply = (
            f"Dispatched to **{session}**"
            + (f" as `{job_id}`" if job_id else "")
            + f" for **{task_id}**.\n\n"
            f"Nick: \"{message[:280]}\"\n\n"
            "Worker will act on this instruction and update the ledger when processed."
        )
        if err and r.returncode != 0:
            reply += f"\n\n(bus warning: {err[:200]})"
        print(reply)
        return 0 if r.returncode == 0 else 1
    except Exception as e:
        print(f"Failed to dispatch work {task_id} to {session}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())