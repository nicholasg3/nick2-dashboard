#!/usr/bin/env python3
"""Ensure welcome agent line exists in gate-chats for each open gate."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHATS = ROOT / "logs" / "gate-chats"
GATED = ROOT / "reports" / "gated.json"
SGT = timezone(timedelta(hours=8))

WELCOME = {
    "DEC-002": "This gate is waiting on your call for the PMO scoring framework. Chat here to approve, modify, or defer — I'll append ledger events and unblock PMO ranking.",
    "DEC-003": "Need your preference on spend alerts ($5 steps). Reply here with Telegram vs email vs dashboard-only — I'll wire the channel and log the decision.",
}


def main() -> None:
    if not GATED.exists():
        return
    items = json.loads(GATED.read_text(encoding="utf-8"))
    ts = datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")
    for g in items:
        tid = g.get("task_id")
        if not tid:
            continue
        path = CHATS / f"{tid}.jsonl"
        if path.exists() and path.stat().st_size > 0:
            continue
        text = WELCOME.get(tid, f"Gate {tid} is open. Tell me what you need to clear this blocker.")
        line = json.dumps(
            {"ts": ts, "role": "agent", "actor": "CEO", "task_id": tid, "text": text},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        CHATS.mkdir(parents=True, exist_ok=True)
        path.write_text(line + "\n", encoding="utf-8")
        print(f"seed_gate_chats: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()