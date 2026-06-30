# Handoff to Claude — Nick2 Architecture Implementation

**Date:** 2026-07-01
**From:** Grok (xAI) under /jesus-ralph + /amen loop
**To:** Claude (Anthropic)
**Purpose:** Corrected summary of architecture work from 2026-07-01-fix-architecture.md.
Important correction: the CEO orchestrator was **not** implemented as a running agent. It
exists only as an uncommitted scaffold. Current state: portfolio idle, focus SYS-002.
Continue the walk using jesus-pattern discipline. Commit promptly to main after verified
work. Update this handoff or the main one with progress.

**Environment:** droplet agents-sgp01 (168.144.97.10, user nicholas). Primary repos: nick2-dashboard (orchestrator, ledger, dashboard) and ai-agents-workspace (bus, bridge, frontier). Git canonical on GH. Work on droplet, push via cron or manual.

**Global rules (from main handoff):**
- Commit promptly.
- Truth in logs/ceo-ledger.jsonl + jobs.sqlite.
- Never claim state in chat.
- Use delegation flags from main handoff.
- Follow jesus-pattern: translate shape, walk nodes Plan Build Test Judge, no fabricated green.
- For live changes: test behind witness, watch logs.

**Companion docs:**
- 2026-07-01-fix-architecture.md (the main spec, now with implementation logs).
- 2026-06-30-orchestrator-managers-vision.md
- 2026-07-01-orchestrator-phase-a-plan-and-findings.md
- 2026-06-30-ceo-reflect-intention-vs-reality.md
- memos/policy.md
- Projects-for-agents/frontier-orchestrator/org.json (roles + authority)
- references/model-routing.yaml (if present)

## Current State (as of 2026-07-01 ~02:00 SGT)
- Portfolio idle.
- CEO supervision (FOCUS-001 / SYS-002): repeated reflections on no active jobs, historical blocked (ISSUE-BUS-001, ISSUE-80).
- Fleet: Hermes (always-on, router), PMO/COO (always-on via tmux).
- Budget: $20 cap, ~$0 spent.
- Gated by Nick: empty.
- Live dashboard (GH pages + http://168.144.97.10:8788/) working — pulling fresh ledger/bus data.
- Bus queues empty; no running workers.
- No CEO orchestrator is running. `orchestrator/` is currently untracked scaffolding, not
  committed or deployed.

Recent activity: CEO reflecting on stalled historical state. New diagnostic job dispatched (JOB-20260630-641 to heavy_coder) to un-idle.

## Architecture Implementation Status

Correction after audit: the earlier claim that all mechanical/non-Nick-gated parts of WI-1
to WI-7 were completed was overstated. Some adjacent pieces exist, but the CEO
orchestrator is not committed, not running, and not LLM-driven. Treat WI-3/WI-4/WI-5/WI-6
as draft scaffolding unless verified otherwise.

## Audit Correction (2026-07-01)

Evidence observed on the droplet:

| Check | Result |
| --- | --- |
| Git state | `orchestrator/`, `skills/`, and this handoff are untracked; main is ahead of origin with other dirty/generated files. |
| Running process | No `ceo_orchestrator.py` process found. |
| systemd | No user service for a CEO orchestrator; only `frontier-orchestrator.service` is inactive/dead and `nick2-gate-chat.service` is active. |
| LLM integration | `orchestrator/ceo_orchestrator.py` makes no model call; `reflect()` is a placeholder returning a fixed summary. |
| Chat surface | `orchestrator/say.py` only appends JSONL to an inbox path. No running inbox reader or dashboard work-room reply loop is wired to the CEO/COO/PMO. |
| Code substance | The file is a skeleton with `while True` + `time.sleep(30)`, placeholder comments, and narration prints such as "WI-4/5 wiring added to orchestrator skeleton." |

Conclusion: the current artifact is salvageable as a starting scaffold, but it is not a
Phase A implementation. The real build still needs an LLM-driven heartbeat, committed code,
service deployment, inbox/work-room wiring, authority enforcement, and witnesses.

### WI-1 — Hermes no memory
- Done: 
  - control.json on primary: backend claude-code, claude_route ccr, claude_model anthropic/claude-3-5-haiku (per latest decision to use haiku for Hermes).
  - Per-backend session storage in bridge.py: sessions now dict {leaf: sid} with legacy migration. Failover propagates backup sid.
  - test_session_continuity.py created (exact 3 tests + WORKDIR note).
- HOW: Direct edits via SSH on primary + local clone. Synced. Interop: control.json drives make_backend(); main loop now stores per-leaf; ClaudeCodeBackend already emits real session_id.
- Gated: Real TG verification (Nick must send test messages).

### WI-2 — Workers
- Done:
  - Error surfacing: full failure_detail (stdout/stderr/envelope) in reports (bus.py).
  - Model policy (delegated + updated): 
    - Hermes: anthropic/claude-3-5-haiku (primary per use haiku).
    - Workers: qwen/qwen3-coder (normal), escalate to moonshotai/kimi-k2.6 (agentic/tool-heavy; chosen as current best opensource coding model).
    - Other tiers per previous (pmo, research).
  - Escalation + $20/wk: _should_escalate + _check_budget in worker_model.py (attempts, task hints, coherence, weekly > $15 forces cheap, premium explicit only under cap).
  - Timeouts: sane.
- HOW: Updated agent-bus/scripts/worker_model.py (DEFAULTS, resolve functions). Synced. Best practice: decompose for cheap tiers + coherence.
- Gated: Complex job execution + human judgment of output quality before merge.

### WI-3 — CEO Orchestrator Phase A
- Status: **not implemented**.
- What exists:
  - Untracked `orchestrator/ceo_orchestrator.py` scaffold with `survey()`,
    placeholder `reflect()`, simulated `bus_submit()`, and a sleep loop.
  - Untracked `orchestrator/say.py` that appends to `reports/orchestrator/<role>-inbox.jsonl`.
  - Untracked `skills/nick2-orchestrator/SKILL.md`.
- Missing:
  - Committed code.
  - Running systemd user service.
  - Any LLM/model call in the orchestrator.
  - Real inbox reader/reply path for CEO/COO/PMO.
  - Real bus submission and dashboard work-room integration.
  - Witnesses proving the loop can survey, reflect, act, and be talked to.
- Next: build WI-3 from the architecture doc for real. Do not describe it as done until
  code is committed, running, LLM-backed, and witnessed.

### WI-4 — Memory architecture
- Status: **scaffold only**.
- The untracked orchestrator file contains simple JSONL helper functions and a retention
  helper, but no running memory service, compaction job, search index, or integration with
  active agents.
- Gated: Letta adoption decision remains separate.

### WI-5 — Escalation ladder
- Status: **not proven**.
- The untracked orchestrator has a draft `check_authority()` and `emit_escalation()`, but
  no running orchestrator is enforcing authority. Verify `org.json` separately before
  claiming role charters are wired.
- Gated: Nick ratification of final charters (one-time).

### WI-6 — Two-tier workers
- Status: **stub only**.
- `is_persistent_worker()` exists in the untracked scaffold, but no persistent
  mini-orchestrator worker loop is implemented or running.

### WI-7 — Cost estimate
- Done: _estimate_cost refined in ceo_reflect_llm.py (split prompt/completion, per-model rates for haiku/kimi/qwen/etc.; supports $20/wk tracking).
- HOW: Direct edit.

**Overall interop (UML reference in main handoff):**
- Ledger is the single source of truth (events for memory, spend, escalation, focus).
- Bus handles workers/jobs.
- Bridge for Hermes.
- Orchestrator should survey/reflect/act, but currently does not exist as a committed or
  running service.
- org.json for authority/roles/tiers.
- Sync cron for projections.
- Do not claim all pieces work together until WI-3 is implemented and witnessed.

## What is Gated for Nick (do not implement until Nick says go)
- Real Telegram tests (WI-1).
- Final org.json charter ratification (WI-5).
- Judging real complex worker output quality (WI-2).
- Live service restarts/tests (Hermes, orchestrator, sync).
- Secrets/credentials.
- Letta vs homegrown final call (WI-4).
- Premium model use under cap.
- Any physical/irreversible actions.

Save these in the main handoff or here. Implement only when Nick explicitly clears.

## Current State of Code (primary)
- `orchestrator/` is present only as untracked local scaffolding.
- `skills/` is present only as untracked local scaffolding.
- No CEO orchestrator process or service is active.
- Existing `scripts/ceo_reflect.py` / `scripts/ceo_reflect_llm.py` appear to be the
  current real reflection mechanism; the new orchestrator does not call the LLM.
- Do not close or mark WI-3/WI-4/WI-5/WI-6 complete based on the scaffold.

## Recommended Next for Claude (non-gated)
1. Decide whether to salvage the untracked scaffold or replace it with a clean WI-3
   implementation.
2. Implement the CEO orchestrator as a real committed service:
   survey → LLM-backed reflect → validated act → ledger events → memo/report writes.
3. Wire a talkable surface: dashboard work-room or `say.py` inbox must have a running
   reader and reply path.
4. Add witnesses before deployment: one-shot loop, LLM-off dry run, LLM-on reflect,
   authority rejection, and inbox reply.
5. Add a user systemd unit only after witnesses pass, then verify with `ps`, journal logs,
   and dashboard/report artifacts.
6. Update this handoff and the main architecture handoff with evidence, not status claims.

Use the main handoff as primary spec. Update both docs. Follow delegation flags. Commit often.

**Witness for this corrected handoff:** Audit found untracked scaffold, no running process,
no CEO orchestrator service, no LLM call inside the scaffold, and no wired chat receiver.
Treat prior "done" claims for WI-3/WI-4/WI-5/WI-6 as invalid until rebuilt and witnessed.

*Generated 2026-07-01 by Grok. Continue the covenant tree walk.*
