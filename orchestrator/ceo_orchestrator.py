#!/usr/bin/env python3
"""Persistent CEO orchestrator for Nick2.

This is the Phase A implementation from the architecture doc:
- wake on a cadence
- survey bus/ledger/dashboard state
- run the existing CEO supervisor + reflect tools
- write status/memos for the dashboard
- stay conservative: all work goes through existing admission caps

The service deliberately does not pretend to be a general autonomous employee yet.
It is an always-on executive loop that keeps the current operating layer warm,
visible, and accountable.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("NICK2_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = ROOT / "scripts"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
MEMOS = ROOT / "memos" / "orchestrator"
STATUS = REPORTS / "orchestrator" / "status.json"
TICKS = LOGS / "orchestrator" / "ticks.jsonl"
LOCK = ROOT / ".ceo-orchestrator.lock"
ROLE_CHATS = LOGS / "role-chats"

sys.path.insert(0, str(SCRIPTS))
import ceo_supervisor as supervisor  # noqa: E402


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if path.exists() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n"):
        prefix = "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(prefix + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def run_cmd(args: list[str], timeout: int = 120) -> dict:
    try:
        r = subprocess.run(
            args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "stdout": (r.stdout or "")[-2000:],
            "stderr": (r.stderr or "")[-1000:],
        }
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "error": str(e)[:500]}


def refresh_reports() -> dict:
    return run_cmd([sys.executable, str(SCRIPTS / "export-json-reports.py")], timeout=180)


def role_chat_summary() -> dict:
    out: dict[str, dict] = {}
    for role in ("ceo", "coo", "pmo"):
        path = ROLE_CHATS / f"{role}.jsonl"
        count = 0
        last = None
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                count += 1
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    pass
        out[role] = {
            "messages": count,
            "last_actor": (last or {}).get("actor"),
            "last_ts": (last or {}).get("ts"),
            "last_text": ((last or {}).get("text") or "")[:240],
        }
    return out


def survey() -> dict:
    return {
        "ts": now(),
        "bus_live": read_json(REPORTS / "bus-live.json", {}),
        "ceo_queue": read_json(REPORTS / "ceo-queue.json", {}),
        "org_fleet": read_json(REPORTS / "org-fleet.json", {}),
        "gated": read_json(REPORTS / "gated.json", []),
        "role_chats": role_chat_summary(),
    }


def summarize_tick(report: dict, state: dict) -> str:
    reflect = report.get("reflect") or {}
    counts = ((reflect.get("context") or {}).get("counts") or {})
    actions = len(reflect.get("actions") or [])
    bottlenecks = int(reflect.get("bottleneck_count") or 0)
    issues = report.get("issues") or []
    running = counts.get("running", 0)
    held = counts.get("held", 0)
    queued = counts.get("queued", 0)
    if issues:
        lead = f"CEO loop found {len(issues)} issue(s): {issues[0]}"
    elif actions:
        lead = f"CEO loop took {actions} bounded action(s)."
    else:
        lead = "CEO loop checked the system; no action was needed."
    return (
        f"{lead} Bus: {running} running, {held} held, {queued} queued. "
        f"Bottlenecks: {bottlenecks}. Role chat messages: "
        f"CEO {state['role_chats']['ceo']['messages']}, "
        f"COO {state['role_chats']['coo']['messages']}, "
        f"PMO {state['role_chats']['pmo']['messages']}."
    )


def write_memo(status: dict) -> None:
    MEMOS.mkdir(parents=True, exist_ok=True)
    report = status.get("last_report") or {}
    reflect = report.get("reflect") or {}
    lines = [
        f"# CEO orchestrator — {status.get('last_tick_at', '')}",
        "",
        f"**Mode:** {status.get('mode')}  ",
        f"**Healthy:** {status.get('healthy')}  ",
        f"**Summary:** {status.get('summary')}",
        "",
        "## Current Counts",
    ]
    counts = ((reflect.get("context") or {}).get("counts") or {})
    lines.extend(
        [
            f"- Running: {counts.get('running', 0)}",
            f"- Held: {counts.get('held', 0)}",
            f"- Queued: {counts.get('queued', 0)}",
            f"- Bottlenecks: {reflect.get('bottleneck_count', 0)}",
            "",
            "## Role Rooms",
        ]
    )
    for role, info in (status.get("survey") or {}).get("role_chats", {}).items():
        lines.append(
            f"- {role.upper()}: {info.get('messages', 0)} messages"
            + (f"; last from {info.get('last_actor')} at {info.get('last_ts')}" if info.get("last_ts") else "")
        )
    lines.append("")
    if report.get("issues"):
        lines.append("## Issues")
        for issue in report["issues"]:
            lines.append(f"- {issue}")
        lines.append("")
    lines.append("## Artifacts")
    lines.append("- `reports/orchestrator/status.json`")
    lines.append("- `logs/orchestrator/ticks.jsonl`")
    (MEMOS / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_once(*, dry_run: bool = False, reason: str = "manual", persist: bool = True) -> dict:
    if os.environ.get("CEO_ORCH_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        status = {
            "ts": now(),
            "mode": "disabled",
            "healthy": True,
            "reason": "CEO_ORCH_ENABLED=0",
        }
        if persist:
            write_json(STATUS, status)
        return status

    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ts": now(), "mode": "skipped", "healthy": True, "reason": "lock-held"}

        pre = survey()
        try:
            report = supervisor.run_cycle(dry_run=dry_run, append_ledger=not dry_run)
            error = None
        except Exception as exc:  # service must stay alive and report the fault
            report = {"healthy": False, "issues": [f"orchestrator exception: {exc}"]}
            error = str(exc)[:1000]

        refresh = refresh_reports() if not dry_run else {"ok": True, "dry_run": True}
        post = survey()
        status = {
            "ts": now(),
            "mode": "dry_run" if dry_run else "live",
            "reason": reason,
            "healthy": bool(report.get("healthy")) and refresh.get("ok", False),
            "last_tick_at": now(),
            "summary": summarize_tick(report, post),
            "survey": post,
            "last_report": report,
            "refresh": refresh,
            "error": error,
        }
        if persist:
            write_json(STATUS, status)
            write_memo(status)
            append_jsonl(
                TICKS,
                {
                    "ts": status["last_tick_at"],
                    "mode": status["mode"],
                    "healthy": status["healthy"],
                    "summary": status["summary"],
                    "reason": reason,
                    "pre_counts": (pre.get("bus_live") or {}).get("counts"),
                },
            )
        return status


def loop(*, interval_sec: int, dry_run: bool = False) -> None:
    print(f"ceo-orchestrator starting interval={interval_sec}s dry_run={dry_run}", flush=True)
    while True:
        status = run_once(dry_run=dry_run, reason="heartbeat")
        print(json.dumps({"ts": now(), "healthy": status.get("healthy"), "summary": status.get("summary")}), flush=True)
        time.sleep(max(30, interval_sec))


def selftest() -> None:
    status = run_once(dry_run=True, reason="selftest", persist=False)
    assert status.get("mode") == "dry_run", status
    assert status.get("summary"), status
    print("ceo_orchestrator selftest OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Nick2 persistent CEO orchestrator")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--interval-sec", type=int, default=int(os.environ.get("CEO_ORCH_INTERVAL_SEC", "300")))
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if args.once:
        print(json.dumps(run_once(dry_run=args.dry_run, reason="manual-once"), indent=2))
        return 0
    loop(interval_sec=args.interval_sec, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
