#!/usr/bin/env python3
"""Gate-chat bridge: Nick messages → agent-bus worker → ledger + dashboard refresh.

Run on droplet (not GitHub Pages):

  python3 scripts/gate_chat_server.py
  # expose via tailscale funnel or reverse proxy; set dashboard/config.json gateChatApi

Env:
  GATE_CHAT_PORT — default 8788 (8787 is telegram-bridge)
  GATE_AGENT_CMD — default: python3 scripts/gate_agent_bus.py
  NICK2_ROOT — repo root
  AGENT_BUS_ROOT — path to agent-bus
  GATE_SKIP_GIT_PUSH — set 1 to skip auto-push after resolve
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
CHATS = ROOT / "logs" / "gate-chats"
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
SGT = timezone(timedelta(hours=8))
PORT = int(os.environ.get("GATE_CHAT_PORT", "8788"))
DEFAULT_AGENT = f"python3 {ROOT / 'scripts' / 'gate_agent_bus.py'}"


def now_sgt() -> str:
    return datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    prefix = ""
    if path.exists() and path.stat().st_size > 0:
        raw = path.read_bytes()
        if not raw.endswith(b"\n"):
            prefix = "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")


def append_ledger(event: dict) -> None:
    if "ts" not in event:
        event["ts"] = now_sgt()
    append_jsonl(LEDGER, event)


def load_events() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def is_resolved(task_id: str) -> bool:
    for ev in reversed(load_events()):
        if ev.get("task_id") == task_id and ev.get("event") in (
            "decision_resolved",
            "nick_gate_resolved",
        ):
            return True
    return False


def load_gate_meta(task_id: str) -> dict:
    briefs = ROOT / "reports" / "gate-briefs.json"
    if briefs.exists():
        data = json.loads(briefs.read_text(encoding="utf-8"))
        if task_id in data:
            return data[task_id]
    return {"task_id": task_id, "title": task_id}


def load_messages(task_id: str) -> list[dict]:
    chat_path = CHATS / f"{task_id}.jsonl"
    msgs = []
    if chat_path.exists():
        for line in chat_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                msgs.append(json.loads(line))
    return msgs


def looks_resolved(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if t.startswith("[gate cleared]"):
        return True
    if re.search(r"\b(clear(ed)?|resolve(d)?)\b.*\bgate\b", t):
        return True
    if re.search(r"\b(approve|approved|approve-with-weights|defer|deferred|reject|rejected)\b", t):
        return True
    return False


def refresh_reports() -> None:
    script = ROOT / "scripts" / "export-json-reports.py"
    if script.is_file():
        subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )


def push_dashboard() -> str | None:
    if os.environ.get("GATE_SKIP_GIT_PUSH", "").strip() in ("1", "true", "yes"):
        return "git push skipped (GATE_SKIP_GIT_PUSH)"
    try:
        subprocess.run(["git", "add", "logs/ceo-ledger.jsonl", "reports/gated.json"], cwd=str(ROOT), check=True)
        chat_glob = list(CHATS.glob("*.jsonl"))
        if chat_glob:
            subprocess.run(["git", "add", "logs/gate-chats/"], cwd=str(ROOT), check=True)
        msg = f"gate-bridge: update ledger and gated queue ({now_sgt()})"
        r = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr):
            return "no git changes"
        subprocess.run(["git", "push", "origin", "main"], cwd=str(ROOT), check=True, timeout=120)
        return "pushed to origin/main"
    except Exception as e:
        return f"git push failed: {e}"


def resolve_gate(task_id: str, note: str, actor: str = "Nicholas") -> dict:
    meta = load_gate_meta(task_id)
    title = meta.get("title") or task_id
    events = []
    if task_id.startswith("DEC-"):
        events.append(
            {
                "actor": actor,
                "role": "Owner",
                "event": "decision_resolved",
                "task_id": task_id,
                "task": title,
                "status": "completed",
                "output": note,
                "resolved_by": actor,
                "needs_nicholas": False,
                "gated_by_nick": False,
            }
        )
    events.append(
        {
            "actor": actor,
            "role": "Owner",
            "event": "nick_gate_resolved",
            "task_id": task_id,
            "task": title,
            "status": "completed",
            "output": note,
            "resolved_by": actor,
            "needs_nicholas": False,
            "gated_by_nick": False,
        }
    )
    for ev in events:
        append_ledger(ev)
    refresh_reports()
    git_note = push_dashboard()
    return {"resolved": True, "task_id": task_id, "git": git_note}


def agent_reply(task_id: str, nick_text: str) -> str:
    cmd = os.environ.get("GATE_AGENT_CMD", DEFAULT_AGENT).strip() or DEFAULT_AGENT
    meta = load_gate_meta(task_id)
    history = load_messages(task_id)
    payload = json.dumps(
        {"task_id": task_id, "message": nick_text, "brief": meta, "history": history[-30:]}
    )
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            input=payload,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
            env={**os.environ, "NICK2_ROOT": str(ROOT)},
        )
        out = (r.stdout or r.stderr or "").strip()
        if out:
            return out[:4000]
    except Exception as e:
        return f"Agent dispatch failed ({e}). Message logged — COO will pick up on reconcile."

    title = meta.get("title", task_id)
    return (
        f"Recorded your instruction for **{task_id}** ({title}).\n\n"
        f"\"{nick_text[:300]}\""
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[gate-chat] {self.address_string()} {fmt % args}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, body: dict):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(200, {"ok": True, "service": "nick2-gate-chat", "port": PORT})
            return
        if path.startswith("/api/gate/") and path.endswith("/messages"):
            task_id = path.split("/")[3]
            self._json(
                200,
                {"messages": load_messages(task_id), "resolved": is_resolved(task_id)},
            )
            return
        if path.startswith("/api/gate/") and path.endswith("/status"):
            task_id = path.split("/")[3]
            self._json(200, {"task_id": task_id, "resolved": is_resolved(task_id)})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/gate/") and path.endswith("/resolve"):
            task_id = path.split("/")[3]
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            note = (body.get("note") or body.get("text") or "Gate cleared by Nicholas.").strip()
            actor = body.get("actor") or "Nicholas"
            if is_resolved(task_id):
                self._json(200, {"ok": True, "already_resolved": True, "task_id": task_id})
                return
            result = resolve_gate(task_id, note, actor)
            agent_msg = {
                "ts": now_sgt(),
                "role": "agent",
                "actor": "CEO",
                "task_id": task_id,
                "text": f"Gate **{task_id}** cleared. Queue updated; {result.get('git', 'reports refreshed')}.",
            }
            append_jsonl(CHATS / f"{task_id}.jsonl", agent_msg)
            self._json(200, {"ok": True, **result})
            return

        if not path.startswith("/api/gate/") or not path.endswith("/message"):
            self._json(404, {"error": "not found"})
            return

        task_id = path.split("/")[3]
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        text = (body.get("text") or "").strip()
        if not text:
            self._json(400, {"error": "text required"})
            return
        actor = body.get("actor") or "Nicholas"
        ts = now_sgt()

        nick_msg = {"ts": ts, "role": "nick", "actor": actor, "task_id": task_id, "text": text}
        append_jsonl(CHATS / f"{task_id}.jsonl", nick_msg)
        append_ledger(
            {
                "actor": actor,
                "role": "Owner",
                "event": "nick_gate_instruction",
                "task_id": task_id,
                "task": load_gate_meta(task_id).get("title", task_id),
                "status": "awaiting_nicholas",
                "output": text,
                "needs_nicholas": False,
                "gated_by_nick": True,
            }
        )

        resolved_payload = None
        if looks_resolved(text) and not is_resolved(task_id):
            resolved_payload = resolve_gate(task_id, text, actor)

        reply = agent_reply(task_id, text)
        if resolved_payload:
            reply += f"\n\n✓ Gate cleared — dashboard queue will refresh ({resolved_payload.get('git', 'ok')})."

        agent_msg = {
            "ts": now_sgt(),
            "role": "agent",
            "actor": "CEO",
            "task_id": task_id,
            "text": reply,
        }
        append_jsonl(CHATS / f"{task_id}.jsonl", agent_msg)

        self._json(
            200,
            {
                "ok": True,
                "reply": reply,
                "resolved": bool(resolved_payload),
                "task_id": task_id,
            },
        )


def main() -> None:
    CHATS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"gate-chat server on http://0.0.0.0:{PORT}")
    print(f"  chats: {CHATS}")
    print(f"  ledger: {LEDGER}")
    print(f"  agent: {os.environ.get('GATE_AGENT_CMD', DEFAULT_AGENT)}")
    print("Expose via tailscale funnel; set dashboard/config.json gateChatApi to the HTTPS URL.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()