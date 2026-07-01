#!/usr/bin/env python3
"""Optional LLM layer for CEO reflection (POL-010) — OpenRouter, admission-validated."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
HERMES_ENV = Path(os.environ.get("HERMES_ENV", Path.home() / ".hermes" / ".env"))
STATE_PATH = ROOT / "reports" / "ceo-reflect-state.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("CEO_REFLECT_MODEL", "openai/gpt-4.1-mini")
MARKER = "ceo-reflect-llm:"

SYSTEM_PROMPT = """You are the CEO for Nick2 — an autonomous executive that improves the organization during idle time.

Core mission: when the bus is idle (0 running/queued/held), continuously identify the highest expected-value action for long-term capability:
- What bottleneck limits progress?
- What repetitive work can be automated or eliminated?
- What system can be made more autonomous?
- What technical debt, missing docs, or leverage improvement has high ROI?

You have standing authority (within weekly budget + trust boundaries) to:
- Spawn tracked sub-agents (claude -p with bypassPermissions) for diagnostics, audits, improvements.
- Edit code, commit, write memos, update skills.
- Register new tracked CEO initiatives (use CEO-INIT-* IDs).
- Reconsider org structure.

You must output JSON only. Schema (all fields optional except situation_summary):
{
  "situation_summary": "2-4 sentences of current state + opportunity",
  "root_causes": ["..."],
  "unstick_ideas": [{"idea": "...", "rationale": "..."}],
  "delegate_recommendation": null | {"task_id": "ISSUE-N", "rationale": "..."},
  "open_initiative": null | {
    "initiative_id": "CEO-INIT-YYYYMMDD-NNN or short name",
    "title": "one line",
    "why_now": "why highest EV",
    "est_cost_usd": 0.5,
    "first_step": "concrete action or claude -p command skeleton",
    "expected_outcome": "..."
  },
  "focus_shift": null | {"task_id": "ISSUE-N or CEO-INIT-xxx", "focus_line": "plain sentence"},
  "nick_attention": ["only for irreversible Level 3+ decisions"]
}

When idle with budget and no high bottlenecks, prefer proposing 1 open_initiative over waiting. Be specific, actionable, and cost-conscious. Prefer reversible, low-blast-radius actions with clear value.
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_openrouter_key() -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    if HERMES_ENV.is_file():
        for line in HERMES_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == "OPENROUTER_API_KEY":
                return v.strip().strip('"').strip("'")
    return ""


def llm_enabled() -> bool:
    flag = os.environ.get("CEO_REFLECT_LLM", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return bool(_load_openrouter_key())


def llm_execute_enabled() -> bool:
    flag = os.environ.get("CEO_REFLECT_LLM_EXECUTE", "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def interval_minutes() -> int:
    try:
        return max(0, int(os.environ.get("CEO_REFLECT_INTERVAL_MIN", "60")))
    except ValueError:
        return 60


def load_state() -> dict:
    if not STATE_PATH.is_file():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def should_run_llm(*, force: bool = False) -> tuple[bool, str]:
    if not llm_enabled():
        return False, "CEO_REFLECT_LLM off or no OPENROUTER_API_KEY"
    if force:
        return True, "forced"
    interval = interval_minutes()
    if interval <= 0:
        return True, "interval disabled"
    state = load_state()
    last = _parse_ts(state.get("last_llm_at"))
    if not last:
        return True, "first llm reflect"
    age = (datetime.now(timezone.utc) - last.astimezone(timezone.utc)).total_seconds() / 60.0
    if age >= interval:
        return True, f"interval elapsed ({age:.0f}m >= {interval}m)"
    return False, f"interval not elapsed ({age:.0f}m < {interval}m)"


def _compact_context(ctx: dict, bottlenecks: list[dict], admission: dict, proposals: list[dict]) -> dict:
    tasks = ctx.get("tasks") or {}
    active_issues = []
    for tid, t in sorted(tasks.items()):
        if not tid.startswith("ISSUE-"):
            continue
        if (t.get("status") or "") not in ("queued", "in_progress", "blocked"):
            continue
        active_issues.append({
            "task_id": tid,
            "status": t.get("status"),
            "owner": t.get("owner"),
            "output_tail": (t.get("output") or "")[-200:],
        })
    triage_rows = []
    for item in (ctx.get("triage") or {}).get("top_issues") or []:
        triage_rows.append({
            "task_id": item.get("task_id"),
            "rank": item.get("rank"),
            "dispatch": item.get("dispatch"),
            "defer_reason": item.get("defer_reason"),
            "title": item.get("title"),
        })
    bus = []
    for row in (ctx.get("bus_rows") or [])[:12]:
        bus.append({
            "job_id": row.get("job_id"),
            "status": row.get("status"),
            "session": row.get("to_session"),
            "hold_reason": (row.get("hold_reason") or "")[:100],
            "objective": (row.get("objective") or "")[:120],
        })
    # Surface recent CEO activity and idle signal for open reasoning
    recent_ceo = []
    for ev in reversed((ctx.get("events_tail") or [])[-8:]):
        if (ev.get("actor") or "").upper() == "CEO":
            recent_ceo.append({
                "ts": ev.get("ts"),
                "event": ev.get("event"),
                "task_id": ev.get("task_id"),
                "output": (ev.get("output") or "")[:180],
            })
    idle = (ctx.get("counts") or {}).get("running", 0) == 0 and (ctx.get("counts") or {}).get("queued", 0) == 0
    return {
        "counts": ctx.get("counts"),
        "budget_remaining_usd": ctx.get("ledger_base", {}).get("budget_remaining_usd"),
        "bottlenecks": bottlenecks,
        "admission": admission,
        "rule_proposals": proposals[:10],
        "active_issues": active_issues,
        "triage": triage_rows,
        "bus_jobs": bus,
        "recent_ceo_activity": recent_ceo,
        "is_idle": idle,
        "memories": [
            {"kind": m.get("kind"), "text": (m.get("text") or "")[:300]}
            for m in (ctx.get("memories_tail") or [])
        ],
    }


def call_openrouter(payload: dict) -> tuple[dict | None, dict]:
    """Returns (parsed_json, meta) where meta has model, usage, error."""
    key = _load_openrouter_key()
    if not key:
        return None, {"error": "no OPENROUTER_API_KEY"}

    model = os.environ.get("CEO_REFLECT_MODEL", DEFAULT_MODEL)
    body = {
        "model": model,
        "max_tokens": int(os.environ.get("CEO_REFLECT_MAX_TOKENS", "1200")),
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://github.com/nicholasg3/nick2-dashboard",
            "X-Title": "nick2-ceo-reflect",
        },
        method="POST",
    )
    meta: dict[str, Any] = {"model": model}
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.load(resp)
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            usage = data.get("usage") or {}
            meta["usage"] = usage
            meta["cost_usd"] = _estimate_cost(model, usage)
            parsed = parse_llm_json(content)
            if parsed is None:
                meta["error"] = "json parse failed"
                meta["raw"] = content[:500]
            return parsed, meta
        except urllib.error.HTTPError as e:
            meta["error"] = f"HTTP {e.code}: {e.read().decode()[:300]}"
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return None, meta
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            meta["error"] = str(e)[:300]
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return None, meta
    return None, meta


def _estimate_cost(model: str, usage: dict) -> float:
    """Rough USD estimate — ledger tail uses 0 if unknown."""
    try:
        total = int(usage.get("total_tokens") or 0)
    except (TypeError, ValueError):
        return 0.0
    if not total:
        return 0.0
    if "gpt-4.1-mini" in model:
        return round(total * 0.0000004, 4)
    if "deepseek" in model:
        return round(total * 0.0000002, 4)
    return round(total * 0.000001, 4)


def parse_llm_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    return data


def _issue_item(ctx: dict, task_id: str) -> dict:
    import pmo_dispatch as pd  # noqa: E402

    for item in (ctx.get("triage") or {}).get("top_issues") or []:
        if pd.issue_task_id(item) == task_id:
            return item
    t = (ctx.get("tasks") or {}).get(task_id, {})
    return {
        "task_id": task_id,
        "title": t.get("task"),
        "issue_number": t.get("issue_number"),
        "worker": "coding_worker",
        "repo": "ai-agents-workspace",
    }


def validate_delegate(task_id: str, ctx: dict, admission: dict) -> str | None:
    """Return error string if invalid, else None."""
    import pmo_dispatch as pd  # noqa: E402
    import work_queue_ops as wqo  # noqa: E402

    if admission.get("max_new_delegations", 0) < 1 and admission.get("max_retries", 0) < 1:
        return "no admission slots"
    if not task_id or not str(task_id).startswith("ISSUE-"):
        return "task_id must be ISSUE-*"
    if wqo.is_deferred_task(task_id):
        return f"{task_id} is deferred / decision-gated"
    triage_item = None
    for item in (ctx.get("triage") or {}).get("top_issues") or []:
        if pd.issue_task_id(item) == task_id:
            triage_item = item
            break
    if triage_item and triage_item.get("dispatch") is False:
        return f"{task_id} dispatch:false in triage"
    tasks = ctx.get("tasks") or {}
    if tasks.get(task_id, {}).get("status") in ("queued", "in_progress", "completed"):
        return f"{task_id} already active on ledger"
    return None


def apply_llm_actions(
    llm: dict,
    ctx: dict,
    admission: dict,
    *,
    append_fn: Callable[[dict], bool] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Execute admission-validated LLM recommendations only."""
    if not llm_execute_enabled() or dry_run:
        return []
    import pmo_dispatch as pd  # noqa: E402

    actions: list[dict] = []
    base = ctx.get("ledger_base") or {}

    rec = llm.get("delegate_recommendation")
    if isinstance(rec, dict) and rec.get("task_id"):
        tid = str(rec["task_id"])
        err = validate_delegate(tid, ctx, admission)
        if err:
            actions.append({"action": "llm_delegate_rejected", "task_id": tid, "reason": err})
        elif admission.get("max_new_delegations", 0) > 0:
            item = _issue_item(ctx, tid)
            item = {**item, "task_id": tid}
            worker = (item.get("worker") or "coding_worker").strip()
            repo = (item.get("repo") or "ai-agents-workspace").strip()
            objective = pd.build_objective(item, tid)
            bus_out = pd.submit_bus_job(
                session=worker,
                objective=objective,
                repo=repo,
                task_id=tid,
                item=item,
                from_harness="ceo-reflect-llm",
            )
            job_id = (bus_out or {}).get("job_id") if isinstance(bus_out, dict) else None
            if job_id and append_fn:
                pd.append_ledger(
                    {
                        **base,
                        "actor": "CEO",
                        "role": "Chief Executive Officer",
                        "event": "task_queued",
                        "task_id": tid,
                        "task": item.get("title") or tid,
                        "status": "queued",
                        "owner": worker.replace("_worker", ""),
                        "output": f"{MARKER}LLM delegate: {(rec.get('rationale') or '')[:180]}",
                    },
                    append_fn,
                )
            actions.append({
                "action": "llm_delegate",
                "task_id": tid,
                "job_id": job_id,
                "rationale": rec.get("rationale"),
            })

    focus = llm.get("focus_shift")
    if isinstance(focus, dict) and focus.get("task_id") and append_fn:
        import work_queue_ops as wqo  # noqa: E402

        fid = str(focus["task_id"])
        if not wqo.is_deferred_task(fid):
            t = (ctx.get("tasks") or {}).get(fid, {})
            pd.append_ledger(
                {
                    **base,
                    "actor": "CEO",
                    "role": "Chief Executive Officer",
                    "event": "focus_snapshot",
                    "task_id": "FOCUS-001",
                    "focus_task_id": fid,
                    "task": t.get("task") or fid,
                    "status": t.get("status") or "in_progress",
                    "owner": "CEO",
                    "focus_line": (focus.get("focus_line") or f"CEO focus → {fid}")[:120],
                    "focus_detail": "LLM reflection shifted focus within admission pass.",
                    "output": f"{MARKER}focus → {fid}",
                },
                append_fn,
            )
            actions.append({"action": "llm_focus_shift", "task_id": fid})

    # NEW: open_initiative support — register as a visible CEO-INIT-* task so it appears
    # in Active Work Queue and Agent Fleet. The supervisor or chat CEO can then execute.
    init = llm.get("open_initiative")
    if isinstance(init, dict) and init.get("initiative_id") and append_fn:
        iid = str(init.get("initiative_id"))
        title = init.get("title") or iid
        cost = float(init.get("est_cost_usd") or 0.3)
        pd.append_ledger(
            {
                **base,
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "task_queued",
                "task_id": iid,
                "task": title,
                "status": "queued",
                "owner": "CEO",
                "output": f"{MARKER}open initiative: {init.get('why_now','')[:160]}",
                "cost_usd": cost,
                "est_cost_usd": cost,
                "initiative": init,
            },
            append_fn,
        )
        # Immediately mark in_progress for visibility (CEO will execute or spawn)
        pd.append_ledger(
            {
                **base,
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "task_updated",
                "task_id": iid,
                "task": title,
                "status": "in_progress",
                "owner": "CEO",
                "output": f"First step: {init.get('first_step','(see initiative)')[:200]}",
            },
            append_fn,
        )
        actions.append({"action": "open_initiative_registered", "initiative_id": iid, "title": title})

    return actions


def llm_proposals_from_response(llm: dict) -> list[dict]:
    out: list[dict] = []
    for idea in llm.get("unstick_ideas") or []:
        if isinstance(idea, dict) and idea.get("idea"):
            out.append({
                "kind": "llm_unstick",
                "detail": idea.get("idea"),
                "suggested": idea.get("rationale"),
            })
    rec = llm.get("delegate_recommendation")
    if isinstance(rec, dict) and rec.get("task_id"):
        out.append({
            "kind": "llm_delegate",
            "task_id": rec.get("task_id"),
            "detail": rec.get("rationale"),
        })
    init = llm.get("open_initiative")
    if isinstance(init, dict) and init.get("initiative_id"):
        out.append({
            "kind": "llm_open_initiative",
            "task_id": init.get("initiative_id"),
            "detail": init.get("title"),
            "suggested": init.get("why_now"),
            "est_cost": init.get("est_cost_usd"),
        })
    for item in llm.get("nick_attention") or []:
        if item:
            out.append({"kind": "llm_nick_attention", "detail": str(item)[:200]})
    return out


def run_llm_reflect(
    ctx: dict,
    bottlenecks: list[dict],
    admission: dict,
    proposals: list[dict],
    *,
    force: bool = False,
    dry_run: bool = False,
    append_fn: Callable[[dict], bool] | None = None,
) -> dict:
    ok, reason = should_run_llm(force=force)
    result: dict[str, Any] = {
        "enabled": llm_enabled(),
        "ran": False,
        "skip_reason": reason,
        "execute": llm_execute_enabled(),
    }
    if not ok:
        return result

    payload = _compact_context(ctx, bottlenecks, admission, proposals)
    if dry_run:
        result["ran"] = True
        result["dry_run"] = True
        result["payload_keys"] = list(payload.keys())
        return result

    llm, meta = call_openrouter(payload)
    result["meta"] = meta
    result["ran"] = True
    if not llm:
        return result

    result["reflection"] = llm
    result["llm_proposals"] = llm_proposals_from_response(llm)
    if append_fn:
        cost = float(meta.get("cost_usd") or 0)
        import pmo_dispatch as pd  # noqa: E402

        pd.append_ledger(
            {
                **(ctx.get("ledger_base") or {}),
                "actor": "CEO",
                "role": "Chief Executive Officer",
                "event": "ceo_reflect_llm",
                "task_id": "FOCUS-001",
                "focus_task_id": "SYS-002",
                "task": "CEO LLM reflection",
                "status": "completed",
                "owner": "CEO",
                "model": meta.get("model"),
                "cost_usd": cost,
                "output": f"{MARKER}{(llm.get('situation_summary') or '')[:240]}",
                "artifacts": ["memos/ceo-reflect/latest.md"],
            },
            append_fn,
        )
    result["actions"] = apply_llm_actions(
        llm, ctx, admission, append_fn=append_fn, dry_run=dry_run
    )

    state = load_state()
    state["last_llm_at"] = _now()
    state["last_model"] = meta.get("model")
    save_state(state)
    return result