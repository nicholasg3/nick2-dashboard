#!/usr/bin/env python3
"""Build reports/org-fleet.json — Nick2 org tree with live/asleep status for the dashboard."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
OUT = ROOT / "reports" / "org-fleet.json"
ORCH_STATUS = ROOT / "reports" / "orchestrator" / "status.json"

# Curated dashboard tree (matches org.json maps_to + droplet services)
SERVICE_SCHEDULES = {
    "ceo-office": {"schedule": "24/7 via dashboard bridge", "label": "CEO role office"},
    "coo-office": {"schedule": "24/7 via dashboard bridge", "label": "COO role office"},
    "pmo": {"schedule": "24/7 via dashboard bridge + agent-bus", "label": "PMO role office"},
    "telegram-bridge": {"schedule": "24/7 systemd", "label": "Hermes (telegram-bridge)"},
    "skill-radar": {"schedule": "~06:02 SGT daily", "label": "skill-radar"},
    "sp-trend-scout": {"schedule": "~05:32 SGT daily", "label": "sp-trend-scout"},
    "frontier-orchestrator": {"schedule": "~07:30 SGT daily", "label": "frontier-orchestrator"},
    "pa-self-improve": {"schedule": "~06:34 SGT daily", "label": "pa-self-improve"},
    "notion-bridge": {"schedule": "on demand", "label": "notion-bridge"},
    "droplet-infra": {"schedule": "systemd + CCR", "label": "droplet-infra"},
    "trust-ledger": {"schedule": "ledger-derived", "label": "trust-ledger"},
}

ASLEEP_ROLES = [
    "Strategy Office", "CFO", "Token Accountant", "Editorial Director", "CMO",
    "CPO", "CISO", "CDO", "Creative Director", "Corporate Development",
    "Think Tank", "Internal Audit", "Automation", "DevOps", "Testing",
    "Notion Librarian", "Citation Manager", "Academic Research",
    "Industry Intelligence", "Fact Checking", "First-Draft Writer",
    "Copy Editor", "Final Publisher", "Newsletter", "Evaluation",
]


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sorted(out, key=lambda e: e.get("ts", ""))


def ledger_context(events: list[dict]) -> dict:
    resolved = {
        ev.get("task_id")
        for ev in events
        if ev.get("event") in ("decision_resolved", "nick_gate_resolved", "nick_decision")
        and ev.get("task_id")
    }
    gates = []
    tasks = {}
    focus = {}
    worker_enabled = False
    budget = {}

    for ev in events:
        tid = ev.get("task_id") or ""
        et = ev.get("event") or ""
        if et == "decision_needed" and ev.get("needs_nicholas") and tid not in resolved:
            gates.append({"task_id": tid, "task": ev.get("task"), "priority": ev.get("priority")})
        if tid:
            tasks[tid] = {**tasks.get(tid, {}), **ev}
        if et == "focus_snapshot":
            focus = {
                "task_id": ev.get("focus_task_id") or tid,
                "task": ev.get("task"),
                "status": ev.get("status"),
                "owner": ev.get("owner"),
            }
        if et == "worker_status" and ev.get("status") == "completed":
            if "enabled=true" in (ev.get("output") or "").lower():
                worker_enabled = True
        if et == "nick_decision" and "worker" in (ev.get("decision") or "").lower():
            worker_enabled = True
        if ev.get("weekly_budget_usd") is not None:
            budget["weekly_usd"] = ev.get("weekly_budget_usd")
        if ev.get("budget_remaining_usd") is not None:
            budget["remaining_usd"] = ev.get("budget_remaining_usd")
        if ev.get("budget_mode"):
            budget["mode"] = ev.get("budget_mode")

    pmo = tasks.get("PMO-001") or {}
    dispatch_active = any(
        (t.get("status") or "") in ("queued", "in_progress")
        for tid, t in tasks.items()
        if tid.startswith("ISSUE-") or tid == "DISPATCH-001"
    )
    return {
        "gates": gates,
        "focus": focus,
        "pmo_status": pmo.get("status"),
        "pmo_task": pmo.get("task"),
        "dispatch_active": dispatch_active,
        "worker_enabled": worker_enabled,
        "budget": budget,
        "open_gate_count": len(gates),
    }


def _parse_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def orchestrator_context() -> dict:
    if not ORCH_STATUS.is_file():
        return {"running": False, "detail": "CEO orchestrator service not witnessed yet"}
    try:
        data = json.loads(ORCH_STATUS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"running": False, "detail": "CEO orchestrator status unreadable"}
    last = _parse_utc(data.get("last_tick_at") or data.get("ts"))
    age_min = None
    fresh = False
    if last:
        age_min = (datetime.now(timezone.utc) - last).total_seconds() / 60.0
        fresh = age_min <= 10
    summary = data.get("summary") or data.get("reason") or "No summary"
    return {
        "running": fresh and data.get("mode") == "live",
        "fresh": fresh,
        "age_min": round(age_min, 1) if age_min is not None else None,
        "healthy": data.get("healthy"),
        "mode": data.get("mode"),
        "summary": summary,
    }


def _node(
    node_id: str,
    title: str,
    *,
    status: str,
    icon: str,
    maps_to: str = "",
    detail: str = "",
    schedule: str = "",
    chat_role: str = "",
    children: list | None = None,
) -> dict:
    return {
        "id": node_id,
        "title": title,
        "status": status,
        "icon": icon,
        "maps_to": maps_to,
        "detail": detail,
        "schedule": schedule,
        "chat_role": chat_role,
        "children": children or [],
    }


def build_tree(ctx: dict) -> dict:
    pmo_active = ctx.get("pmo_status") in ("in_progress", "queued") or ctx.get(
        "dispatch_active"
    )
    worker_on = ctx.get("worker_enabled")
    gates = ctx.get("gates") or []
    focus = ctx.get("focus") or {}
    budget = ctx.get("budget") or {}
    orch = ctx.get("orchestrator") or {}

    frontier_detail = "Daily cycle + /nick2 run on demand"
    if pmo_active:
        frontier_detail = "PMO-001 %s — worker %s" % (
            ctx.get("pmo_status"),
            "on" if worker_on else "off",
        )
    if gates:
        frontier_detail += " · %d Nick gate(s)" % len(gates)

    coo_status = "active" if pmo_active else "timer"
    coo_icon = "🟡" if pmo_active else "⏰"

    ceo_detail = focus.get("task") or "Portfolio idle — timer armed"
    if focus.get("task_id"):
        ceo_detail = "%s (%s)" % (focus.get("task_id"), focus.get("status") or "—")

    ceo_status = "live" if orch.get("running") else "timer"
    ceo_icon = "🟢" if orch.get("running") else "⏰"
    orch_detail = "Talkable executive supervisor via the live dashboard bridge."
    if orch.get("summary"):
        age = "fresh" if orch.get("age_min") is None else f"{orch['age_min']}m ago"
        orch_detail = f"{orch.get('summary')} ({age})"

    children = [
        _node(
            "ceo_office",
            "CEO Office",
            status=ceo_status,
            icon=ceo_icon,
            maps_to=SERVICE_SCHEDULES["ceo-office"]["label"],
            detail=orch_detail,
            schedule=SERVICE_SCHEDULES["ceo-office"]["schedule"],
            chat_role="ceo",
        ),
        _node(
            "coo_office",
            "COO Office",
            status="live",
            icon="🟢",
            maps_to=SERVICE_SCHEDULES["coo-office"]["label"],
            detail="Talkable operations role for services, stuck work, and handoffs.",
            schedule=SERVICE_SCHEDULES["coo-office"]["schedule"],
            chat_role="coo",
        ),
        _node(
            "pmo_office",
            "PMO Office",
            status="live",
            icon="🟢",
            maps_to=SERVICE_SCHEDULES["pmo"]["label"],
            detail=frontier_detail + " · talkable PMO role; dispatch still runs through agent-bus when needed.",
            schedule=SERVICE_SCHEDULES["pmo"]["schedule"],
            chat_role="pmo",
        ),
        _node(
            "chief_of_staff",
            "Chief of Staff",
            status="live",
            icon="🟢",
            maps_to=SERVICE_SCHEDULES["telegram-bridge"]["label"],
            detail="Router only (Gemini Flash Lite) — NOT PMO; wakes PMO for assessments",
            schedule=SERVICE_SCHEDULES["telegram-bridge"]["schedule"],
        ),
        _node(
            "caio",
            "CAIO",
            status="timer",
            icon="⏰",
            maps_to=SERVICE_SCHEDULES["skill-radar"]["label"],
            detail="Skill crawl + digest",
            schedule=SERVICE_SCHEDULES["skill-radar"]["schedule"],
        ),
        _node(
            "cro",
            "CRO",
            status="timer",
            icon="⏰",
            maps_to=SERVICE_SCHEDULES["sp-trend-scout"]["label"],
            detail="Trend scout signals",
            schedule=SERVICE_SCHEDULES["sp-trend-scout"]["schedule"],
        ),
        _node(
            "cio",
            "CIO",
            status="asleep",
            icon="💤",
            maps_to=SERVICE_SCHEDULES["notion-bridge"]["label"],
            detail="Not running — notion-bridge on demand",
            schedule=SERVICE_SCHEDULES["notion-bridge"]["schedule"],
        ),
        _node(
            "cto",
            "CTO",
            status="implicit",
            icon="⚙️",
            maps_to=SERVICE_SCHEDULES["droplet-infra"]["label"],
            detail="systemd services, CCR :3456, GitHub Actions",
            schedule=SERVICE_SCHEDULES["droplet-infra"]["schedule"],
        ),
        _node(
            "chro",
            "CHRO",
            status="passive",
            icon="📋",
            maps_to=SERVICE_SCHEDULES["trust-ledger"]["label"],
            detail="Trust scores from ledger events",
            schedule=SERVICE_SCHEDULES["trust-ledger"]["schedule"],
        ),
        _node(
            "asleep_bucket",
            "Strategy · CFO · Editorial · CMO · …",
            status="asleep",
            icon="💤",
            maps_to="",
            detail="%d roles asleep until CEO admits + budget" % len(ASLEEP_ROLES),
            schedule="budget-gated",
            children=[
                _node(
                    "asleep_%d" % i,
                    name,
                    status="asleep",
                    icon="·",
                    detail="Awaiting portfolio admission",
                )
                for i, name in enumerate(ASLEEP_ROLES[:8])
            ]
            + (
                [_node("asleep_more", "… +%d more" % (len(ASLEEP_ROLES) - 8), status="asleep", icon="·", detail="")]
                if len(ASLEEP_ROLES) > 8
                else []
            ),
        ),
    ]

    budget_note = ""
    if budget.get("weekly_usd"):
        budget_note = " · $%s/wk cap ($%s left)" % (
            budget.get("weekly_usd"),
            budget.get("remaining_usd", "?"),
        )

    return _node(
        "ceo",
        "CEO (Nick2)",
        status="active" if pmo_active else "idle",
        icon="🟡" if pmo_active else "◆",
        maps_to="frontier-orchestrator",
        detail=(ceo_detail + budget_note).strip(),
        children=children,
    )


def main() -> None:
    events = load_events()
    ctx = ledger_context(events)
    ctx = {**ctx, "orchestrator": orchestrator_context()}
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "legend": {
            "live": "🟢 Running now (24/7 service)",
            "timer": "⏰ Scheduled — fires on systemd timer",
            "active": "🟡 Work in flight (ledger)",
            "implicit": "⚙️ Infrastructure always on",
            "passive": "📋 Data-only / ledger-derived",
            "asleep": "💤 Budget-gated — not spawned",
            "idle": "◆ No active portfolio dispatch",
        },
        "context": ctx,
        "root": build_tree(ctx),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("Exported org-fleet.json (%d gates, PMO=%s)" % (
        ctx.get("open_gate_count", 0),
        ctx.get("pmo_status") or "—",
    ))


if __name__ == "__main__":
    main()
