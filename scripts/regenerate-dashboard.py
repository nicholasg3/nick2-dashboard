#!/usr/bin/env python3
"""Regenerate DASHBOARD.md and reports/weekly-review.md from logs/ceo-ledger.jsonl."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
DASHBOARD_MD = ROOT / "DASHBOARD.md"
WEEKLY_MD = ROOT / "reports" / "weekly-review.md"


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    events = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return sorted(events, key=lambda e: e.get("ts", ""))


def latest_val(events: list[dict], key: str, default=None):
    for ev in reversed(events):
        if key in ev and ev[key] is not None:
            return ev[key]
    return default


def build_tasks(events: list[dict]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for ev in events:
        tid = ev.get("task_id")
        if tid:
            tasks[tid] = {**tasks.get(tid, {}), **ev}
    return tasks


def fmt_usd(n) -> str:
    if n is None:
        return "—"
    return f"${float(n):.2f}"


def render_dashboard(events: list[dict]) -> str:
    tasks = build_tasks(events)
    weekly = latest_val(events, "weekly_budget_usd", 0)
    spent = latest_val(events, "cumulative_weekly_spend_usd", 0)
    mode = latest_val(events, "budget_mode", "unknown")
    model = latest_val(events, "model")
    decisions = [e for e in events if e.get("needs_nicholas") or e.get("event") == "decision_needed"]
    completed = [t for t in tasks.values() if t.get("status") == "completed" or t.get("event") == "task_completed"]
    active = [t for t in tasks.values() if t.get("status") in {"queued", "in_progress", "blocked", "awaiting_nicholas", "approved"}]
    roadmap = [e for e in events if e.get("event") == "roadmap_item"]
    trust_ev = next((e for e in reversed(events) if e.get("trust")), None)
    trust = trust_ev.get("trust", {}) if trust_ev else {}
    artifacts = sorted({a for e in events for a in (e.get("artifacts") or []) if a})
    now = datetime.now().strftime("%Y-%m-%d %H:%M SGT")

    lines = [
        "# Nick2 Operating Dashboard",
        "",
        f"_Regenerated {now} from `logs/ceo-ledger.jsonl`. Do not edit manually — run `python3 scripts/regenerate-dashboard.py`._",
        "",
        "## Executive Snapshot",
        "",
        f"| Budget (week) | Spend | Mode | Model |",
        f"|---|---:|---|---|",
        f"| {fmt_usd(weekly) if weekly else 'OFF'} | {fmt_usd(spent)} | {mode} | {model or '—'} |",
        "",
        "## Active Work Queue",
        "",
        "| Status | Owner | Task | ID |",
        "|---|---|---|---|",
    ]
    for t in active:
        lines.append(f"| {t.get('status','—')} | {t.get('owner') or t.get('actor','—')} | {t.get('task','—')} | {t.get('task_id','—')} |")
    if not active:
        lines.append("| — | — | _empty_ | — |")

    lines += ["", "## Completed Work", "", "| Time | Owner | Task | Cost |", "|---|---|---|---:|"]
    for t in completed:
        lines.append(f"| {t.get('ts','—')[:16]} | {t.get('actor','—')} | {t.get('task','—')} | {fmt_usd(t.get('cost_usd', 0))} |")
    if not completed:
        lines.append("| — | — | _empty_ | — |")

    lines += ["", "## Decisions Needed From Nicholas", ""]
    for d in decisions:
        lines.append(f"- **[{d.get('priority','medium').upper()}]** {d.get('task','—')}: {d.get('output','')}")
    if not decisions:
        lines.append("_None pending._")

    lines += ["", "## Agent Trust Ledger", "", "| Agent | Runs | Successes | Failures | Autonomy |", "|---|---:|---:|---:|---|"]
    for agent, rec in sorted(trust.items()):
        lines.append(
            f"| {agent} | {rec.get('runs',0)} | {rec.get('successes',0)} | {rec.get('failures',0)} | {rec.get('autonomy','—')} |"
        )
    if not trust:
        lines.append("| — | 0 | 0 | 0 | — |")

    lines += ["", "## Strategic Roadmap", ""]
    for r in sorted(roadmap, key=lambda x: x.get("priority", 99)):
        lines.append(f"- **{r.get('roadmap_lane','near_term')}**: {r.get('task','—')}")
    if not roadmap:
        lines.append("_Empty._")

    lines += ["", "## Artifacts Produced", ""]
    for a in artifacts:
        lines.append(f"- `{a}`")
    if not artifacts:
        lines.append("_None yet._")

    return "\n".join(lines) + "\n"


def render_weekly(events: list[dict]) -> str:
    spent = latest_val(events, "cumulative_weekly_spend_usd", 0)
    weekly = latest_val(events, "weekly_budget_usd", 0)
    tasks = build_tasks(events)
    completed = [t for t in tasks.values() if t.get("status") == "completed"]
    decisions = [e for e in events if e.get("needs_nicholas")]
    spend_by_model: dict[str, float] = defaultdict(float)
    for e in events:
        if e.get("cost_usd"):
            spend_by_model[e.get("model") or "unknown"] += float(e["cost_usd"])
    trust_ev = next((e for e in reversed(events) if e.get("trust")), None)
    trust = trust_ev.get("trust", {}) if trust_ev else {}

    lines = [
        "# Nick2 Weekly Review",
        "",
        "_Auto-generated from ceo-ledger.jsonl_",
        "",
        "## Summary",
        "",
        f"- Weekly budget: {fmt_usd(weekly) if weekly else 'OFF'}",
        f"- Cumulative spend: {fmt_usd(spent)}",
        f"- Tasks completed: {len(completed)}",
        f"- Decisions awaiting Nicholas: {len(decisions)}",
        "",
        "## Spend by Model",
        "",
    ]
    if spend_by_model:
        for m, v in sorted(spend_by_model.items(), key=lambda x: -x[1]):
            lines.append(f"- {m}: {fmt_usd(v)}")
    else:
        lines.append("_No spend recorded._")

    lines += ["", "## Trust Ledger", ""]
    for agent, rec in sorted(trust.items()):
        lines.append(f"- **{agent}**: {rec.get('runs',0)} runs, autonomy={rec.get('autonomy','—')}")

    return "\n".join(lines) + "\n"


def main() -> None:
    events = load_events()
    DASHBOARD_MD.write_text(render_dashboard(events), encoding="utf-8")
    WEEKLY_MD.write_text(render_weekly(events), encoding="utf-8")
    print(f"Wrote {DASHBOARD_MD}")
    print(f"Wrote {WEEKLY_MD}")


if __name__ == "__main__":
    main()