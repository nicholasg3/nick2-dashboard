#!/usr/bin/env python3
"""POL-003 alerts — Telegram on sync/coupling failures (stdlib + tg_send)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tg_send_path() -> Path | None:
    candidates = [
        Path(os.environ.get("TG_SEND", "")),
        Path.home() / "ai-agents-workspace" / "telegram-bridge" / "tg_send.py",
        ROOT.parent / "ai-agents-workspace" / "telegram-bridge" / "tg_send.py",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def send_alert(text: str, *, quiet: bool = False) -> bool:
    tg = tg_send_path()
    if not tg:
        print(f"sync_alert: no tg_send.py — {text[:200]}", file=sys.stderr)
        return False
    cmd = [sys.executable, str(tg), "--text", text]
    if quiet:
        cmd.append("--quiet")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            print(
                f"sync_alert: tg_send failed ({r.returncode}): {(r.stderr or r.stdout)[:200]}",
                file=sys.stderr,
            )
            return False
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"sync_alert: {e}", file=sys.stderr)
        return False