"""Execution Brief memos for active missions (WIP).

Complements MKA Decision Memos (gated items). Answers: how is the mission progressing?
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SGT = timezone(timedelta(hours=8))
SEP = "────────────────────────────────────────────"
DASHBOARD = "https://nicholasg3.github.io/nick2-dashboard/"

# Rich execution state keyed by task_id. Agents update via ledger + regenerate-memos.
EXECUTION_BRIEFS: dict[str, dict[str, Any]] = {
    "PMO-001": {
        "mission_name": "Triage Ready-for-Agent GitHub Issues",
        "objective": (
            "Produce a ranked execution order for 13 ready-for-agent GitHub issues "
            "and dispatch the highest-value work within the $20/week operating budget."
        ),
        "success_criteria": [
            ("done", "All issues inventoried"),
            ("open", "Dependencies identified"),
            ("open", "Ranked backlog produced"),
            ("open", "Top issues dispatched"),
            ("open", "Dashboard updated"),
        ],
        "phases": [
            {
                "name": "Understand the Work",
                "progress": 35,
                "activities": [
                    "Inventory all 13 ready-for-agent issues",
                    "Classify by capability / tier",
                    "Estimate effort and risk",
                ],
            },
            {
                "name": "Prioritize",
                "progress": 15,
                "activities": [
                    "Score ROI (interim rubric until DEC-002)",
                    "Identify dependencies",
                    "Produce ranked backlog",
                ],
            },
            {
                "name": "Execute",
                "progress": 10,
                "activities": [
                    "Dispatch frontier workers",
                    "Monitor budget ($20/wk cap)",
                    "Verify outputs / witnesses",
                ],
            },
            {
                "name": "Report & Learn",
                "progress": 5,
                "activities": [
                    "Update nick2-dashboard ledger",
                    "Refresh execution brief",
                    "Capture lessons for postmortem",
                ],
            },
        ],
        "overall_progress": 18,
        "critical_path": [
            "Issue inventory",
            "Dependency analysis",
            "Priority ranking",
            "Agent dispatch",
            "Verification",
            "Dashboard update",
        ],
        "workstreams": [
            ("Issue analysis", 40),
            ("Dependency mapping", 15),
            ("Agent dispatch", 5),
            ("Verification", 0),
        ],
        "blockers": [
            "DEC-002 scoring framework not yet finalized — using interim rubric",
        ],
        "milestones": [
            ("17:30", "Complete issue inventory"),
            ("18:00", "Publish ranked backlog (top 5)"),
            ("18:15", "Push dashboard ledger update"),
        ],
        "waiting_on": [
            "DEC-002 — Approve PMO scoring framework (calibration, not dispatch block)",
        ],
        "links": [
            ("Dashboard", DASHBOARD),
            ("GitHub Issues", "https://github.com/nicholasg3/ai-agents-workspace/issues"),
            ("CEO Ledger", "ledger.html"),
            ("lane.json", "Projects-for-agents/frontier-orchestrator/lane.json"),
        ],
    },
    "P-001": {
        "mission_name": "PMO Triage Proposal (Tier B)",
        "objective": "Seed PMO-001 with highest-ROI analysis entry point for 13 ready-for-agent issues.",
        "success_criteria": [
            ("done", "Proposal approved (Tier B, score 0.6)"),
            ("open", "Analysis output linked to PMO-001"),
            ("open", "Ranked recommendation delivered"),
        ],
        "phases": [
            {
                "name": "Scope",
                "progress": 100,
                "activities": ["Pure analysis — no external writes", "Feeds PMO-001"],
            },
            {
                "name": "Analyze",
                "progress": 30,
                "activities": ["Review issue board", "Draft rank inputs"],
            },
            {
                "name": "Handoff",
                "progress": 0,
                "activities": ["Merge into PMO-001 backlog", "Close P-001"],
            },
        ],
        "overall_progress": 45,
        "critical_path": ["Approved scope", "Analysis", "Handoff to PMO-001"],
        "workstreams": [("Analysis", 45), ("Handoff", 0)],
        "blockers": [],
        "milestones": [("—", "Complete analysis handoff to PMO-001")],
        "waiting_on": [],
        "links": [
            ("Dashboard", DASHBOARD),
            ("PMO-001 brief", "queue/PMO-001.html"),
        ],
    },
}


def _date_stamp(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(SGT)
    return f"[{dt.strftime('%a %b')} {dt.day}, {dt.year}]"


def _bar(pct: int, width: int = 10) -> str:
    pct = max(0, min(100, int(pct)))
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _status_emoji(status: str) -> str:
    s = (status or "").lower()
    if s == "in_progress":
        return "🟢 Executing"
    if s in {"blocked", "failed"}:
        return "🔴 Blocked"
    if s in {"queued", "approved"}:
        return "🟡 At Risk"
    return "🟡 At Risk"


def _criteria_line(state: str, text: str) -> str:
    mark = "☑" if state == "done" else "☐"
    return f"{mark} {text}"


def _brief(tid: str, t: dict) -> dict[str, Any]:
    b = dict(EXECUTION_BRIEFS.get(tid, {}))
    if "mission_name" not in b:
        b["mission_name"] = t.get("task", tid)
    if "objective" not in b:
        b["objective"] = t.get("output") or f"Execute mission {tid}."
    b.setdefault("success_criteria", [("open", "Mission completed per ledger")])
    b.setdefault("phases", [
        {
            "name": "Execute",
            "progress": 10 if t.get("status") == "in_progress" else 0,
            "activities": [t.get("output") or "See ledger for current step."],
        },
    ])
    b.setdefault("overall_progress", 15 if t.get("status") == "in_progress" else 5)
    b.setdefault("critical_path", ["Start", "Execute", "Verify", "Report"])
    b.setdefault("workstreams", [("Primary workstream", b["overall_progress"])])
    b.setdefault("blockers", [])
    if t.get("status") == "blocked" and t.get("output"):
        b.setdefault("blockers", []).append(t.get("output"))
    b.setdefault("milestones", [])
    b.setdefault("waiting_on", [])
    b.setdefault("links", [
        ("Dashboard", DASHBOARD),
        ("CEO Ledger", "ledger.html"),
    ])
    return b


def _task_events(events: list[dict], tid: str, limit: int = 6) -> list[dict]:
    matched = [e for e in events if e.get("task_id") == tid]
    return list(reversed(matched))[:limit]


def _fmt_event_time(ts: str) -> str:
    if not ts:
        return "—"
    try:
        if "T" in ts:
            return ts.split("T")[1][:5]
        return ts[:5]
    except Exception:
        return ts[:16]


def execution_brief_body(
    tid: str,
    t: dict,
    *,
    events: list[dict],
    weekly: float,
    spend: float,
    remaining: float | None,
    memo_context: str = "queue",
) -> str:
    brief = _brief(tid, t)
    owner = t.get("owner") or t.get("actor", "—")
    status = _status_emoji(t.get("status", ""))
    updated = (t.get("ts") or "")[:16].replace("T", " ")
    overall = brief["overall_progress"]

    criteria = "\n".join(
        _criteria_line(state, text) for state, text in brief["success_criteria"]
    )

    phases = []
    for i, ph in enumerate(brief["phases"], 1):
        pct = ph.get("progress", 0)
        acts = "\n".join(f"• {a}" for a in ph.get("activities", []))
        phases.append(
            f"{i}. {ph['name']}\n"
            f"Progress: {_bar(pct)}\n\n"
            f"{acts}"
        )
    phases_block = "\n\n".join(phases)

    path = "\n      ↓\n".join(brief["critical_path"])

    workstreams = "\n\n".join(
        f"{_bar(pct)}\n{label}"
        for label, pct in brief["workstreams"]
    )

    blockers = "\n".join(f"• {b}" for b in brief["blockers"]) or "• _None._"
    waiting = "\n".join(f"• {w}" for w in brief["waiting_on"]) or "• _None._"

    milestones = "\n\n".join(
        f"{time}\n{milestone}" for time, milestone in brief["milestones"]
    ) or "—\n_TBD_"

    recent = _task_events(events, tid)
    if not recent:
        recent = [t]
    recent_lines = "\n\n".join(
        f"{_fmt_event_time(e.get('ts', ''))}\n{e.get('event', '—')}: {(e.get('output') or '')[:80]}"
        for e in recent[:5]
    )

    rem = remaining if remaining is not None else max(0.0, weekly - spend)
    budget_block = (
        f"Spent: ${spend:.2f}\n"
        f"Remaining: ${rem:.2f}\n"
        f"Limit: ${weekly:.2f}/week" if weekly > 0 else "Spent: $0.00\nRemaining: —\nLimit: OFF"
    )

    def resolve_href(href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("queue/"):
            return href.replace("queue/", queue_peer) if memo_ctx == "current" else href.split("/")[-1]
        root_pages = {"ledger.html", "gated-queue.html", "current.html", "policy.html"}
        if href in root_pages:
            return f"../{href}" if memo_ctx == "queue" else href
        return href

    queue_peer = ""
    memo_ctx = memo_context
    links = "\n".join(
        f"- [{label}]({resolve_href(href)})"
        if href.startswith("http") or href.endswith(".html") or href.startswith("queue/")
        else f"- `{href}`"
        for label, href in brief["links"]
    )
    links += f"\n- Ledger: `logs/ceo-ledger.jsonl` (`{tid}`)"

    return f"""{_date_stamp()}

# {tid}: {brief['mission_name']}

**Owner:** {owner}  
**Status:** {status}  
**Last Updated:** {updated}

{SEP}

## MISSION

### Objective

{brief['objective']}

### Success Criteria

{criteria}

### Mission Decomposition (MECE)

{phases_block}

{SEP}

## EXECUTION STATUS

### Overall Progress

{_bar(overall)} {overall}%

### Budget

{budget_block}

### Critical Path

{path}

{SEP}

## CURRENT WORKSTREAMS

{workstreams}

{SEP}

## BLOCKERS

{blockers}

{SEP}

## NEXT MILESTONES

{milestones}

{SEP}

## WAITING ON

{waiting}

{SEP}

## RECENT EVENTS

{recent_lines}

{SEP}

## LINKS

{links}
"""