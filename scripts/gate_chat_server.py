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
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import work_queue_ops as wqo  # noqa: E402

DASHBOARD = ROOT / "dashboard"
CHATS = ROOT / "logs" / "gate-chats"
WORK_CHATS = ROOT / "logs" / "work-chats"
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
REPORTS = ROOT / "reports"
SGT = timezone(timedelta(hours=8))
PORT = int(os.environ.get("GATE_CHAT_PORT", "8788"))
BUS_LIVE_MAX_AGE_SEC = int(os.environ.get("BUS_LIVE_MAX_AGE_SEC", "30"))
DEFAULT_AGENT = f"python3 {ROOT / 'scripts' / 'gate_agent_bus.py'}"
DEFAULT_WORK_AGENT = f"python3 {ROOT / 'scripts' / 'work_agent_bus.py'}"
DEFAULT_ROLE_AGENT = f"python3 {ROOT / 'scripts' / 'role_agent.py'}"
ROLE_CHATS = ROOT / "logs" / "role-chats"
ROLE_META = {
    "ceo": {
        "role": "ceo",
        "title": "CEO Office",
        "owner": "CEO",
        "status": "live",
        "summary": "Talk to the executive supervisor about focus, bottlenecks, gates, and next moves.",
    },
    "coo": {
        "role": "coo",
        "title": "COO Office",
        "owner": "COO",
        "status": "live",
        "summary": "Talk to operations about execution state, stuck work, services, and handoffs.",
    },
    "pmo": {
        "role": "pmo",
        "title": "PMO Office",
        "owner": "PMO",
        "status": "live",
        "summary": "Talk to PMO about backlog order, dispatch readiness, and evidence before closing work.",
    },
}

LIVE_FILES = {
    "/api/live/ledger": (LEDGER, "text/plain; charset=utf-8"),
    "/api/live/bus-live": (REPORTS / "bus-live.json", "application/json"),
    "/api/live/org-fleet": (REPORTS / "org-fleet.json", "application/json"),
    "/api/live/gated": (REPORTS / "gated.json", "application/json"),
    "/api/live/ceo-queue": (REPORTS / "ceo-queue.json", "application/json"),
    "/api/live/gate-briefs": (REPORTS / "gate-briefs.json", "application/json"),
    "/api/live/orchestrator": (REPORTS / "orchestrator" / "status.json", "application/json"),
}

STATIC_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".jsonl": "text/plain; charset=utf-8",
}


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


def read_json(path: Path, default):
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def compact_orchestrator_status() -> dict:
    data = read_json(REPORTS / "orchestrator" / "status.json", {})
    return {
        k: data.get(k)
        for k in ("ts", "mode", "reason", "healthy", "last_tick_at", "summary")
        if k in data
    }


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


def load_messages(task_id: str, *, work: bool = False) -> list[dict]:
    chat_path = (WORK_CHATS if work else CHATS) / f"{task_id}.jsonl"
    msgs = []
    if chat_path.exists():
        for line in chat_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                msgs.append(json.loads(line))
    return msgs


def load_role_messages(role: str) -> list[dict]:
    role_key = role if role in ROLE_META else "ceo"
    chat_path = ROLE_CHATS / f"{role_key}.jsonl"
    msgs = []
    if chat_path.exists():
        for line in chat_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                msgs.append(json.loads(line))
    return msgs


def load_role_meta(role: str) -> dict:
    role_key = role if role in ROLE_META else "ceo"
    meta = dict(ROLE_META[role_key])
    meta["messages"] = len(load_role_messages(role_key))
    meta["orchestrator"] = compact_orchestrator_status()
    return meta


def load_task_meta(task_id: str) -> dict:
    """Latest ledger row for an active-work task."""
    meta = {"task_id": task_id, "task": task_id, "owner": "PMO", "status": "in_progress"}
    focus_id = None
    for ev in load_events():
        if ev.get("task_id") == task_id:
            meta = {**meta, **ev}
        if ev.get("event") in ("focus_snapshot", "ceo_focus") and ev.get("focus_task_id"):
            if task_id in ("FOCUS-001", ev.get("task_id", "")):
                focus_id = ev.get("focus_task_id")
    if focus_id:
        meta["memo_task_id"] = focus_id
        for ev in reversed(load_events()):
            if ev.get("task_id") == focus_id:
                meta["focus_mission"] = ev.get("task") or focus_id
                break
    if "memo_task_id" not in meta:
        meta["memo_task_id"] = task_id
    return meta


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


def ensure_bus_live_fresh(*, force: bool = False) -> None:
    """Refresh bus-live.json from agent-bus (every live API read, or when stale on disk)."""
    out = REPORTS / "bus-live.json"
    script = ROOT / "scripts" / "export_bus_live.py"
    if not script.is_file():
        return
    age_sec = None
    if out.exists():
        age_sec = datetime.now(timezone.utc).timestamp() - out.stat().st_mtime
    if not force and age_sec is not None and age_sec <= BUS_LIVE_MAX_AGE_SEC:
        return
    r = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        print(
            f"[gate-chat] export_bus_live failed ({r.returncode}): "
            f"{(r.stderr or r.stdout)[:400]}"
        )


def resolve_static_path(url_path: str) -> Path | None:
    """Map URL path to a file under dashboard/, logs/, reports/, or memos/."""
    clean = url_path.split("?", 1)[0]
    if clean in ("", "/"):
        return DASHBOARD / "index.html"
    rel = clean.lstrip("/")
    if rel.startswith("api/"):
        return None
    for base in (DASHBOARD, ROOT / "logs", REPORTS, ROOT / "memos"):
        sub = rel
        if base == ROOT / "memos" and sub.startswith("memos/"):
            sub = sub[len("memos/") :]
        candidate = (base / sub).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    dash = (DASHBOARD / rel).resolve()
    if dash.is_file() and str(dash).startswith(str(DASHBOARD.resolve())):
        return dash
    return None


def push_dashboard() -> str | None:
    if os.environ.get("GATE_SKIP_GIT_PUSH", "").strip() in ("1", "true", "yes"):
        return "git push skipped (GATE_SKIP_GIT_PUSH)"
    try:
        subprocess.run(["git", "add", "logs/ceo-ledger.jsonl", "reports/gated.json"], cwd=str(ROOT), check=True)
        if list(CHATS.glob("*.jsonl")):
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
        pull = subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if pull.returncode != 0:
            return f"git pull --rebase failed: {(pull.stderr or pull.stdout)[:300]}"
        push = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if push.returncode != 0:
            return f"git push failed: {(push.stderr or push.stdout)[:300]}"
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


def work_agent_reply(task_id: str, nick_text: str, meta: dict) -> str:
    cmd = os.environ.get("WORK_AGENT_CMD", DEFAULT_WORK_AGENT).strip() or DEFAULT_WORK_AGENT
    history = load_messages(task_id, work=True)
    payload = json.dumps(
        {
            "task_id": task_id,
            "message": nick_text,
            "meta": meta,
            "history": history[-30:],
        }
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
        return f"Agent dispatch failed ({e}). Message logged — worker will pick up on reconcile."

    title = meta.get("task") or task_id
    return (
        f"Recorded your instruction for **{task_id}** ({title}).\n\n"
        f"\"{nick_text[:300]}\""
    )


def role_agent_reply(role: str, nick_text: str) -> str:
    role_key = role if role in ROLE_META else "ceo"
    cmd = os.environ.get("ROLE_AGENT_CMD", DEFAULT_ROLE_AGENT).strip() or DEFAULT_ROLE_AGENT
    history = load_role_messages(role_key)
    payload = json.dumps(
        {
            "role": role_key,
            "message": nick_text,
            "history": history[-30:],
        }
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
            return out[:5000]
    except Exception as e:
        return f"Role office failed ({e}). Message logged for the next pass."
    return f"Recorded your instruction for {ROLE_META[role_key]['title']}."


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

    def _raw(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _serve_live(self, path: str) -> bool:
        spec = LIVE_FILES.get(path)
        if not spec:
            return False
        file_path, mime = spec
        if path == "/api/live/bus-live":
            ensure_bus_live_fresh(force=True)
        if path == "/api/live/org-fleet":
            refresh_reports()
        if not file_path.exists():
            empty = b"[]" if mime == "application/json" else b""
            self._raw(200, empty, mime)
            return True
        self._raw(200, file_path.read_bytes(), mime)
        return True

    def _serve_static(self, url_path: str) -> bool:
        file_path = resolve_static_path(url_path)
        if not file_path:
            return False
        mime = STATIC_MIME.get(file_path.suffix.lower(), "application/octet-stream")
        self._raw(200, file_path.read_bytes(), mime)
        return True

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "service": "nick2-gate-chat",
                    "port": PORT,
                    "live": list(LIVE_FILES.keys()),
                    "role_chat": list(ROLE_META.keys()),
                    "root": str(ROOT),
                },
            )
            return
        if self._serve_live(path):
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
        if path.startswith("/api/work/") and path.endswith("/meta"):
            task_id = path.split("/")[3]
            self._json(200, load_task_meta(task_id))
            return
        if path.startswith("/api/work/") and path.endswith("/messages"):
            task_id = path.split("/")[3]
            self._json(200, {"messages": load_messages(task_id, work=True)})
            return
        if path.startswith("/api/role/") and path.endswith("/meta"):
            role = path.split("/")[3].lower()
            self._json(200, load_role_meta(role))
            return
        if path.startswith("/api/role/") and path.endswith("/messages"):
            role = path.split("/")[3].lower()
            self._json(200, {"messages": load_role_messages(role)})
            return
        if self._serve_static(self.path):
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

        if path.startswith("/api/work/") and path.endswith("/message"):
            task_id = path.split("/")[3]
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            text = (body.get("text") or "").strip()
            if not text:
                self._json(400, {"error": "text required"})
                return
            actor = body.get("actor") or "Nicholas"
            meta = load_task_meta(task_id)
            nick_msg = {
                "ts": now_sgt(),
                "role": "nick",
                "actor": actor,
                "task_id": task_id,
                "text": text,
            }
            append_jsonl(WORK_CHATS / f"{task_id}.jsonl", nick_msg)
            if wqo.looks_remove_instruction(text):
                result = wqo.remove_from_active_queue(task_id, text, actor=actor)
                reply = (
                    f"Removed **{task_id}** from the active work queue "
                    f"(status → idle). Bus packets superseded where applicable.\n\n"
                    f"Nick: \"{text[:280]}\""
                )
                if result.get("deferred"):
                    reply += "\n\nThis item stays decision-gated / Nick's queue — not agent work."
            else:
                append_ledger(
                    {
                        "actor": actor,
                        "role": "Owner",
                        "event": "nick_work_instruction",
                        "task_id": task_id,
                        "task": meta.get("task", task_id),
                        "status": meta.get("status", "in_progress"),
                        "owner": meta.get("owner") or meta.get("actor"),
                        "output": text,
                        "needs_nicholas": False,
                    }
                )
                reply = work_agent_reply(task_id, text, meta)
            agent_msg = {
                "ts": now_sgt(),
                "role": "agent",
                "actor": meta.get("owner") or "Agent",
                "task_id": task_id,
                "text": reply,
            }
            append_jsonl(WORK_CHATS / f"{task_id}.jsonl", agent_msg)
            self._json(200, {"ok": True, "reply": reply, "task_id": task_id})
            return

        if path.startswith("/api/role/") and path.endswith("/message"):
            role = path.split("/")[3].lower()
            role_key = role if role in ROLE_META else "ceo"
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            text = (body.get("text") or "").strip()
            if not text:
                self._json(400, {"error": "text required"})
                return
            actor = body.get("actor") or "Nicholas"
            nick_msg = {
                "ts": now_sgt(),
                "role": "nick",
                "actor": actor,
                "task_id": f"ROLE-{role_key.upper()}",
                "text": text,
            }
            append_jsonl(ROLE_CHATS / f"{role_key}.jsonl", nick_msg)
            append_ledger(
                {
                    "actor": actor,
                    "role": "Owner",
                    "event": "role_chat_instruction",
                    "task_id": f"ROLE-{role_key.upper()}",
                    "task": f"Talk with {ROLE_META[role_key]['title']}",
                    "status": "in_progress",
                    "owner": ROLE_META[role_key]["owner"],
                    "output": text,
                    "needs_nicholas": False,
                }
            )
            reply = role_agent_reply(role_key, text)
            agent_msg = {
                "ts": now_sgt(),
                "role": "agent",
                "actor": ROLE_META[role_key]["owner"],
                "task_id": f"ROLE-{role_key.upper()}",
                "text": reply,
            }
            append_jsonl(ROLE_CHATS / f"{role_key}.jsonl", agent_msg)
            append_ledger(
                {
                    "actor": ROLE_META[role_key]["owner"],
                    "role": ROLE_META[role_key]["title"],
                    "event": "role_chat_reply",
                    "task_id": f"ROLE-{role_key.upper()}",
                    "task": f"Talk with {ROLE_META[role_key]['title']}",
                    "status": "completed",
                    "owner": ROLE_META[role_key]["owner"],
                    "output": reply[:1000],
                    "needs_nicholas": False,
                }
            )
            refresh_reports()
            self._json(200, {"ok": True, "reply": reply, "role": role_key})
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
    WORK_CHATS.mkdir(parents=True, exist_ok=True)
    ROLE_CHATS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"gate-chat server on http://0.0.0.0:{PORT}")
    print(f"  dashboard: {DASHBOARD}")
    print(f"  chats: {CHATS}")
    print(f"  role chats: {ROLE_CHATS}")
    print(f"  ledger: {LEDGER}")
    print(f"  live API: {', '.join(LIVE_FILES)}")
    print(f"  agent: {os.environ.get('GATE_AGENT_CMD', DEFAULT_AGENT)}")
    print(f"  role agent: {os.environ.get('ROLE_AGENT_CMD', DEFAULT_ROLE_AGENT)}")
    print("Expose via cloudflared/tailscale; set dashboard/config.json gateChatApi to the HTTPS URL.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
