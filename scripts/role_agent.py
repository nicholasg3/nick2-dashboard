#!/usr/bin/env python3
"""Talkable CEO/COO/PMO role responder for the Nick2 live dashboard.

This is not the full autonomous orchestrator. It is the first honest, useful
role-chat loop: the live dashboard sends a role message, this script gathers the
current operating context, asks a cheap OpenRouter model when available, and
returns a concise executive reply.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
HERMES_ENV = Path(os.environ.get("HERMES_ENV", Path.home() / ".hermes" / ".env"))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("ROLE_AGENT_MODEL", "openai/gpt-4.1-mini")

LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
REPORTS = ROOT / "reports"
CEO_MEMO = ROOT / "memos" / "ceo-reflect" / "latest.md"

ROLE_DEFS = {
    "ceo": {
        "name": "CEO",
        "title": "CEO Office",
        "brief": (
            "You are the CEO of Nick2. Give Nick a truthful operating read, name the "
            "highest-leverage next move, and distinguish what is running from what is only planned."
        ),
    },
    "coo": {
        "name": "COO",
        "title": "COO Office",
        "brief": (
            "You are the COO of Nick2. Focus on execution state, handoffs, stuck work, "
            "services, and what should be reconciled next."
        ),
    },
    "pmo": {
        "name": "PMO",
        "title": "PMO Office",
        "brief": (
            "You are the PMO of Nick2. Focus on backlog order, issue triage, worker "
            "dispatch readiness, gates, and evidence required before closing work."
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


def _read_text(path: Path, limit: int = 4000) -> str:
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            return text[-limit:]
    except OSError:
        pass
    return ""


def _ledger_tail(limit: int = 30) -> list[dict]:
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


def _load_env_key() -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    if not HERMES_ENV.is_file():
        return ""
    for line in HERMES_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "OPENROUTER_API_KEY":
            return value.strip().strip('"').strip("'")
    return ""


def build_context(role: str, message: str, history: list[dict]) -> dict:
    return {
        "ts": _now(),
        "role": role,
        "message": message,
        "recent_chat": [
            {
                "actor": h.get("actor") or h.get("role"),
                "text": (h.get("text") or "")[:500],
                "ts": h.get("ts"),
            }
            for h in history[-12:]
        ],
        "bus_live": _read_json(REPORTS / "bus-live.json", {}),
        "ceo_queue": _read_json(REPORTS / "ceo-queue.json", {}),
        "org_fleet": _read_json(REPORTS / "org-fleet.json", {}),
        "orchestrator": _read_json(REPORTS / "orchestrator" / "status.json", {}),
        "gated": _read_json(REPORTS / "gated.json", []),
        "ceo_reflect_latest": _read_text(CEO_MEMO),
        "ledger_tail": _ledger_tail(),
    }


def fallback_reply(role: str, ctx: dict) -> str:
    role_name = ROLE_DEFS.get(role, ROLE_DEFS["ceo"])["name"]
    bus = ctx.get("bus_live") or {}
    running = len(bus.get("running") or [])
    held = len(bus.get("held") or [])
    queued = len(bus.get("queued") or [])
    gates = ctx.get("gated") or []
    memo = (ctx.get("ceo_reflect_latest") or "").strip()
    memo_line = "No CEO reflection memo is loaded."
    for line in memo.splitlines():
        stripped = line.strip("# -")
        if stripped and "CEO reflection" not in stripped:
            memo_line = stripped[:240]
            break
    return (
        f"{role_name} office is reachable, but OpenRouter is not available for a fresh "
        f"model reply right now.\n\n"
        f"Current mechanical read: {running} running, {held} held, {queued} queued; "
        f"{len(gates)} Nick gate(s). Latest memo signal: {memo_line}\n\n"
        "I can still record instructions here; the next LLM-backed pass will have this chat "
        "history and the ledger context."
    )


def call_model(role: str, ctx: dict) -> str | None:
    key = _load_env_key()
    if not key:
        return None
    role_def = ROLE_DEFS.get(role, ROLE_DEFS["ceo"])
    system = (
        f"{role_def['brief']}\n"
        "Be concise, specific, and honest. If something is not running, say so. "
        "Do not claim commits, services, or worker state unless present in context. "
        "Reply directly to Nick in 3-7 short bullets or paragraphs. "
        "If Nick is asking for action, say the next concrete step and whether it needs approval."
    )
    body = {
        "model": os.environ.get(f"{role.upper()}_ROLE_MODEL", DEFAULT_MODEL),
        "temperature": 0.25,
        "max_tokens": int(os.environ.get("ROLE_AGENT_MAX_TOKENS", "900")),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(ctx, ensure_ascii=False, indent=2)},
        ],
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://github.com/nicholasg3/nick2-dashboard",
            "X-Title": "nick2-role-office",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.load(resp)
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return content.strip() or None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        return f"Model call failed: {str(e)[:240]}\n\n{fallback_reply(role, ctx)}"


def reply(role: str, message: str, history: list[dict] | None = None) -> str:
    role_key = role if role in ROLE_DEFS else "ceo"
    ctx = build_context(role_key, message, history or [])
    return call_model(role_key, ctx) or fallback_reply(role_key, ctx)


def selftest() -> None:
    ctx = build_context("ceo", "What is going on?", [])
    out = fallback_reply("ceo", ctx)
    assert "CEO" in out or "running" in out or "Model call failed" in out
    assert build_context("pmo", "hello", [])["role"] == "pmo"
    print("role_agent selftest OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Nick2 role chat responder")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
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
