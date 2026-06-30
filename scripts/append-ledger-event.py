#!/usr/bin/env python3
"""Safely append one JSON event to logs/ceo-ledger.jsonl (append-only).

Usage:
  python3 scripts/append-ledger-event.py '{"actor":"CEO","event":"task_started",...}'
  python3 scripts/append-ledger-event.py --file event.json
  echo '{"actor":"PMO",...}' | python3 scripts/append-ledger-event.py

If `ts` is omitted, current Singapore time is added automatically.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
SGT = timezone(timedelta(hours=8))


def now_sgt() -> str:
    return datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")


def load_event(args: argparse.Namespace) -> dict:
    if args.file:
        return json.loads(Path(args.file).read_text(encoding="utf-8"))
    raw = sys.stdin.read().strip() if not args.json else args.json
    if not raw:
        raise SystemExit("No JSON provided. Pass as argument, --file, or stdin.")
    return json.loads(raw)


def append_event(event: dict) -> None:
    if "ts" not in event or not event["ts"]:
        event["ts"] = now_sgt()
    if "actor" not in event:
        raise SystemExit("Event must include 'actor'.")
    if "event" not in event:
        raise SystemExit("Event must include 'event'.")

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with LEDGER.open("a", encoding="utf-8") as f:
        if LEDGER.stat().st_size > 0:
            f.seek(-1, 2)
            if f.read(1) != "\n":
                f.write("\n")
        f.write(line + "\n")
    print(f"Appended to {LEDGER.relative_to(ROOT)}")
    print(line)


def main() -> None:
    p = argparse.ArgumentParser(description="Append one event to ceo-ledger.jsonl")
    p.add_argument("json", nargs="?", help="JSON event string")
    p.add_argument("--file", help="Path to JSON file containing one event object")
    args = p.parse_args()
    event = load_event(args)
    append_event(event)


if __name__ == "__main__":
    main()