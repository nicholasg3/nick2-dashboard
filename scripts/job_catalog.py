#!/usr/bin/env python3
"""Job work catalog — enrich from GitHub, detect landed-on-main (POL-009)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKSPACE = Path(
    __import__("os").environ.get(
        "AGENT_BUS_ROOT",
        str(ROOT.parent / "ai-agents-workspace" / "agent-bus"),
    )
).parent
CATALOG_PATH = ROOT / "job_work_catalog.json"
TRIAGE_PATH = ROOT / "pmo_001_result.json"
GH_REPO = "nicholasg3/ai-agents-workspace"

SKIP_LANDED_WITNESS = re.compile(
    r"no bus dispatch|decision recorded|nick's queue|decision memo",
    re.I,
)
SKIP_LANDED_DOING = re.compile(
    r"\*\*nick's queue|\*\*done — no bus dispatch|not running on agents",
    re.I,
)
WITNESS_CMD_RE = re.compile(r"(python3\s+[^\n;]+)")
THIN_WITNESS_RE = re.compile(
    r"closes #\d+ when witness passes|when witness passes$|mission completed per ledger",
    re.I,
)


def load_catalog() -> dict:
    if not CATALOG_PATH.is_file():
        return {"version": 1, "tasks": {}}
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "tasks": {}}


def save_catalog(data: dict) -> None:
    data.setdefault("version", 1)
    CATALOG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_triage() -> dict | None:
    if not TRIAGE_PATH.is_file():
        return None
    try:
        return json.loads(TRIAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_triage(data: dict) -> None:
    TRIAGE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def repo_root(repo: str) -> Path:
    if repo == "nick2-dashboard":
        return ROOT
    return WORKSPACE


def is_thin_entry(entry: dict | None) -> bool:
    if not entry:
        return True
    witness = str(entry.get("witness") or "")
    if THIN_WITNESS_RE.search(witness):
        return True
    steps = entry.get("steps") or []
    if len(steps) < 2:
        return True
    doing = str(entry.get("doing") or "")
    if len(doing) < 40:
        return True
    return False


def fetch_github_issue(issue_number: int, *, repo: str = GH_REPO) -> dict | None:
    try:
        r = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--repo",
                repo,
                "--json",
                "title,body,labels,state",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def _first_paragraph(body: str) -> str:
    lines = []
    for line in (body or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            if lines:
                break
            continue
        lines.append(line)
        if len(" ".join(lines)) > 120:
            break
    return " ".join(lines)[:500]


def _labels(gh: dict) -> list[str]:
    return [lb.get("name", "") for lb in (gh.get("labels") or []) if isinstance(lb, dict)]


def is_decision_gated(item: dict, entry: dict | None, gh: dict | None = None) -> bool:
    if item.get("dispatch") is False and item.get("defer_reason"):
        reason = str(item.get("defer_reason") or "")
        if "landed on main" not in reason.lower():
            return True
    if entry:
        if SKIP_LANDED_DOING.search(str(entry.get("doing") or "")):
            return True
        if SKIP_LANDED_WITNESS.search(str(entry.get("witness") or "")):
            return True
    if gh:
        labels = _labels(gh)
        if "needs-nick" in labels:
            return True
        body = (gh.get("body") or "").lower()
        if "decide if/when" in body or "low priority — decide" in body:
            return True
    title = (item.get("title") or "").lower()
    if title.startswith("decision:"):
        return True
    return False


def witness_commands(witness: str) -> list[str]:
    if SKIP_LANDED_WITNESS.search(witness or ""):
        return []
    cmds: list[str] = []
    first_dir = ""
    m0 = WITNESS_CMD_RE.search(witness or "")
    if m0:
        parts = m0.group(1).split()
        if len(parts) >= 2 and "/" in parts[1]:
            first_dir = "/".join(parts[1].split("/")[:-1])

    def _expand_or_paren(text: str) -> str:
        def repl(m: re.Match) -> str:
            tail = m.group(1).strip()
            if tail.startswith("python3"):
                return " or " + tail
            if "/" not in tail and first_dir:
                return f" or python3 {first_dir}/{tail}"
            return f" or python3 {tail}"

        return re.sub(r"\(\s*or\s+([^)]+)\)", repl, text, flags=re.I)

    normalized = _expand_or_paren(witness or "")
    for alt in re.split(r"\s+or\s+", normalized, flags=re.I):
        for part in re.split(r"[;]", alt):
            part = part.strip()
            for m in WITNESS_CMD_RE.finditer(part):
                cmd = m.group(1).strip()
                cmd = re.sub(r"\s+exits\s+0.*$", "", cmd, flags=re.I).strip()
                cmd = re.sub(r"\s*\(.*$", "", cmd).strip()
                if cmd and cmd not in cmds:
                    cmds.append(cmd)
    return cmds


def paths_exist(repo: str, touch_paths: list[str]) -> tuple[bool, list[str]]:
    base = repo_root(repo)
    missing = []
    for rel in touch_paths or []:
        rel = str(rel).strip()
        if not rel:
            continue
        p = base / rel
        if not p.exists():
            missing.append(rel)
    ok = not missing and bool(touch_paths)
    return ok, missing


def run_witness(cmd: str, repo: str) -> tuple[bool, str]:
    cwd = repo_root(repo)
    try:
        r = subprocess.run(
            cmd.split(),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode == 0:
            return True, "exit 0"
        err = (r.stderr or r.stdout or "")[:200]
        return False, f"exit {r.returncode}: {err}"
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)[:200]


def assess_landed(
    task_id: str,
    item: dict,
    entry: dict | None,
    *,
    gh: dict | None = None,
) -> dict[str, Any]:
    """Return {landed: bool, reason: str, witness_ok: bool, paths_ok: bool}."""
    if is_decision_gated(item, entry, gh):
        return {"landed": False, "reason": "decision-gated", "skipped": True}

    entry = entry or {}
    audit_mode = str(entry.get("landed_audit") or "open_witness").lower()
    if audit_mode in ("off", "false", "none"):
        return {"landed": False, "reason": "landed_audit off", "skipped": True}

    shipped = bool(entry.get("shipped_on_main"))
    gh_closed = bool(gh and (gh.get("state") or "").upper() == "CLOSED")
    if audit_mode == "closed_only" and not gh_closed:
        return {"landed": False, "reason": "issue still open", "skipped": True}
    if audit_mode == "open_witness" and not shipped and not gh_closed:
        return {"landed": False, "reason": "open issue — need shipped_on_main or closed", "skipped": True}
    repo = str(item.get("repo") or "ai-agents-workspace")
    touch = list(entry.get("touch_paths") or [])
    paths_ok, missing = paths_exist(repo, touch)
    witness = str(entry.get("witness") or "")
    cmds = witness_commands(witness)
    witness_ok = False
    witness_detail = "no runnable witness"
    if cmds:
        for cmd in cmds:
            ok, detail = run_witness(cmd, repo)
            if ok:
                witness_ok = True
                witness_detail = cmd
                break
            witness_detail = detail

    landed = paths_ok and witness_ok
    reason = ""
    if landed:
        reason = f"witness green ({witness_detail}); touch_paths on main"
    elif not paths_ok:
        reason = f"missing paths: {', '.join(missing[:3])}"
    else:
        reason = f"witness failed: {witness_detail}"

    return {
        "landed": landed,
        "reason": reason,
        "witness_ok": witness_ok,
        "paths_ok": paths_ok,
        "skipped": False,
    }


def enrich_catalog_entry(
    task_id: str,
    item: dict,
    catalog: dict | None = None,
    *,
    dry_run: bool = False,
) -> bool:
    """Fill thin catalog rows from triage item + GitHub issue. Returns True if changed."""
    data = catalog if catalog is not None else load_catalog()
    tasks = data.setdefault("tasks", {})
    entry = dict(tasks.get(task_id) or {})
    changed = False

    title = str(item.get("title") or task_id)
    issue_num = item.get("issue_number")
    gh = None
    if issue_num is not None:
        gh = fetch_github_issue(int(issue_num))

    if not entry.get("problem") or is_thin_entry(entry):
        if gh and gh.get("body"):
            entry["problem"] = _first_paragraph(gh["body"])
            changed = True
        elif item.get("objective") and not entry.get("problem"):
            entry["problem"] = str(item["objective"])[:400]
            changed = True

    if is_thin_entry(entry) or not entry.get("doing"):
        entry["doing"] = f"Implement per GitHub issue — {title}"
        if gh and _first_paragraph(gh.get("body") or ""):
            entry["doing"] = _first_paragraph(gh["body"])[:400]
        changed = True

    if len(entry.get("steps") or []) < 2:
        entry["steps"] = [
            f"Read GitHub issue #{issue_num}" if issue_num else f"Read {task_id} scope",
            "Implement on job branch with runnable witness",
            "Report evidence; do not merge to main",
        ]
        changed = True

    if THIN_WITNESS_RE.search(str(entry.get("witness") or "")) or not entry.get("witness"):
        if issue_num:
            entry["witness"] = f"Closes #{issue_num} when catalog witness command exits 0 on job branch"
        else:
            entry["witness"] = f"{task_id}: runnable witness exits 0 before done"
        changed = True

    if not entry.get("landed_audit") or str(entry.get("landed_audit")).lower() in (
        "off",
        "false",
        "none",
    ):
        if not is_decision_gated(item, entry, gh):
            entry["landed_audit"] = "open_witness"
            changed = True

    if not entry.get("touch_paths"):
        repo = str(item.get("repo") or "ai-agents-workspace")
        area = str(item.get("area") or "")
        hints: list[str] = []
        if area == "agent-infra" and repo == "ai-agents-workspace":
            hints = ["agent-bus/scripts/"]
        elif repo == "nick2-dashboard":
            hints = ["scripts/"]
        if hints:
            entry["touch_paths"] = hints
            changed = True

    if changed and not dry_run:
        tasks[task_id] = entry
        save_catalog(data)
    elif changed:
        tasks[task_id] = entry

    return changed


def enrich_catalog_from_triage(*, dry_run: bool = False) -> dict[str, Any]:
    triage = load_triage()
    if not triage:
        return {"enriched": 0, "skipped": "no triage file"}
    catalog = load_catalog()
    sys.path.insert(0, str(SCRIPTS))
    import pmo_dispatch as pd  # noqa: E402

    n = 0
    for item in triage.get("top_issues") or []:
        tid = pd.issue_task_id(item)
        if enrich_catalog_entry(tid, item, catalog, dry_run=dry_run):
            n += 1
    if n and not dry_run:
        save_catalog(catalog)
    return {"enriched": n, "dry_run": dry_run}


def audit_landed_on_main(*, dry_run: bool = False) -> dict[str, Any]:
    """POL-009 — auto dispatch:false when catalog witness is green on main."""
    triage = load_triage()
    if not triage:
        return {"updated": 0, "skipped": "no triage file"}

    sys.path.insert(0, str(SCRIPTS))
    import pmo_dispatch as pd  # noqa: E402

    catalog = load_catalog()
    tasks = catalog.get("tasks") or {}
    updated: list[dict] = []

    for item in triage.get("top_issues") or []:
        tid = pd.issue_task_id(item)
        if item.get("dispatch") is False:
            continue
        entry = tasks.get(tid)
        gh = None
        if item.get("issue_number") is not None:
            gh = fetch_github_issue(int(item["issue_number"]))
        if is_decision_gated(item, entry, gh):
            continue

        enrich_catalog_entry(tid, item, catalog, dry_run=dry_run)
        entry = catalog.get("tasks", {}).get(tid) or entry
        verdict = assess_landed(tid, item, entry, gh=gh)
        if not verdict.get("landed"):
            continue

        item["dispatch"] = False
        item["defer_reason"] = f"POL-009 landed on main — {verdict['reason']}"
        updated.append({"task_id": tid, "reason": verdict["reason"]})

    out = {"updated": len(updated), "tasks": updated, "dry_run": dry_run}
    if updated and not dry_run:
        save_triage(triage)
        save_catalog(catalog)
    return out


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Job catalog enrich + landed audit")
    p.add_argument("--enrich", action="store_true")
    p.add_argument("--audit-landed", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.enrich:
        print(json.dumps(enrich_catalog_from_triage(dry_run=args.dry_run), indent=2))
    if args.audit_landed:
        print(json.dumps(audit_landed_on_main(dry_run=args.dry_run), indent=2))
    if not args.enrich and not args.audit_landed:
        print(json.dumps(audit_landed_on_main(dry_run=args.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())