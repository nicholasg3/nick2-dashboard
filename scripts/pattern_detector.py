#!/usr/bin/env python3
"""Detect recurring failure signatures in ledger + role memories (24h window).

On 3rd occurrence of the same (task_id, signature), emit pattern_flag to the
CEO ledger so workers treat recurrence as a first-class signal (SKILL review).
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "logs" / "ceo-ledger.jsonl"
SESSIONS_ROOT = Path(
    os.environ.get(
        "AGENT_BUS_SESSIONS",
        ROOT.parent / "ai-agents-workspace" / "agent-bus" / "sessions",
    )
)

WINDOW_HOURS = 24
THRESHOLD = 3
SGT = timezone(timedelta(hours=8))
MARKER_RE = re.compile(r"reconcile-bus:([\w-]+)")
FAILURE_SNIPPETS = (
    "pmo-stale-no-worker",
    "p001-stale-approved",
    "repo lock",
    "zombie",
    "no PMO job on bus",
    "worker failed",
    "blocked verdict",
)


def parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cutoff() -> datetime:
    return datetime.now(SGT) - timedelta(hours=WINDOW_HOURS)


def _in_window(ts: str, cutoff: datetime) -> bool:
    dt = parse_ts(ts)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SGT)
    return dt.astimezone(SGT) >= cutoff.astimezone(SGT)


def extract_signature(text: str) -> str | None:
    if not text:
        return None
    m = MARKER_RE.search(text)
    if m:
        return m.group(1).strip().lower()
    low = text.lower()
    for snippet in FAILURE_SNIPPETS:
        if snippet in low:
            return snippet.replace(" ", "-")
    return None


def load_ledger(path: Path | None = None) -> list[dict]:
    path = path or LEDGER
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _scan_memories(sessions_root: Path, cutoff: datetime) -> list[tuple[str, str, str]]:
    """Yield (task_id, signature, source) from role memory files."""
    if not sessions_root.is_dir():
        return []
    hits: list[tuple[str, str, str]] = []
    for session_dir in sessions_root.iterdir():
        if not session_dir.is_dir():
            continue
        session = session_dir.name
        task_id = _session_default_task(session)
        for name in ("memories.jsonl", "memories.archive.jsonl"):
            mem = session_dir / name
            if not mem.is_file():
                continue
            for line in mem.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = obj.get("ts") or ""
                if not _in_window(ts, cutoff):
                    continue
                blob = " ".join(
                    str(obj.get(k) or "") for k in ("text", "kind", "summary")
                )
                sig = extract_signature(blob)
                if sig:
                    hits.append((task_id or session, sig, f"memory:{session}"))
    return hits


def _session_default_task(session: str) -> str:
    return {
        "pmo": "PMO-001",
        "dashboard_worker": "SYS-002",
        "coding_worker": "SYS-001",
        "ceo": "FOCUS-001",
    }.get(session, "")


def count_signatures(
    events: list[dict],
    *,
    sessions_root: Path | None = None,
    window_hours: int = WINDOW_HOURS,
) -> dict[tuple[str, str], list[dict]]:
    """Map (task_id, signature) -> list of occurrence records in window."""
    cutoff = datetime.now(SGT) - timedelta(hours=window_hours)
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for ev in events:
        ts = ev.get("ts") or ""
        if not _in_window(ts, cutoff):
            continue
        if ev.get("event") == "pattern_flag":
            continue
        task_id = ev.get("task_id") or ev.get("focus_task_id") or ""
        output = ev.get("output") or ""
        sig = extract_signature(output)
        if task_id and sig:
            buckets[(task_id, sig)].append(
                {"ts": ts, "event": ev.get("event"), "source": "ledger"}
            )

    for task_id, sig, source in _scan_memories(sessions_root or SESSIONS_ROOT, cutoff):
        if task_id and sig:
            buckets[(task_id, sig)].append({"ts": "", "event": "memory", "source": source})

    return buckets


def already_flagged(
    events: list[dict],
    task_id: str,
    signature: str,
    *,
    window_hours: int = WINDOW_HOURS,
) -> bool:
    cutoff = datetime.now(SGT) - timedelta(hours=window_hours)
    for ev in reversed(events):
        if ev.get("event") != "pattern_flag":
            continue
        if not _in_window(ev.get("ts") or "", cutoff):
            continue
        if ev.get("task_id") == task_id and (ev.get("signature") or "") == signature:
            return True
    return False


def pattern_flags_to_emit(
    events: list[dict],
    *,
    sessions_root: Path | None = None,
    threshold: int = THRESHOLD,
    window_hours: int = WINDOW_HOURS,
) -> list[dict[str, Any]]:
    buckets = count_signatures(events, sessions_root=sessions_root, window_hours=window_hours)
    flags: list[dict[str, Any]] = []
    for (task_id, signature), occ in buckets.items():
        if len(occ) < threshold:
            continue
        if already_flagged(events, task_id, signature, window_hours=window_hours):
            continue
        flags.append(
            {
                "event": "pattern_flag",
                "task_id": task_id,
                "signature": signature,
                "count": len(occ),
                "window_hours": window_hours,
                "status": "flagged",
                "output": (
                    f"Pattern detected {len(occ)}× in {window_hours}h: "
                    f"reconcile-bus:{signature} on {task_id}. "
                    "PMO/worker may propose SKILL.md best-practice update."
                ),
                "sources": [o.get("source") for o in occ[:5]],
            }
        )
    return flags


def emit_pattern_flags(
    events: list[dict],
    base: dict[str, Any],
    append: Callable[[dict], bool],
    *,
    sessions_root: Path | None = None,
) -> int:
    """Append pattern_flag events; returns count written."""
    n = 0
    for flag in pattern_flags_to_emit(events, sessions_root=sessions_root):
        if append({**base, **flag, "actor": "COO", "role": "Chief Operating Officer"}):
            n += 1
            events.append(flag)
    return n


def recent_flags_for_task(
    task_id: str,
    *,
    ledger_path: Path | None = None,
    window_hours: int = WINDOW_HOURS,
) -> list[dict]:
    events = load_ledger(ledger_path)
    cutoff = datetime.now(SGT) - timedelta(hours=window_hours)
    out = []
    for ev in events:
        if ev.get("event") != "pattern_flag":
            continue
        if ev.get("task_id") != task_id:
            continue
        if _in_window(ev.get("ts") or "", cutoff):
            out.append(ev)
    return out[-5:]


def main() -> int:
    events = load_ledger()
    base = {"needs_nicholas": False, "cost_usd": 0}

    def _append(ev: dict) -> bool:
        ev.setdefault("ts", datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S+08:00"))
        line = json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n"
        prefix = ""
        if LEDGER.exists() and LEDGER.stat().st_size > 0:
            if not LEDGER.read_bytes().endswith(b"\n"):
                prefix = "\n"
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(prefix + line)
        print(f"pattern_detector: appended pattern_flag {ev.get('task_id')} {ev.get('signature')}")
        return True

    n = emit_pattern_flags(events, base, _append)
    print(f"pattern_detector: {n} flag(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())