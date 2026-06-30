#!/usr/bin/env python3
"""Bridge gate-room chat to agent-bus — routes DEC-* gates to PMO with full context."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
BUS = Path(
    os.environ.get(
        "AGENT_BUS_ROOT",
        ROOT.parent / "ai-agents-workspace" / "agent-bus",
    )
)
CHATS = ROOT / "logs" / "gate-chats"


def worker_for_task(task_id: str, message: str) -> str:
    tid = (task_id or "").upper()
    msg = (message or "").lower()
    if tid.startswith("DEC-"):
        return "pmo"
    if tid.startswith("CFO-") or "spend" in msg or "budget" in msg or "telegram alert" in msg:
        return "hermes"
    if "dashboard" in msg or "github pages" in msg:
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


def looks_resolved(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    if t.startswith("[gate cleared]"):
        return True
    if re.search(r"\b(clear(ed)?|resolve(d)?)\b.*\bgate\b", t):
        return True
    if re.search(r"\b(approve|approved|approve-with-weights|defer|deferred|reject|rejected)\b", t):
        return True
    return False


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print("No gate payload on stdin.", file=sys.stderr)
        return 1
    payload = json.loads(raw)
    task_id = payload.get("task_id") or ""
    message = (payload.get("message") or "").strip()
    brief = payload.get("brief") or {}
    history = load_chat_history(task_id)

    session = worker_for_task(task_id, message)
    title = brief.get("title") or task_id
    objective = f"Gate {task_id} ({title}): Nick says — {message[:400]}"

    context = [
        f"Source: nick2-dashboard gate room for {task_id}.",
        f"Objective: {brief.get('objective', '')}",
        f"Decision: {brief.get('decision', '')}",
        f"What Nick must do: {brief.get('what_nick_must_do', '')}",
        f"Recommendation: {brief.get('recommendation', '')}",
        "If Nick approved or cleared the gate, append decision_resolved / nick_gate_resolved to the ledger, "
        "refresh reports/gated.json, and take the appropriate PMO action (do not wait for another prompt).",
        "Gate chat history:",
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
                    "would_resolve": looks_resolved(message),
                }
            )
        )
        return 0

    cmd = [
        "python3",
        str(bus_script),
        "submit",
        "--to",
        session,
        "--task-type",
        "situation_assessment",
        "--from-harness",
        "gate-bridge",
        "--repo",
        "nick2-dashboard",
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
        )
        if looks_resolved(message):
            reply += "Treating this as a gate clearance — ledger will be updated and the queue refreshed."
        else:
            reply += "Worker will act on this instruction and reply when processed."
        if err and r.returncode != 0:
            reply += f"\n\n(bus warning: {err[:200]})"
        print(reply)
        return 0 if r.returncode == 0 else 1
    except Exception as e:
        print(f"Failed to dispatch gate {task_id} to {session}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())