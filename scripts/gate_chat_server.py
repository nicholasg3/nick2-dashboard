#!/usr/bin/env python3
"""Local gate-chat bridge: Nick messages → agent reply → logs/gate-chats/*.jsonl + ledger.

Run on your Mac or droplet (not GitHub Pages):

  python3 scripts/gate_chat_server.py
  # set dashboard/config.json gateChatApi to http://YOUR_HOST:8787

Env:
  GATE_CHAT_PORT — default 8787
  GATE_AGENT_CMD — optional shell command; receives task_id and message on stdin JSON
  NICK2_ROOT — repo root (default: parent of scripts/)
"""
from __future__ import annotations

import json
import os
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
PORT = int(os.environ.get("GATE_CHAT_PORT", "8787"))


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


def load_gate_meta(task_id: str) -> dict:
    briefs = ROOT / "reports" / "gate-briefs.json"
    if briefs.exists():
        data = json.loads(briefs.read_text(encoding="utf-8"))
        if task_id in data:
            return data[task_id]
    return {"task_id": task_id, "title": task_id}


def agent_reply(task_id: str, nick_text: str) -> str:
    cmd = os.environ.get("GATE_AGENT_CMD", "").strip()
    meta = load_gate_meta(task_id)
    if cmd:
        payload = json.dumps({"task_id": task_id, "message": nick_text, "brief": meta})
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                input=payload,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT),
            )
            out = (r.stdout or r.stderr or "").strip()
            if out:
                return out[:4000]
        except Exception as e:
            return f"Agent hook failed ({e}). Message logged — COO will pick up on reconcile."

    title = meta.get("title", task_id)
    return (
        f"Recorded your instruction for **{task_id}** ({title}).\n\n"
        f"I'll append `nick_gate_instruction` to the ledger and execute: "
        f"\"{nick_text[:300]}\"\n\n"
        f"Ungated work continues. Reply here when the gate is cleared or you need more from Nick."
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
            self._json(200, {"ok": True, "service": "nick2-gate-chat"})
            return
        if path.startswith("/api/gate/") and path.endswith("/messages"):
            task_id = path.split("/")[3]
            chat_path = CHATS / f"{task_id}.jsonl"
            msgs = []
            if chat_path.exists():
                for line in chat_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        msgs.append(json.loads(line))
            self._json(200, {"messages": msgs})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
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

        reply = agent_reply(task_id, text)
        agent_msg = {
            "ts": now_sgt(),
            "role": "agent",
            "actor": "CEO",
            "task_id": task_id,
            "text": reply,
        }
        append_jsonl(CHATS / f"{task_id}.jsonl", agent_msg)

        self._json(200, {"ok": True, "reply": reply})


def main() -> None:
    CHATS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"gate-chat server on http://0.0.0.0:{PORT}")
    print(f"  chats: {CHATS}")
    print(f"  ledger: {LEDGER}")
    print("Set dashboard/config.json gateChatApi to this URL for live chat.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()