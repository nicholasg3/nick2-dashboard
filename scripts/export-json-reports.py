#!/usr/bin/env python3
"""Derive reports/*.json snapshots from logs/ceo-ledger.jsonl (read-only)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
REPORTS = ROOT / "reports"


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return sorted(out, key=lambda e: e.get("ts", ""))


def latest(events: list[dict], key: str, default=None):
    for ev in reversed(events):
        if key in ev and ev[key] is not None:
            return ev[key]
    return default


def main() -> None:
    events = load_events()
    REPORTS.mkdir(parents=True, exist_ok=True)

    trust = {}
    for ev in events:
        if ev.get("trust"):
            trust.update(ev["trust"])

    roadmap = [
        {
            "task_id": e.get("task_id"),
            "lane": e.get("roadmap_lane", "near_term"),
            "task": e.get("task"),
            "status": e.get("status"),
            "priority": e.get("priority"),
        }
        for e in events
        if e.get("event") == "roadmap_item"
    ]

    spend_by_model: dict[str, float] = defaultdict(float)
    spend_by_actor: dict[str, float] = defaultdict(float)
    transactions = []
    for ev in events:
        cost = float(ev.get("cost_usd") or 0)
        if cost > 0:
            m = ev.get("model") or "unknown"
            spend_by_model[m] += cost
            spend_by_actor[ev.get("actor") or "unknown"] += cost
            transactions.append(
                {
                    "ts": ev.get("ts"),
                    "actor": ev.get("actor"),
                    "model": m,
                    "cost_usd": cost,
                    "cumulative_weekly_spend_usd": ev.get("cumulative_weekly_spend_usd"),
                    "task": ev.get("task"),
                }
            )

    costs = {
        "weekly_budget_usd": latest(events, "weekly_budget_usd", 0),
        "budget_mode": latest(events, "budget_mode", "unknown"),
        "cumulative_weekly_spend_usd": latest(events, "cumulative_weekly_spend_usd", 0),
        "spend_by_model": dict(spend_by_model),
        "spend_by_actor": dict(spend_by_actor),
        "transactions": transactions,
    }

    (REPORTS / "trust.json").write_text(json.dumps(trust, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "roadmap.json").write_text(json.dumps(roadmap, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "costs.json").write_text(json.dumps(costs, indent=2) + "\n", encoding="utf-8")
    print("Exported trust.json, roadmap.json, costs.json")


if __name__ == "__main__":
    main()