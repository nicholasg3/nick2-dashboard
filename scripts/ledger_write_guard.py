"""Ledger write-path guard — resolve blocked vs executing conflicts from live bus."""
from __future__ import annotations

import re
from typing import Any

from dashboard_honesty import (
    MARKER_PREFIX,
    cited_job_suffixes,
    ensure_fresh_bus_truth,
)

MISSION_SESSION = {
    "PMO-001": "pmo",
    "SYS-002": "dashboard_worker",
    "P-001": "pmo",
}


def _running_job_ids(truth: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for j in truth.get("running_jobs") or []:
        jid = j.get("job_id") or ""
        if jid:
            ids.add(jid)
            m = re.match(r"^JOB-\d{8}-(\d+)$", jid)
            if m:
                ids.add(f"JOB-{m.group(1)}")
    return ids


def _pmo_running(truth: dict[str, Any]) -> list[dict]:
    return [
        j
        for j in truth.get("running_jobs") or []
        if (j.get("to_session") or j.get("lane")) == "pmo"
    ]


def guard_ledger_event(
    event: dict[str, Any],
    *,
    bus_truth: dict[str, Any] | None = None,
    required_fresh_min: float = 0.0,
) -> dict[str, Any] | None:
    """Return coerced event, or None to skip write (e.g. stale bus, no change needed)."""
    task_id = event.get("task_id") or ""
    status = (event.get("status") or "").lower()
    output = event.get("output") or ""

    if event.get("event") not in ("task_updated", "focus_snapshot", "supervisor_checkin"):
        return event

    stale_markers = (
        "pmo-stale-no-worker",
        "p001-stale-approved",
        "no PMO job on bus",
        "triage stalled",
        "no job on bus for",
    )
    is_stale_verdict = status in ("blocked", "idle") and any(
        m in output for m in stale_markers
    )
    if not is_stale_verdict and status not in ("blocked", "idle"):
        return event

    truth = bus_truth or ensure_fresh_bus_truth(required_fresh_min=required_fresh_min)
    if not truth.get("fresh"):
        return None

    running_ids = _running_job_ids(truth)
    cited = cited_job_suffixes(output)

    # Same job ID cannot be blocked in ledger while executing on bus.
    for suffix in cited:
        full = next(
            (j.get("job_id") for j in truth.get("running_jobs") or [] if suffix in (j.get("job_id") or "")),
            None,
        )
        if full or f"JOB-{suffix}" in running_ids:
            short = f"JOB-{suffix}"
            return {
                **event,
                "status": "in_progress",
                "output": (
                    f"{MARKER_PREFIX}guard-running {short} is executing on bus — "
                    f"overrode ledger {status} (live bus wins)."
                ),
            }

    session = MISSION_SESSION.get(task_id)
    if session:
        session_jobs = [
            j
            for j in truth.get("running_jobs") or []
            if (j.get("to_session") or "") == session
        ]
        if session_jobs:
            job = session_jobs[0]
            short = job.get("short_job_id") or job.get("job_id", "")
            return {
                **event,
                "status": "in_progress",
                "output": (
                    f"{MARKER_PREFIX}guard-session {short} running on {session} — "
                    f"overrode ledger {status}."
                ),
            }

    if task_id == "PMO-001" and status == "blocked":
        pmo_jobs = _pmo_running(truth)
        if pmo_jobs:
            job = pmo_jobs[0]
            short = job.get("short_job_id") or job.get("job_id", "")
            return {
                **event,
                "status": "in_progress",
                "output": (
                    f"{MARKER_PREFIX}guard-pmo {short} executing — "
                    "blocked verdict suppressed (live bus)."
                ),
            }

    return event