#!/usr/bin/env python3
"""Talkable CEO/COO/PMO role responder for the Nick2 live dashboard.

Each role maintains a PERSISTENT Claude CLI session (claude --resume <session_id>)
so conversations have genuine continuity — Nick can ask follow-up questions and
the agent remembers what was said. Session IDs are stored in
nick2-dashboard/sessions/role-<role>.json and survive server restarts.

On the first message the agent receives a rich system prompt (injected as a
user-turn preamble) describing its role and the live dashboard context.
Subsequent turns get a compact context refresh + the new message, so the model
always has current data without re-reading the full prompt each time.

Falls back to a stateless OpenRouter call if the Claude CLI is not available.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
HERMES_ENV = Path(os.environ.get("HERMES_ENV", Path.home() / ".hermes" / ".env"))
SESSIONS_DIR = ROOT / "sessions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OR_MODEL = os.environ.get("ROLE_AGENT_MODEL", "openai/gpt-4.1-mini")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")

LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
REPORTS = ROOT / "reports"
CEO_MEMO = ROOT / "memos" / "ceo-reflect" / "latest.md"

ROLE_DEFS = {
    "ceo": {
        "name": "CEO",
        "title": "CEO Office",
        "brief": (
            "You are the CEO of Nick2, Nick Garcia's AI-agent workspace. "
            "You have a persistent memory of your conversations with Nick. "
            "Give truthful operating reads, name the highest-leverage next move, "
            "and clearly distinguish what is actually running from what is only planned. "
            "You remember what Nick told you in previous messages in this session."
        ),
    },
    "coo": {
        "name": "COO",
        "title": "COO Office",
        "brief": (
            "You are the COO of Nick2. You remember prior conversations with Nick. "
            "Focus on execution state, stuck work, service health, and handoffs. "
            "Tell Nick what needs to be reconciled or unblocked."
        ),
    },
    "pmo": {
        "name": "PMO",
        "title": "PMO Office",
        "brief": (
            "You are the PMO of Nick2. You remember prior conversations with Nick. "
            "Focus on backlog order, issue triage, dispatch readiness, gates, "
            "and evidence required before closing work."
        ),
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _read_text(path: Path, limit: int = 3000) -> str:
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            return text[-limit:]
    except OSError:
        pass
    return ""


def _ledger_tail(limit: int = 20) -> list[dict]:
    if not LEDGER.is_file():
        return []
    out: list[dict] = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_session(role: str) -> str | None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"role-{role}.json"
    data = _read_json(path, {})
    return data.get("session_id") or None


def _save_session(role: str, session_id: str) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"role-{role}.json"
    path.write_text(json.dumps({"role": role, "session_id": session_id, "updated": _now()},
                               indent=2), encoding="utf-8")


def _load_or_key() -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    if not HERMES_ENV.is_file():
        return ""
    for line in HERMES_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == "OPENROUTER_API_KEY":
            return v.strip().strip('"').strip("'")
    return ""


def _context_snapshot() -> dict:
    """Current dashboard state — injected into every turn so the agent is grounded."""
    return {
        "ts": _now(),
        "bus_live": _read_json(REPORTS / "bus-live.json", {}),
        "ceo_queue": _read_json(REPORTS / "ceo-queue.json", {}),
        "org_fleet": _read_json(REPORTS / "org-fleet.json", {}),
        "orchestrator": _read_json(REPORTS / "orchestrator" / "status.json", {}),
        "gated": _read_json(REPORTS / "gated.json", []),
        "ceo_reflect_latest": _read_text(CEO_MEMO),
        "ledger_tail": _ledger_tail(),
    }


def _build_prompt(role: str, message: str, is_first_turn: bool) -> str:
    """Build the user-turn prompt.

    First turn: full system brief + context + message (establishes the persona).
    Subsequent turns: compact context refresh + message (keeps data current cheaply).
    """
    role_def = ROLE_DEFS.get(role, ROLE_DEFS["ceo"])
    ctx = _context_snapshot()
    ctx_json = json.dumps(ctx, ensure_ascii=False, indent=2)

    if is_first_turn:
        return (
            f"[SYSTEM — read this once, then remember it for all future turns]\n"
            f"Role: {role_def['brief']}\n"
            f"Instructions: Be concise and specific. Reply in 3-7 bullets or short paragraphs. "
            f"Never claim something is running unless it appears in the context data. "
            f"When Nick asks for action, state the next concrete step and whether it needs his approval.\n\n"
            f"[LIVE DASHBOARD CONTEXT — {ctx['ts']}]\n{ctx_json}\n\n"
            f"[NICK'S MESSAGE]\n{message}"
        )
    else:
        # Compact refresh: just the parts that change frequently
        compact = {
            "ts": ctx["ts"],
            "bus_live": ctx["bus_live"],
            "ledger_tail": ctx["ledger_tail"][-10:],
            "gated": ctx["gated"],
        }
        return (
            f"[CONTEXT REFRESH — {ctx['ts']}]\n"
            f"{json.dumps(compact, ensure_ascii=False, indent=2)}\n\n"
            f"[NICK'S MESSAGE]\n{message}"
        )


def call_claude_persistent(role: str, message: str) -> tuple[str, str | None]:
    """Call claude --resume for persistent session. Returns (reply_text, new_session_id)."""
    session_id = _load_session(role)
    is_first_turn = session_id is None

    prompt = _build_prompt(role, message, is_first_turn)

    cmd = [CLAUDE_BIN, "-p", "--output-format", "json", "--permission-mode", "bypassPermissions"]
    if session_id:
        cmd += ["--resume", session_id]
    cmd += [prompt]

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "")[:500]
            return f"Claude session error (rc={r.returncode}): {err}", None

        data = json.loads((r.stdout or "").strip())
        new_sid = data.get("session_id")
        result = str(data.get("result") or data.get("text") or "").strip()

        if data.get("is_error"):
            return f"Claude in-band error: {result[:300]}", None

        if new_sid:
            _save_session(role, new_sid)

        return result or "(empty response)", new_sid

    except subprocess.TimeoutExpired:
        return "Role office timed out (>120s). Try again.", None
    except (json.JSONDecodeError, OSError) as e:
        return f"Claude CLI error: {e}", None


def call_openrouter_fallback(role: str, message: str, history: list[dict]) -> str:
    """Stateless OpenRouter fallback — no continuity, but always available."""
    import urllib.error
    import urllib.request

    key = _load_or_key()
    if not key:
        return fallback_reply(role)

    role_def = ROLE_DEFS.get(role, ROLE_DEFS["ceo"])
    ctx = _context_snapshot()
    messages = [
        {"role": "system", "content": role_def["brief"] + "\nBe concise. Reply in 3-7 bullets."},
    ]
    for h in history[-12:]:
        actor = (h.get("actor") or h.get("role") or "").lower()
        messages.append({
            "role": "assistant" if actor != "nicholas" else "user",
            "content": (h.get("text") or "")[:600],
        })
    messages.append({"role": "user", "content": f"Context: {json.dumps(ctx)}\n\nMessage: {message}"})

    body = {"model": DEFAULT_OR_MODEL, "temperature": 0.25, "max_tokens": 900, "messages": messages}
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                 "HTTP-Referer": "https://github.com/nicholasg3/nick2-dashboard"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.load(resp)
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return content.strip() or fallback_reply(role)
    except Exception as e:
        return f"Model call failed: {str(e)[:200]}\n\n{fallback_reply(role)}"


def fallback_reply(role: str) -> str:
    role_name = ROLE_DEFS.get(role, ROLE_DEFS["ceo"])["name"]
    bus = _read_json(REPORTS / "bus-live.json", {})
    running = len(bus.get("running") or [])
    held = len(bus.get("held") or [])
    queued = len(bus.get("queued") or [])
    return (
        f"{role_name} office is reachable but the model is unavailable right now. "
        f"Mechanical read: {running} running, {held} held, {queued} queued. "
        "Your message has been logged and will be in context on the next live pass."
    )


def reply(role: str, message: str, history: list[dict] | None = None) -> str:
    role_key = role if role in ROLE_DEFS else "ceo"
    text, _ = call_claude_persistent(role_key, message)
    if text and not text.startswith("Claude session error") and not text.startswith("Claude CLI error"):
        return text
    # Fallback to OpenRouter if Claude CLI fails
    return call_openrouter_fallback(role_key, message, history or [])


def selftest() -> None:
    assert _build_prompt("ceo", "hello", True).startswith("[SYSTEM")
    assert _build_prompt("ceo", "hello", False).startswith("[CONTEXT REFRESH")
    assert ROLE_DEFS["pmo"]["name"] == "PMO"
    print("role_agent selftest OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Nick2 role chat responder")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--reset-session", metavar="ROLE", help="Clear stored session for role")
    args = parser.parse_args()

    if args.selftest:
        selftest()
        return 0

    if args.reset_session:
        path = SESSIONS_DIR / f"role-{args.reset_session.lower()}.json"
        if path.exists():
            path.unlink()
            print(f"Session cleared for {args.reset_session}")
        else:
            print(f"No session file found for {args.reset_session}")
        return 0

    raw = sys.stdin.read()
    if not raw.strip():
        print("No role payload on stdin.", file=sys.stderr)
        return 1
    payload = json.loads(raw)
    role = (payload.get("role") or "ceo").lower()
    message = (payload.get("message") or "").strip()
    history = payload.get("history") or []
    if not message:
        print("Message required.", file=sys.stderr)
        return 1
    print(reply(role, message, history))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
