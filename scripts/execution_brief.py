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

# Pages under memos/ — use absolute URLs so links work from work-room, memo.html, and queue HTML.
_SITE_MEMO_PAGES = {
    "ledger.html": "memos/ledger.html",
    "gated-queue.html": "memos/gated-queue.html",
    "current.html": "memos/current.html",
    "policy.html": "memos/policy.html",
    "index.html": "index.html",
}


def resolve_link_href(href: str, *, memo_context: str = "queue") -> str:
    """Resolve dashboard links for any viewer (work-room, memo.html, memos/queue/*.html)."""
    if not href:
        return href
    if href.startswith("http"):
        return href
    if href in _SITE_MEMO_PAGES:
        return DASHBOARD + _SITE_MEMO_PAGES[href]
    if href.startswith("queue/"):
        return DASHBOARD + "memos/" + href
    if href in {"../index.html", "index.html"}:
        return DASHBOARD + "index.html"
    if href.startswith("../") and href.endswith(".html"):
        name = href.removeprefix("../")
        if name in _SITE_MEMO_PAGES:
            return DASHBOARD + _SITE_MEMO_PAGES[name]
    if memo_context == "queue" and href.endswith(".html") and "/" not in href:
        return DASHBOARD + f"memos/queue/{href}"
    return href

# Rich execution state keyed by task_id. Agents update via ledger + regenerate-memos.
EXECUTION_BRIEFS: dict[str, dict[str, Any]] = {
    "PMO-001": {
        "title": "Triage 13 ready-for-agent GitHub issues",
        "situation": (
            "Thirteen GitHub issues are labeled ready-for-agent but lack a ranked execution order. "
            "PMO must inventory, score ROI, and dispatch frontier workers within the $20/week cap — "
            "without burning budget on repo-lock collisions or low-yield doc-only tasks."
        ),
        "mece": [
            ("Understand the work", "Inventory 13 issues; classify capability/tier; estimate effort/risk (~35% done)"),
            ("Prioritize", "Score ROI with interim rubric until DEC-002; map dependencies; rank backlog (~15%)"),
            ("Execute", "Dispatch top issues to frontier workers; monitor budget; verify witnesses (~10%)"),
            ("Report & learn", "Update ledger, refresh briefs, capture lessons for postmortem (~5%)"),
        ],
        "paths_considered": [
            "FIFO dispatch — fast start but ignores ROI and repo-lock risk",
            "ROI-ranked batch with interim scoring — analysis-first, then dispatch top N",
            "Wait for DEC-002 scoring framework before any dispatch",
        ],
        "chosen_path_why": (
            "ROI-ranked batch with interim rubric wins because FIFO would waste slots on doc-only or "
            "blocked repos, and waiting for DEC-002 stalls the whole frontier. P-001 already approved "
            "pure analysis feeding this backlog — PMO executes the ranked dispatch once inventory "
            "and dependencies are clear."
        ),
        "where_it_stands": (
            "Issue inventory ~35% complete. Dependency mapping started. nick2-dashboard repo lock "
            "(JOB-453) cleared on main but PMO dispatch still needs a clean ranked top-5. DEC-002 "
            "scoring framework pending — interim rubric in use, not a hard block. No Nick gate."
        ),
        "effort": {
            "time": "Mission age ~5h · Last heartbeat due per POL-002 if stale",
            "work": "PMO worker enabled; inventory + ranking in flight",
            "budget": "spent $0.00 · remaining $20.00 · limit $20/week",
        },
        "links": [
            ("Dashboard", DASHBOARD),
            ("GitHub Issues", "https://github.com/nicholasg3/ai-agents-workspace/issues"),
            ("CEO Ledger", "ledger.html"),
            ("lane.json", "Projects-for-agents/frontier-orchestrator/lane.json"),
        ],
    },
    "P-001": {
        "title": "PMO Triage Proposal (Tier B)",
        "situation": (
            "CEO approved a Tier B proposal (score 0.6) to seed PMO-001 with analysis-first triage "
            "of 13 ready-for-agent GitHub issues. P-001 scopes pure analysis with no external writes — "
            "output feeds PMO-001's ranked backlog. Task is stale: no ledger heartbeat in 30+ minutes."
        ),
        "mece": [
            ("Scope", "Approved — pure analysis, no external writes; feeds PMO-001 (complete)"),
            ("Analyze", "Review issue board; draft rank inputs for PMO (~30%)"),
            ("Handoff", "Merge analysis into PMO-001 backlog; close P-001 (not started)"),
        ],
        "paths_considered": [
            "Dispatch all 13 issues immediately from CEO lane",
            "Analysis-first: rank inputs only, hand off to PMO-001 for dispatch",
            "Defer until DEC-002 scoring framework is finalized",
        ],
        "chosen_path_why": (
            "Analysis-first was approved because immediate dispatch would collide with repo locks "
            "and burn budget without ranking. PMO-001 owns execution; P-001 only produces the "
            "ranked recommendation and then closes."
        ),
        "where_it_stands": (
            "Proposal approved and scope locked. Analysis partially drafted; handoff to PMO-001 not "
            "yet complete. **Stale per POL-002** — CEO lane should append `task_updated` or transition "
            "to idle/completed after handoff."
        ),
        "effort": {
            "time": "Approved 14:50 SGT · No heartbeat 30+ min (stale)",
            "work": "Analysis in progress; handoff pending",
            "budget": "spent $0.00 · remaining $20.00 · limit $20/week",
        },
        "links": [
            ("Dashboard", DASHBOARD),
            ("PMO-001 brief", "queue/PMO-001.html"),
            ("CEO Ledger", "ledger.html"),
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
            "JOB-924 is **executing now** on the droplet (not blocked). One harness crash earlier "
            "required a requeue; repo-lock zombies (JOB-755/453) are cleared. Worker is implementing "
            "live ledger/bus API, POL-002 reconcile, and 15m sync cron on branch job/20260630-924. "
            "JOB-102 waits for 924 to finish. No Nick gate."
        ),
        "effort": {
            "time": (
                "Now: executing since ~19:50 SGT · Mission age ~2h · "
                "Past stalls (resolved): ~45m repo locks + ~15m harness retry — not current blockers"
            ),
            "work": "JOB-924 attempt 2 executing; attempt 1 blocked (harness); JOB-102 held; JOB-438 parallel",
            "budget": "spent $0.00 · remaining $20.00 · limit $20/week",
        },
        "links": [
            ("Dashboard", DASHBOARD),
            ("CEO Ledger", "ledger.html"),
        ],
    },
    "ISSUE-BUS-001": {
        "title": "Fix agent-bus worker_model crash",
        "situation": (
            "Coding workers cannot reliably spawn: `bus.py` calls `worker_model.py` to pick an "
            "OpenRouter slug, but an empty-string registry model breaks resolution. Until this "
            "lands, DISPATCH-001 jobs pile up held/queued behind dead harnesses."
        ),
        "mece": [
            ("Reproduce", "Scratch tests in worktree exercising resolve_or_ccr_default — in flight"),
            ("Patch", "bus.py passes None not \"\" when session meta has no model — patched in JOB-549 worktree"),
            ("Unit test", "Permanent test_worker_model.py under agent-bus/scripts — not merged yet"),
            ("Witness", "Tests exit 0; worker spawn shows model: line without traceback — open"),
        ],
        "paths_considered": [
            "Patch bus.py only (minimal — empty string → None)",
            "Rewrite worker_model tier routing (ISSUE-ROUTING-001 scope — defer)",
            "Bypass worker_model and hardcode CCR default (hides bug)",
        ],
        "chosen_path_why": (
            "Minimal bus.py fix first because the crash is an integration bug (empty string is "
            "truthy bad input), not missing routing policy. Routing policy is rank #3 separately."
        ),
        "where_it_stands": (
            "JOB-549 executing on ai-agents-workspace. Worktree shows 1-line bus.py fix plus "
            "scratch reproduce scripts; permanent test + witness still needed before complete."
        ),
        "effort": {
            "time": "Executing — watch 15m coding_worker timeout",
            "work": "coding_worker branch job/20260630-549-issue-bus-001-fix-agent-bus-wo",
            "budget": "spent $0.00 · remaining $20.00 · limit $20.00/week",
        },
        "links": [
            ("Dashboard", DASHBOARD),
            ("worker_model.py", "agent-bus/scripts/worker_model.py"),
            ("CEO Ledger", "ledger.html"),
        ],
    },
    "ISSUE-80": {
        "title": "Dashboard live-sync + honest memos",
        "situation": (
            "Nick cannot tell what workers are doing from thin job memos and lagging exports. "
            "POL-003 requires reconcile-on-finish, bus-live export, and cron sync on the droplet."
        ),
        "mece": [
            ("Live export", "export_bus_live.py + generate_job_memos on sync tick"),
            ("Reconcile", "reconcile-ledger.py flags stale in_progress per POL-002"),
            ("Cron", "sync-dashboard-live.sh every 15m on droplet"),
            ("Witness", "witness_dashboard_honesty.py exits 0"),
        ],
        "paths_considered": [
            "React rewrite",
            "Extend gate server + vanilla JS (chosen for SYS-002)",
            "Static-only shorter cron",
        ],
        "chosen_path_why": (
            "Extend existing Python gate server — same path as SYS-002 live mission; add POL-005 "
            "narrative job memos so Nick sees what each worker is actually doing."
        ),
        "where_it_stands": (
            "JOB-573 executing on nick2-dashboard in parallel with ISSUE-BUS-001 on workspace repo."
        ),
        "effort": {
            "time": "Parallel lane #2 after PMO triage",
            "work": "coding_worker on nick2-dashboard",
            "budget": "spent $0.00 · remaining $20.00 · limit $20.00/week",
        },
        "links": [
            ("Dashboard", DASHBOARD),
            ("GitHub #80", "https://github.com/nicholasg3/ai-agents-workspace/issues/80"),
            ("CEO Ledger", "ledger.html"),
        ],
    },
}


def _is_mckinsey_brief(brief: dict[str, Any]) -> bool:
    return bool(brief.get("situation") and brief.get("mece"))


def _resolve_brief_tid(tid: str, events: list[dict] | None = None) -> str:
    """FOCUS-001 mirrors the CEO focus mission (e.g. SYS-002)."""
    if tid != "FOCUS-001" or not events:
        return tid
    for ev in reversed(events):
        if ev.get("event") in ("focus_snapshot", "ceo_focus") and ev.get("focus_task_id"):
            return ev["focus_task_id"]
    return tid


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

    back = DASHBOARD + "index.html"
    links = "\n".join(
        f"- [{label}]({resolve_link_href(href, memo_context=memo_context)})"
        for label, href in brief.get("links", [("Dashboard", DASHBOARD)])
    )
    alias_note = ""
    if brief.get("_alias_from"):
        alias_note = f"\n\n_Focus memo sourced from **{brief['_alias_from']}**._\n"

    return f"""{_date_stamp()}

[← Dashboard]({back})

**{tid}: {title}**{alias_note}

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
    brief_tid = _resolve_brief_tid(tid, events)
    raw = dict(EXECUTION_BRIEFS.get(brief_tid) or EXECUTION_BRIEFS.get(tid, {}))
    if brief_tid != tid and raw:
        raw["_alias_from"] = brief_tid
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

    links = "\n".join(
        f"- [{label}]({resolve_link_href(href, memo_context=memo_context)})"
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