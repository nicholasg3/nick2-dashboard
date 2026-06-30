#!/usr/bin/env python3
"""Active work queue operations — remove/defer tasks Nick steers off the board."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import job_catalog as jc  # noqa: E402
import pmo_dispatch as pd  # noqa: E402

LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
BUS = Path(
    os.environ.get(
        "AGENT_BUS_ROOT",
        ROOT.parent / "ai-agents-workspace" / "agent-bus",
    )
)
BUS_DB = BUS / "jobs.sqlite"
MARKER = "work-queue:"
SGT = timezone(timedelta(hours=8))

REMOVE_PATTERNS = (
    r"\btake\s+(it\s+)?out\b",
    r"\bpull\s+(it\s+)?off\b",
    r"\bremove\s+(it|this|from)",
    r"\boff\s+the\s+(active\s+)?queue\b",
    r"\bout\s+of\s+the\s+(active\s+)?queue\b",
    r"\bstop\s+(working|this|on)\b",
    r"\bdon'?t\s+(run|dispatch|work)",
    r"\bdo\s+not\s+(run|dispatch|work)",
    r"\bcancel\s+(this|it|the)\b",
    r"\bdefer\s+(this|it)\b",
    r"\bpark\s+(this|it)\b",
    r"\bnot\s+an?\s+agent\s+task\b",
    r"\bpersonal\s+(queue|decision)\b",
)


def now_sgt() -> str:
    return datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")


def deferred_task_ids() -> set[str]:
    data = pd.load_triage_result() or {}
    out: set[str] = set()
    for item in data.get("top_issues") or []:
        if item.get("dispatch") is False:
            out.add(pd.issue_task_id(item))
    return out


def triage_item(task_id: str) -> dict:
    data = pd.load_triage_result() or {}
    for item in data.get("top_issues") or []:
        if pd.issue_task_id(item) == task_id:
            return item
    return {}


def is_deferred_task(task_id: str) -> bool:
    if task_id in deferred_task_ids():
        return True
    item = triage_item(task_id)
    cat = jc.load_catalog().get("tasks", {}).get(task_id, {})
    return jc.is_decision_gated(item, cat)


def looks_remove_instruction(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    for pat in REMOVE_PATTERNS:
        if re.search(pat, t, re.I):
            return True
    return False


def _append_ledger(event: dict) -> None:
    event.setdefault("ts", now_sgt())
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    prefix = ""
    if LEDGER.exists() and LEDGER.stat().st_size > 0:
        if not LEDGER.read_bytes().endswith(b"\n"):
            prefix = "\n"
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")


def _supersede_via_janitor(task_id: str, reason: str) -> dict:
    janitor = BUS / "scripts" / "bus_janitor.py"
    if not janitor.is_file():
        return {"skipped": True}
    cmd = [
        sys.executable,
        str(janitor),
        "--deferred-json",
        json.dumps({task_id: reason}),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BUS.parent), timeout=120)
    parsed = None
    for block in reversed((r.stdout or "").strip().split("\n\n")):
        block = block.strip()
        if block.startswith("{"):
            try:
                parsed = json.loads(block)
                break
            except json.JSONDecodeError:
                continue
    return parsed or {"returncode": r.returncode}


def remove_from_active_queue(
    task_id: str,
    note: str,
    *,
    actor: str = "Nicholas",
    supersede: bool = True,
) -> dict:
    """Move task off Active Work Queue — ledger idle + supersede bus packets."""
    events = pd.load_events()
    tasks = pd.task_state(events)
    t = tasks.get(task_id, {})
    title = t.get("task") or task_id
    reason = note.strip() or "Removed from active queue by Nicholas."
    defer = triage_item(task_id).get("defer_reason") or ""
    if is_deferred_task(task_id) and defer:
        reason = f"{reason} ({defer})"

    base = pd.ledger_base(events)
    _append_ledger(
        {
            **base,
            "actor": actor,
            "role": "Owner",
            "event": "work_removed",
            "task_id": task_id,
            "task": title,
            "status": "idle",
            "owner": t.get("owner") or "CEO",
            "output": f"{MARKER}{reason}",
            "needs_nicholas": is_deferred_task(task_id),
            "artifacts": t.get("artifacts") or [],
        }
    )

    janitor_out: dict = {}
    if supersede:
        janitor_out = _supersede_via_janitor(
            task_id,
            f"Nick removed {task_id} from active queue — {reason[:120]}",
        )

    refresh = ROOT / "scripts" / "export-json-reports.py"
    if refresh.is_file():
        subprocess.run(
            [sys.executable, str(refresh)],
            cwd=str(ROOT),
            capture_output=True,
            timeout=60,
        )
    memos = ROOT / "scripts" / "generate-memos.py"
    if memos.is_file():
        subprocess.run(
            [sys.executable, str(memos)],
            cwd=str(ROOT),
            capture_output=True,
            timeout=120,
        )

    return {
        "removed": True,
        "task_id": task_id,
        "status": "idle",
        "janitor": janitor_out,
        "deferred": is_deferred_task(task_id),
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Remove task from active work queue")
    p.add_argument("task_id")
    p.add_argument("--note", default="Removed from active queue.")
    p.add_argument("--no-supersede", action="store_true")
    args = p.parse_args()
    out = remove_from_active_queue(
        args.task_id,
        args.note,
        supersede=not args.no_supersede,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())