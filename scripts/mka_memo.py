"""McKinsey-style (MKA) memo framework for Nick2 dashboard memos.

Sequence: Executive Framing → MECE decomposition → Root cause → Options → Recommendation.
Execution plan omitted unless explicitly requested (not used for auto-generated memos).
"""
from __future__ import annotations

from typing import Any

# Rich briefs keyed by task_id. Fallback builder uses ledger fields when missing.
TASK_BRIEFS: dict[str, dict[str, Any]] = {
    "DEC-002": {
        "objective": "Enable consistent, repeatable ranking of ready-for-agent GitHub issues before autonomous dispatch consumes the weekly budget.",
        "decision": "Approve, modify, or defer the PMO scoring framework.",
        "mece": [
            ("Impact", "Strategic value, unblocker effect, revenue adjacency", "13 issues waiting; no agreed rank order"),
            ("Effort & risk", "Agent complexity, external writes, rollback cost", "Tier-B proposal exists; scores not standardized"),
            ("Readiness", "Issue clarity, artifacts, runnable witness", "Issues marked ready-for-agent in workspace"),
            ("Governance", "Budget fit ($20/wk), trust tier, Nick-only gates", "DEC-002 is the last high-priority framework gate"),
        ],
        "root_cause": "PMO cannot scale triage without a shared rubric — ad-hoc ranking would misallocate the $20/week cap across low-ROI agent runs.",
        "options": [
            {
                "name": "Approve default framework (pilot)",
                "upside": "Unblocks PMO-001 immediately; impact×readiness/effort is good enough for first cycle.",
                "downside": "Weights may need tuning after first spend report.",
                "when": "Nick wants velocity over perfect calibration.",
            },
            {
                "name": "Approve with Nick-tuned weights",
                "upside": "Better fit to Nick's ROI preferences before any spend.",
                "downside": "Adds one review round; delays first dispatch.",
                "when": "Nick has strong priors on issue priority.",
            },
            {
                "name": "Defer — manual CEO triage only",
                "upside": "Zero framework risk.",
                "downside": "Does not scale; wastes PMO capacity; blocks autonomous loop.",
                "when": "Only if autonomous dispatch is off indefinitely.",
            },
            {
                "name": "Reject — revert to ad-hoc picks",
                "upside": "No process overhead.",
                "downside": "Highest risk of budget waste and inconsistent outcomes.",
                "when": "Not recommended while budget is capped and worker may enable.",
            },
        ],
        "recommendation": "**Approve the default framework for a pilot on the top 3 issues.** Revisit weights after the first weekly spend report (CFO).",
        "nick_action": "Reply approve / approve-with-weights / defer. CEO appends `decision_resolved` for DEC-002.",
    },
    "DEC-003": {
        "objective": "Give Nicholas real-time visibility when weekly OpenRouter spend crosses material thresholds — before the $20 cap is silently exhausted.",
        "decision": "Which alert channel and threshold rules to use for spend notifications.",
        "mece": [
            ("Channel", "How Nick receives the signal", "No push channel configured"),
            ("Threshold logic", "When alerts fire", "Proposed: every $5 of cumulative weekly spend"),
            ("Recipient & escalation", "Who acts on the alert", "Nick (budget owner)"),
            ("Fallback", "Behavior if delivery fails", "Hourly reconcile + dashboard only today"),
        ],
        "root_cause": "Budget is authorized and capped, but spend is only visible on reconcile — no interrupt path for Nick to throttle or reprioritize mid-week.",
        "options": [
            {
                "name": "Telegram bot → Nick",
                "upside": "Real-time; mobile; low friction once bot token is set.",
                "downside": "Requires one-time bot setup and chat ID.",
                "when": "Nick wants push alerts (recommended).",
            },
            {
                "name": "Email digest (hourly)",
                "upside": "No new infra beyond SMTP.",
                "downside": "Slower; easy to miss.",
                "when": "Telegram is undesirable.",
            },
            {
                "name": "Dashboard + reconcile only",
                "upside": "Zero setup.",
                "downside": "No proactive signal; Nick must pull.",
                "when": "Acceptable only at very low spend velocity.",
            },
            {
                "name": "Hard stop at $18 auto-pause",
                "upside": "Automatic cap protection.",
                "downside": "No human judgment before pause; may halt good work.",
                "when": "Combine with A or B, not alone.",
            },
        ],
        "recommendation": "**Telegram alerts at $5 / $10 / $15 / $20 cumulative weekly spend**, with reconcile as fallback witness. Pair with auto-pause at $18 if desired.",
        "nick_action": "Confirm Telegram (provide chat ID or approve CTO to wire bot) or choose email/dashboard-only.",
    },
    "PMO-001": {
        "objective": "Produce a ranked execution order for 13 ready-for-agent GitHub issues — highest ROI first within the $20/week budget.",
        "decision": "**Settled — Nicholas chose Option B** (enable worker + dispatch). Agents: execute.",
        "mece": [
            ("Inventory", "13 issues, tiers, dependencies", "In progress; P-001 approved (Tier B)"),
            ("Scoring", "Framework weights and rank output", "DEC-002 still open — use interim rubric until Nick approves"),
            ("Dispatch readiness", "Budget, worker flag, model routing", "Budget $20/wk; `worker.enabled=true` (Nick 2026-06-30)"),
            ("Deliverable", "Ranked list + memos for top 3", "PMO dispatch authorized"),
        ],
        "root_cause": "Was configuration lag (`worker.enabled=false`). **Resolved** — Nick explicitly approved Option B and worker dispatch.",
        "options": [
            {
                "name": "Option B — active (Nick approved)",
                "upside": "Full autonomous dispatch after triage within $20/wk cap.",
                "downside": "Spend starts; DEC-002 scoring framework still pending for calibration.",
                "when": "**Selected by Nicholas.** PMO must append ledger events and push nick2-dashboard on milestones.",
            },
        ],
        "recommendation": "**Execute PMO triage and dispatch now.** Append `task_updated` / `task_completed` events to `nick2-dashboard/logs/ceo-ledger.jsonl` and push — dashboard is the public source of truth.",
        "nick_action": "None — Option B approved. Monitor spend on dashboard until DEC-003 alerts ship.",
    },
    "SYS-001": {
        "objective": "Turn on the frontier worker execution path so queued PMO work can dispatch against the authorized budget.",
        "decision": "**Settled — worker enabled** per Nicholas Option B (PMO-001).",
        "mece": [
            ("Worker flag", "`worker.enabled` in lane.json", "**true** — auto-dispatch on"),
            ("Budget gate", "Weekly cap authorized", "$20/week capped (BUD-002)"),
            ("Model routing", "Default worker model", "moonshotai/kimi-k2.6 configured"),
            ("Safety", "Trust tier, spend alerts", "Baseline trust; DEC-003 alerts pending — monitor dashboard"),
        ],
        "root_cause": "Was pre-budget default (`enabled=false`). **Resolved** by Nick directive.",
        "options": [],
        "recommendation": "**Worker live.** Frontier orchestrator may spawn workers per lane.json. CFO tracks spend; agents log costs to ledger.",
        "nick_action": "None.",
    },
    "P-001": {
        "objective": "Validate the highest-ROI next move among 13 ready-for-agent issues before broader PMO ranking.",
        "decision": "Whether to proceed with the Tier-B analysis proposal (score 0.6).",
        "mece": [
            ("Proposal", "Tier B, score 0.6, pure analysis", "Approved in ledger"),
            ("Scope", "No external writes", "Low risk, no spend"),
            ("Dependency", "Feeds PMO-001 ranked output", "Downstream of DEC-002 for full autonomy"),
            ("Output", "Ranked recommendation memo", "Pending PMO execution"),
        ],
        "root_cause": "Issue backlog exceeds manual CEO capacity — need structured triage entry point.",
        "options": [
            {
                "name": "Execute proposal as approved",
                "upside": "Already approved; aligns with PMO-001.",
                "downside": "None material for analysis-only.",
                "when": "Default — proceed.",
            },
            {
                "name": "Expand scope to include writes",
                "upside": "Faster shipping on top issue.",
                "downside": "Spend + trust implications; needs CFO review.",
                "when": "Only after explicit budget line item.",
            },
        ],
        "recommendation": "**Execute the approved analysis-only proposal** as the seed input for PMO-001 ranking.",
        "nick_action": "None required — already approved.",
    },
    "DASH-001": {
        "objective": "Give Nick2 a single-pane operating view: ledger, queue, budget, gates, and trust.",
        "decision": "N/A — delivered.",
        "mece": [
            ("UI", "Dashboard panels", "Shipped on GitHub Pages"),
            ("Source of truth", "ceo-ledger.jsonl", "Append-only, reconcile hourly"),
            ("Deploy", "GitHub Actions", "Automated"),
            ("Deep links", "Memos + HTML", "This pipeline"),
        ],
        "root_cause": "Operating state was scattered across repos — no executive snapshot.",
        "options": [],
        "recommendation": "**Shipped.** Maintain via ledger events + hourly reconcile.",
        "nick_action": "None.",
    },
    "BUD-002": {
        "objective": "Authorize autonomous agent spend with a hard weekly ceiling.",
        "decision": "N/A — Nicholas set $20/week.",
        "mece": [
            ("Cap", "$20/week OpenRouter", "Authorized"),
            ("Convention", "0=OFF, positive=cap", "Locked via DEC-001 resolution"),
            ("Remaining", "Budget headroom", "See dashboard"),
            ("Controls", "Alerts + reconcile", "DEC-003 pending"),
        ],
        "root_cause": "Prior `per_cycle: 0` ambiguity blocked dispatch — now resolved.",
        "options": [],
        "recommendation": "**Budget live.** CFO monitors spend; COO reconciles hourly.",
        "nick_action": "None.",
    },
    "POL-001": {
        "objective": "Prevent agent idle time when work is gated on Nick.",
        "decision": "N/A — policy published.",
        "mece": [
            ("Gate", "nick_gate / decision_needed", "Park in Gated queue"),
            ("Execute", "Active Work Queue", "Ungated only"),
            ("Clear", "nick_gate_resolved", "Nick or reconcile"),
            ("Anti-pattern", "Blocking on Nick", "Explicitly forbidden"),
        ],
        "root_cause": "Without a gate convention, agents stall on human dependencies.",
        "options": [],
        "recommendation": "**Policy active.** Agents continue ungated work while Nick clears gates.",
        "nick_action": "None — reference when clearing gates.",
    },
}


def _meta_line(t: dict, extras: list[str] | None = None) -> str:
    parts = [
        f"**Owner:** {t.get('owner') or t.get('actor', '—')}",
        f"**Status:** {t.get('status', '—')}",
        f"**Updated:** {(t.get('ts') or '')[:16]}",
    ]
    if extras:
        parts.extend(extras)
    return " · ".join(parts) + "\n"


def _section_mece(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        "## 2. Problem Decomposition (MECE)",
        "",
        "| Bucket | Scope | Current state |",
        "|--------|-------|---------------|",
    ]
    for bucket, scope, state in rows:
        lines.append(f"| {bucket} | {scope} | {state} |")
    return "\n".join(lines) + "\n"


def _section_options(options: list[dict[str, str]]) -> str:
    if not options:
        return ""
    lines = ["## 4. Strategic Options", ""]
    for i, opt in enumerate(options, 1):
        letter = chr(ord("A") + i - 1)
        lines.append(f"### Option {letter}: {opt['name']}")
        lines.append(f"- **Upside:** {opt['upside']}")
        lines.append(f"- **Downside:** {opt['downside']}")
        lines.append(f"- **When to choose:** {opt['when']}")
        lines.append("")
    return "\n".join(lines)


def _brief(tid: str, t: dict) -> dict[str, Any]:
    b = dict(TASK_BRIEFS.get(tid, {}))
    output = (t.get("output") or "").strip()
    if output and "objective" not in b:
        b.setdefault("objective", f"Advance: {t.get('task', tid)}")
    if output:
        b.setdefault("ledger_context", output)
    return b


def _fallback_mece(tid: str, t: dict) -> list[tuple[str, str, str]]:
    output = t.get("output") or "No detail in ledger yet."
    return [
        ("Work unit", t.get("task", tid), output[:120]),
        ("Status & owner", f"{t.get('status', '—')} / {t.get('owner') or t.get('actor', '—')}", (t.get("ts") or "")[:16]),
        ("Dependencies", "Gates, budget, worker", "See dashboard Gated queue and budget panel"),
        ("Deliverable", "Ledger event + artifacts", ", ".join(t.get("artifacts") or []) or "Not listed"),
    ]


def _fallback_options(t: dict, gated: bool) -> list[dict[str, str]]:
    if gated:
        return [
            {
                "name": "Approve / proceed",
                "upside": "Unblocks downstream work immediately.",
                "downside": "Commits to direction Nick should validate.",
                "when": "Ledger context supports the ask.",
            },
            {
                "name": "Approve with modifications",
                "upside": "Tailors to Nick's constraints.",
                "downside": "One extra iteration.",
                "when": "Direction is right, details need tuning.",
            },
            {
                "name": "Defer",
                "upside": "Buys time for more evidence.",
                "downside": "Agents must stay on ungated work only.",
                "when": "Insufficient information to decide.",
            },
        ]
    return [
        {
            "name": "Execute now",
            "upside": "Moves the queue forward.",
            "downside": "May consume budget or need Nick later.",
            "when": "No open gates block this task.",
        },
        {
            "name": "Execute analysis-only first",
            "upside": "Decision-ready output without spend.",
            "downside": "Delays full automation.",
            "when": "Worker off or framework pending.",
        },
        {
            "name": "Park in Gated queue",
            "upside": "Surfaces Nick decision clearly.",
            "downside": "Agents cannot execute this item.",
            "when": "Truly needs Nicholas.",
        },
    ]


def _ledger_note(brief: dict[str, Any]) -> str:
    ctx = brief.get("ledger_context")
    if not ctx:
        return ""
    return f"\n_Ledger note:_ {ctx}\n"


def mka_header(tid: str, t: dict, subtitle: str = "") -> str:
    title = t.get("task", "Task")
    sub = f"\n_{subtitle}_\n" if subtitle else "\n"
    return f"# {tid}: {title}{sub}{_meta_line(t)}"


def mka_gated_body(tid: str, t: dict, rank: int) -> str:
    brief = _brief(tid, t)
    what = t.get("what_nick_must_do") or brief.get("nick_action") or t.get("output", "Review and respond.")
    objective = brief.get("objective", f"Resolve gate on: {t.get('task', tid)}")
    decision = brief.get("decision", f"What Nick decides for `{tid}`")
    mece = brief.get("mece") or _fallback_mece(tid, t)
    root = brief.get(
        "root_cause",
        "Human decision is on the critical path — agents cannot proceed without Nick's call.",
    )
    options = brief.get("options") or _fallback_options(t, gated=True)
    rec = brief.get("recommendation", f"**Review and respond** — see “What Nick must do” below.")

    parts = [
        mka_header(tid, t, f"Gated by Nick · priority #{rank} · {t.get('priority', 'medium')}"),
        "## 1. Executive Framing",
        "",
        f"**Objective:** {objective}",
        "",
        f"**Decision:** {decision}",
        _ledger_note(brief),
        _section_mece(mece),
        "## 3. Root Cause",
        "",
        root,
        "",
        _section_options(options),
        "## 5. Recommendation",
        "",
        rec,
        "",
        "### What Nick must do",
        "",
        what,
        "",
        "### Context for agents",
        "",
        "This item is **gated**. Do not idle — continue ungated work in the Active Work Queue.",
        "",
        "### Clear this gate",
        "",
        f"Append `nick_gate_resolved` or `decision_resolved` for `{tid}`.",
        "",
        "[Policy](../policy.html)",
    ]
    return "\n".join(parts)


def mka_queue_body(tid: str, t: dict, weekly: float) -> str:
    brief = _brief(tid, t)
    objective = brief.get("objective", f"Complete: {t.get('task', tid)}")
    decision = brief.get(
        "decision",
        "What action unblocks or completes this queue item.",
    )
    mece = brief.get("mece") or _fallback_mece(tid, t)
    root = brief.get(
        "root_cause",
        t.get("output") or "See ledger for latest blocker or next step.",
    )
    options = brief.get("options") or _fallback_options(t, gated=False)
    rec = brief.get("recommendation", "**Proceed** per owner assignment unless a gate applies.")
    nick_action = brief.get("nick_action", "")

    budget_line = ""
    if weekly > 0:
        budget_line = f"\n**Weekly budget:** ${weekly:.2f} (capped)\n"

    nick_section = ""
    if t.get("needs_nicholas") or nick_action:
        action = nick_action or t.get("output", "Review and approve.")
        nick_section = f"\n### Nick action (if any)\n\n{action}\n"

    parts = [
        mka_header(tid, t, "Active Work Queue"),
        "## 1. Executive Framing",
        "",
        f"**Objective:** {objective}",
        "",
        f"**Decision:** {decision}",
        budget_line,
        _ledger_note(brief),
        _section_mece(mece),
        "## 3. Root Cause",
        "",
        root,
        "",
        _section_options(options),
        "## 5. Recommendation",
        "",
        rec,
        nick_section,
        "### Links",
        "",
        "- [Dashboard](https://nicholasg3.github.io/nick2-dashboard/)",
        f"- Ledger: `logs/ceo-ledger.jsonl` (`{tid}`)",
    ]
    return "\n".join(parts)


def mka_completed_body(tid: str, t: dict) -> str:
    brief = _brief(tid, t)
    arts = t.get("artifacts") or []
    art_block = "\n".join(f"- `{a}`" for a in arts) if arts else "_None listed._"
    objective = brief.get("objective", f"Delivered: {t.get('task', tid)}")
    root = brief.get("root_cause", "Work item reached completed status in ledger.")
    rec = brief.get("recommendation", "**Done.** No further action unless regression.")
    mece = brief.get("mece") or _fallback_mece(tid, t)

    mece_block = _section_mece(mece).replace("## 2. Problem Decomposition (MECE)", "## 2. What shipped (MECE)")

    return f"""# {tid}: {t.get('task', 'Task')} — Completed

{_meta_line(t, [f"**Cost:** ${float(t.get('cost_usd') or 0):.2f}"])}

## 1. Executive Framing

**Objective:** {objective}  
**Outcome:** {t.get('output', 'Task completed.')}

{mece_block}
## 3. Root cause addressed

{root}

## 5. Recommendation

{rec}

## Artifacts

{art_block}
"""


def mka_current_body(
    *,
    primary: dict,
    pid: str,
    now: str,
    weekly: float,
    spend: float,
    mode: str,
    gated_count: int,
) -> str:
    task = primary.get("task", "Idle")
    owner = primary.get("owner") or primary.get("actor", "CEO")
    output = primary.get("output", "")
    status = primary.get("status", "—")

    return f"""# Current focus — Nick2

_Updated {now} (hourly cadence)_

## 1. Executive Framing

**Objective:** Keep Nick2 moving on the highest-leverage **ungated** work while gates wait in Nick's priority inbox.  
**Decision this cycle:** Whether to enable worker dispatch (`worker.enabled`) and clear DEC-002 / DEC-003.

## 2. State (MECE)

| Bucket | Now |
|--------|-----|
| **Focus** | {owner}: [{task}](queue/{pid}.html) (`{pid}`) |
| **Status** | {status} |
| **Budget** | ${weekly:.2f}/wk · spent ${spend:.2f} · mode {mode} |
| **Gates** | {gated_count} item(s) waiting on Nick |

## 3. Root cause

{output or "No blocker text in ledger — see task memo."}

## 5. Recommendation

**Agents:** [PMO triage](queue/PMO-001.html) **in progress** — worker enabled (Nick Option B). Append ledger + push `nick2-dashboard` on each milestone.  
**Nick:** Clear [Approve PMO scoring framework](gated/DEC-002.html) and [Confirm Telegram alert method](gated/DEC-003.html) when ready.
"""


def mka_gated_queue_body(gated_items: list[tuple[str, dict]]) -> str:
    if not gated_items:
        return """# Gated by Nick — priority queue

## 1. Executive Framing

**Objective:** Surface decisions only Nick can make — without stopping agent execution elsewhere.  
**Decision:** None pending in queue.

## 5. Recommendation

**Agents:** Keep executing the Active Work Queue. No gates open.
"""

    rows = []
    for i, (tid, t) in enumerate(gated_items):
        task = t.get("task", tid)
        rows.append(
            f"| {i + 1} | {t.get('priority', 'medium')} | `{tid}` | "
            f"[{task}](../gate-room.html?task={tid}) |"
        )

    return f"""# Gated by Nick — priority queue

## 1. Executive Framing

**Objective:** Ordered inbox of decisions that block or shape autonomous operations.  
**Decision:** Nick works top-down; agents ignore this list for execution.

## 2. Queue (MECE)

| # | Priority | ID | Decision needed |
|---|----------|-----|-----------------|
{chr(10).join(rows)}

## 3. Root cause

Gates exist because framework, alerts, or explicit approval require Nick — not because agents are idle.

## 5. Recommendation

**Nick:** Start with **#1** ({gated_items[0][1].get('task', gated_items[0][0])}).  
**Agents:** Continue ungated queue — [policy](policy.html).
"""