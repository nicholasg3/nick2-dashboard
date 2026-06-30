#!/usr/bin/env python3
"""POL-003 cron witness — sync-dashboard-live must run at least every 20 minutes."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT = ROOT / "logs" / "sync-heartbeat.txt"
LOG = ROOT / "logs" / "sync-dashboard-live.log"
MAX_AGE_MIN = float(os.environ.get("SYNC_HEARTBEAT_MAX_MIN", "20"))


def _parse_ts(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def heartbeat_age_minutes() -> tuple[float | None, str]:
    if HEARTBEAT.is_file():
        ts = _parse_ts(HEARTBEAT.read_text(encoding="utf-8"))
        if ts:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds() / 60.0
            return age, "sync-heartbeat.txt"
    if LOG.is_file():
        age = (datetime.now(timezone.utc).timestamp() - LOG.stat().st_mtime) / 60.0
        return age, "sync-dashboard-live.log mtime"
    return None, "missing"


def check(*, max_age_min: float | None = None) -> list[str]:
    cap = max_age_min if max_age_min is not None else MAX_AGE_MIN
    age, source = heartbeat_age_minutes()
    if age is None:
        return ["POL-003 cron: no sync heartbeat or log — run install-droplet-cron.sh"]
    if age > cap:
        return [
            f"POL-003 cron stale: last sync {age:.0f}m ago via {source} (max {cap:.0f}m)"
        ]
    return []


def maybe_alert(issues: list[str]) -> bool:
    if not issues:
        return False
    sys.path.insert(0, str(ROOT / "scripts"))
    import sync_alert as sa  # noqa: E402

    body = "Nick2 sync loop\n\n" + "\n".join(f"• {i}" for i in issues)
    return sa.send_alert(body)


def main() -> int:
    issues = check()
    for i in issues:
        print(f"CRON HEALTH FAIL: {i}", file=sys.stderr)
    if issues and os.environ.get("CRON_HEALTH_ALERT", "1") not in ("0", "false"):
        maybe_alert(issues)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())