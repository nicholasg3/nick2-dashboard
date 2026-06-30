"""Execution Brief memos for active missions (WIP).

Complements MKA Decision Memos (gated items). Answers: how is the mission progressing?
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SGT = timezone(timedelta(hours=8))
SEP = "────────────────────────────────────────────"
DASHBOARD = "https://nicholasg3.github.io/nick2-dashboard/"
WIP_MEMO_MAX_AGE_MIN = 30

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
            "nick2-dashboard repo lock — JOB-453 still running (gate work already on main)",
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
    "LIT-001": {
        "mission_name": "Autonomous literature research for memory architecture paper",
        "objective": (
            "Bounded OA/arxiv/IS search + snowball for the 2026-07-12 agent memory architecture paper. "
            "After cycle 1, only narrow writing passes or targeted IS-platform search — not broad trawls."
        ),
        "success_criteria": [
            ("done", "Cycle 1 complete — 9 new papers ingested"),
            ("done", "theme_06 operational memory governance synthesis memo"),
            ("open", "Fold synthesis into paper Section 6 / construct table"),
            ("open", "Optional targeted IS-platform portability/governance search"),
        ],
        "phases": [
            {
                "name": "Broad discovery (cycle 1)",
                "progress": 100,
                "activities": [
                    "9 new papers; snowball + OA search",
                    "Declared low-yield for further broad search",
                ],
            },
            {
                "name": "Bounded follow-up",
                "progress": 100,
                "activities": [
                    "theme_06_operational_memory_governance.md written",
                    "Recommendation: narrow writing pass or sleep",
                ],
            },
            {
                "name": "Writing / targeted search",
                "progress": 0,
                "activities": [
                    "Awaiting CRO re-arm — agent is idle/slept since 09:26 UTC",
                ],
            },
        ],
        "overall_progress": 40,
        "critical_path": [
            "Cycle 1 search",
            "Governance synthesis memo",
            "Writing pass OR targeted IS search",
            "Ledger + brief update",
        ],
        "workstreams": [
            ("Literature ingestion", 100),
            ("Synthesis memos", 100),
            ("Paper integration", 0),
        ],
        "blockers": [
            "Autonomous sub-agent slept after cycle 1 — not running on droplet",
            "Broad literature search explicitly marked low-yield",
        ],
        "milestones": [
            ("09:26 UTC", "Cycle 1 + theme_06 complete; agent recommended sleep"),
            ("—", "Re-arm: narrow writing pass or close as idle-complete"),
        ],
        "waiting_on": [
            "CRO/CEO — confirm narrow writing pass vs retire LIT-001",
        ],
        "links": [
            ("Dashboard", DASHBOARD),
            ("autonomous_update.md", "Projects-for-agents/strategic-publishing/grounded/2026-07-12-agents-need-memory-architecture-not-just-prompt/literature/autonomous_update.md"),
            ("theme_06 memo", "Projects-for-agents/strategic-publishing/grounded/2026-07-12-agents-need-memory-architecture-not-just-prompt/literature/round-gt-theory/theme_06_operational_memory_governance.md"),
        ],
    },
    "SYS-002": {
        "title": "Make the dashboard live",
        "situation": (
            "The operating dashboard still reads ledger and agent-bus state from GitHub Pages "
            "snapshots that can lag minutes behind reality. POL-002 needs server-side stale "
            "detection so workers cannot sit at Executing while asleep."
        ),
        "mece": [
            ("Live read path", "Add droplet API for ledger tail + bus SQLite — in flight via JOB-924"),
            ("Honest reconcile", "Auto-flag or transition tasks with no heartbeat in 30+ minutes"),
            ("Publish cadence", "15-minute cron to reconcile, regenerate memos, and push"),
            ("Client wiring", "dashboard app polls live API when configured, static JSON fallback"),
        ],
        "paths_considered": [
            "Full React/Node rewrite on GitHub Pages",
            "Extend existing Python gate server with /api/live/* + vanilla JS polling",
            "Static-only: shorter cron and hope agents heartbeats",
        ],
        "chosen_path_why": (
            "We chose extending the gate server and vanilla JS because it fixes latency and "
            "honesty without a framework migration. React would improve DX but would not stop "
            "agents from going quiet without the reconcile layer; static-only leaves the "
            "phone and dashboard blind during the export gap. The gate server already runs on "
            "the droplet beside the ledger — adding live endpoints is the cheapest path that "
            "unifies memo and panel reads."
        ),
        "where_it_stands": (
            "JOB-924 is executing on the droplet (requeued after one harness crash). "
            "Live ledger/bus API endpoints, POL-002 reconcile, and 15-minute sync cron are "
            "in progress on branch job/20260630-924. Activity feed reads ledger live; memos now "
            "load via memo.html so they track regenerate-memos output. JOB-102 will McKinsey-format "
            "PMO-001 and remaining queue items after 924 lands. No Nick gate."
        ),
        "effort": {
            "time": "In focus ~2h; ~45m blocked on repo-lock zombies + ~15m harness retry",
            "work": "JOB-924 dispatch 2 (1 blocked retry), JOB-102 held, JOB-438 notify rewrite parallel",
            "budget": "spent $0.00 · remaining $20.00 · limit $20/week",
        },
        "links": [
            ("Dashboard", DASHBOARD),
            ("CEO Ledger", "ledger.html"),
        ],
    },
}


def _is_mckinsey_brief(brief: dict[str, Any]) -> bool:
    return bool(brief.get("situation") and brief.get("mece"))


def ceo_focus_line(tid: str, t: dict, brief: dict[str, Any] | None = None) -> str:
    """One plain sentence for CEO Focus — never truncated mid-word."""
    brief = brief or EXECUTION_BRIEFS.get(tid, {})
    if _is_mckinsey_brief(brief):
        status = (t.get("status") or "queued").replace("_", " ")
        title = brief.get("title") or tid
        if status == "in progress":
            return f"{title} — executing on droplet (JOB-924), live API + reconcile path"
        if status == "queued":
            return f"{title} — queued on droplet, waiting for worker slot"
        return f"{title} — {status}"
    task = (t.get("task") or brief.get("mission_name") or tid).strip()
    if len(task) <= 72:
        return task
    cut = task[:72].rsplit(" ", 1)[0]
    return cut + "…"


def mckinsey_brief_body(
    tid: str,
    t: dict,
    brief: dict[str, Any],
    *,
    memo_context: str = "queue",
) -> str:
    title = brief.get("title") or t.get("task") or tid
    updated = (t.get("ts") or "")[:16].replace("T", " ")
    stale = _wip_stale(t)
    stale_note = ""
    if stale:
        age = _wip_age_minutes(t)
        mins = int(age) if age is not None else WIP_MEMO_MAX_AGE_MIN
        stale_note = (
            f"\n\n> POL-002: last ledger touch **{mins}m** ago — heartbeat or status transition due.\n"
        )

    mece = "\n".join(f"- **{branch}** — {state}" for branch, state in brief.get("mece", []))
    paths = "\n".join(f"- {p}" for p in brief.get("paths_considered", []))
    effort = brief.get("effort", {})
    effort_block = (
        f"- **Time:** {effort.get('time', '—')}\n"
        f"- **Work:** {effort.get('work', '—')}\n"
        f"- **Budget:** {effort.get('budget', '—')}"
    )

    back = "../index.html"
    links = "\n".join(
        f"- [{label}]({href})" for label, href in brief.get("links", [("Dashboard", DASHBOARD)])
    )

    return f"""{_date_stamp()}

[← Dashboard]({back})

**{tid}: {title}**

## SITUATION

{brief.get('situation', '')}

## MECE DECOMPOSITION

{mece}

## PATHS CONSIDERED

{paths}

## CHOSEN PATH + WHY

{brief.get('chosen_path_why', '')}

## WHERE IT STANDS

{brief.get('where_it_stands', '')}{stale_note}

## EFFORT & COST

{effort_block}

## LINKS

{links}

_Last updated {updated} SGT_
"""


def _date_stamp(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(SGT)
    return f"[{dt.strftime('%a %b')} {dt.day}, {dt.year}]"


def _bar(pct: int, width: int = 10) -> str:
    pct = max(0, min(100, int(pct)))
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        raw = ts.replace("Z", "+00:00")
        if raw.endswith("+08:00"):
            return datetime.fromisoformat(raw)
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _wip_age_minutes(t: dict) -> float | None:
    dt = _parse_ts(t.get("ts") or "")
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SGT)
    return (datetime.now(SGT) - dt.astimezone(SGT)).total_seconds() / 60.0


def _wip_stale(t: dict) -> bool:
    if (t.get("status") or "").lower() not in {"in_progress", "queued", "approved", "blocked"}:
        return False
    age = _wip_age_minutes(t)
    return age is not None and age > WIP_MEMO_MAX_AGE_MIN


def _status_emoji(status: str, *, stale: bool = False) -> str:
    s = (status or "").lower()
    if stale:
        return f"🟠 Stale — no update in {WIP_MEMO_MAX_AGE_MIN}+ min (POL-002)"
    if s == "idle":
        return "💤 Idle"
    if s == "in_progress":
        return "🟢 Executing"
    if s in {"blocked", "failed"}:
        return "🔴 Blocked"
    if s in {"queued", "approved"}:
        return "🟡 At Risk"
    if s == "completed":
        return "✅ Complete"
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
    raw = EXECUTION_BRIEFS.get(tid, {})
    if _is_mckinsey_brief(raw):
        return mckinsey_brief_body(tid, t, raw, memo_context=memo_context)
    brief = _brief(tid, t)
    owner = t.get("owner") or t.get("actor", "—")
    stale = _wip_stale(t)
    status = _status_emoji(t.get("status", ""), stale=stale)
    updated = (t.get("ts") or "")[:16].replace("T", " ")
    stale_note = ""
    if stale:
        age = _wip_age_minutes(t)
        mins = int(age) if age is not None else WIP_MEMO_MAX_AGE_MIN
        stale_note = (
            f"\n\n> **WIP policy (POL-002):** Last ledger touch was **{mins} minutes** ago. "
            f"Agents must append `task_updated` every {WIP_MEMO_MAX_AGE_MIN} minutes or set `idle`/`completed`.\n"
        )
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
**Last Updated:** {updated}{stale_note}

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