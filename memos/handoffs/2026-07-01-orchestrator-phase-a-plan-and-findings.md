# Orchestrator managers — Phase-A plan, findings & decisions

**Audience:** Claude Code / next agent session (and Nick)
**Status:** Plan + diagnosis. **Worker-runtime fix is the agreed prerequisite.** No orchestrator code authorized until the revised design (or Phase-A) is approved.
**Companion docs:**
- `memos/handoffs/2026-06-30-orchestrator-managers-vision.md` (Nick's original design intent — the north star)
- `memos/handoffs/2026-06-30-ceo-reflect-intention-vs-reality.md`
- `Projects-for-agents/frontier-orchestrator/org.json` (role tree)
- `agent-bus/registry.yaml` (delegation contract)

This memo captures the 2026-07-01 design conversation between Nick and Claude (Opus 4.8), after a session that fixed the dashboard honesty/plumbing layer.

---

## 0. Decisions locked in this conversation

- **Build a fresh dedicated orchestrator process** (NOT by generalizing Hermes/telegram-bridge). Hermes stays untouched as the router.
- **First role = CEO** (it already has a `sessions/ceo/` memory dir + reflect tools to wrap).
- **Heartbeat is active, not passive:** the orchestrator wakes on a periodic cadence **AND** on events. Each tick it surveys, reflects, may act, and writes memos. It is forward-looking (spin up research/exploration, propose initiatives, explore/exploit toward Nick's goals) — not just a reactive event handler.
- **Workers come in two tiers:** ephemeral bounded workers (witness-gated, end on completion) **and** persistent "smart" workers (mini-orchestrators with their own heartbeat + memory) for creative/wide-scope tasks. Both write memos.
- **Nick is the gate for almost nothing.** Replace `needs_nicholas` defaults with an **escalation ladder**: decide locally if within charter, else escalate up the org chain (worker → manager → CEO/COO/CTO), resolved there. Reaches Nick **only when physically required** (a secret/credential only he holds, a real-world or irreversible external action he must authorize, or a genuinely personal/strategic call). Never for triage sort order, commit-vs-merge, model choice, etc.
- **Chat surface = the dashboard work-room** (the per-issue chat thread next to the memo). Route messages to the **owning persistent agent**, carrying memo + thread context. (Replaces the earlier CLI-queue idea.)
- **Token cost:** auto-route effort — moderate model for routine survey ticks, escalate for hard thinking (per `model-routing-policy` skill / OpenRouter default).
- **"Safety/POL-010" = machine guardrails, NOT gating Nick:** caps (no unlimited workers, stay under $20/wk), dry-run (log-what-it-would-do), kill-switch (off button). None ask Nick anything.

---

## 1. CRITICAL FINDING — why delegated workers hang/fail

**Root cause (diagnosed 2026-07-01):** `agent-bus/scripts/bus.py::_run_claude` launches each worker as:

```
claude -p --output-format json --permission-mode acceptEdits --model <slug> <prompt>
```

with `ANTHROPIC_BASE_URL=http://127.0.0.1:3456` and `ANTHROPIC_AUTH_TOKEN=ccr-local` — i.e. **routed through CCR → OpenRouter open-weight models** (qwen3-coder, deepseek, kimi, per `worker_model.py` DEFAULTS).

Two problems:
1. **This is the exact path the Telegram bridge already abandoned.** Nick's CLAUDE.md note: the bridge *drops* the CCR base URL because "ccr→OpenRouter DeepSeek was flaky at tool-use." Workers never got that fix — so they drive Claude Code's agentic tool-loop with models that don't reliably do tool-use → they stall or fail fast. (CCR itself is healthy on :3456; the problem is the routed models + tool-use.)
2. **Errors are swallowed.** Recent workers (JOB-703, JOB-576) ended `status=blocked, kind=error, bottom_line="Worker failed: "` — empty error after the colon. `_run_claude` raises `RuntimeError((p.stderr or p.stdout or "claude failed")[:500])` but the real cause isn't captured/surfaced, so Nick couldn't see why they hung.

**Fix direction (agreed prerequisite, not yet done):**
- Run workers on a runtime proven to drive the agentic loop — the **Claude subscription** (the bridge pattern: drop CCR base URL, use OAuth/`auth.json`), or a model **verified** to handle tool-use through CCR.
- **Surface the real error** (capture full stderr/stdout/envelope; stop emitting empty "Worker failed: ").
- **Verification / definition of done:** a worker actually completes a real open issue (e.g. #78) end-to-end, witness exit 0, with a non-empty report.

**This blocks the entire orchestrator vision** — an orchestrator that delegates to workers that hang is useless.

---

## 2. SECONDARY FINDING — Hermes "no memory" (springs newborn)

`telegram-bridge/bridge.py::_run` does `if session_id: cmd += ["--resume", session_id]` — the resume mechanism exists. The "newborn every message" symptom is that the **per-chat session-id map is flaky**: almost certainly kept in memory (lost on every systemd restart) and/or reset when the failover backend swaps (Claude ↔ Codex/Grok). So it resumes sometimes, starts fresh other times.

**Fix:** persist the per-chat `chat_id → session_id` map to disk; reattach on restart; keep it stable across backend failover. Independent of the orchestrator, and the lesson (durable session persistence) carries directly into the orchestrator's own memory.

---

## 3. Revised target architecture (folds in Nick's feedback)

### 3.1 Two species (unchanged from vision, refined)
- **Orchestrator (manager):** persistent session, active heartbeat (periodic + events), memory, chat-while-work-runs, tool belt (status/spawn/steer/ledger/reflect). Does not usually own long coding.
- **Worker (implementer):** ephemeral bounded **OR** persistent-smart (creative/wide-scope). Branch-per-job, witness exit 0. Writes memos.

### 3.2 Active heartbeat loop (the CEO's "day")
On each tick (periodic cadence) and on events (your message, bus job completed/failed, gate, stall):
1. **Survey** — what's running, what's stuck, how are we tracking to Nick's goals.
2. **Reflect** — synthesize; what's going well/badly; what to try.
3. **Act** — within caps: spawn workers, kick off audits/research/exploration, propose initiatives, supersede own stuck jobs, exploit/explore.
4. **Document** — write memos (for Nick + for org memory) on what it saw, decided, and why.
5. **Stay talkable** — never block; answer Nick mid-job via status reads.

### 3.3 Escalation ladder (replaces "needs_nicholas" defaults)
```
worker decides within charter
   └─ can't? → manager (CEO/COO/CTO/...) decides within its charter
         └─ can't? → Nick — ONLY if physically required
```
"Physically required" = a secret/credential only Nick has · a real-world or irreversible external action Nick must authorize · a genuinely personal/strategic call. Everything operational (triage order, commit/merge, model choice, retries) resolves below Nick.

### 3.4 Chat surface
Dashboard work-room (per-issue chat next to memo) → routed to the **owning persistent agent**, carrying memo + prior-thread context. Lets Nick ask "hung or working?" and get a grounded mid-job answer; give unblocking info; steer/stop.

---

## 4. Memory design (NEEDS A PROPER SPEC before building)

Proposed layered model:
- **Per-agent working memory** — recent, self-compacted; "what I'm doing / already tried." Borrow the **MemGPT / Letta** pattern (self-editing working memory + archival memory with recall) rather than inventing.
- **Shared org memory** — append-only events + memos, **indexed/searchable**; any agent can see what the org has done.
- **Authoritative state** — bus + ledger remain the source of truth for "what is true right now."

### Memo lifecycle (Nick wants memos but fears bloat)
- **Tier by durability:** `durable` (decisions, charters) vs `ephemeral` (per-tick observations, TTL'd).
- **Rollup/compaction:** daily job summarizes the day's ephemeral memos → one digest; weekly rolls up dailies; raw archived/expired.
- **Split audience:** "for Nick" (surfaced as digests) vs "for agents" (org memory, searchable, not pushed).
- **Indexed + searchable** so agents query "what did we already try on X."

---

## 5. Phase-A plan (CEO orchestrator — pattern proof) — pending approval

**Location:** `nick2-dashboard/orchestrator/` (co-located with `ceo_reflect`/ledger; calls `bus.py` as subprocess like `pmo_dispatch`).

1. **Persistent session** `orchestrator/ceo_orchestrator.py` — long-lived loop as a **systemd user service** (`ceo-orchestrator.service`, auto-restart) with kill-switch (`CEO_ORCH_ENABLED=0`) and `--dry-run`.
2. **Active heartbeat** — periodic survey LLM call + event wakes; auto-routed effort.
3. **Chat surface** — dashboard work-room messages routed to this session (carry memo + thread context); non-blocking (spawning a worker returns immediately).
4. **Tool belt (non-blocking, escalation-gated):** `status_portfolio()` / `status_job(id)`, `bus_submit(...)`, `bus_supersede(id, reason)` (own jobs; else escalate, not to Nick), `ledger_append(event)`, `run_reflect()`.
5. **Memory** — per-agent working memory (Letta-style if specced) + writes to shared org memory; ledger/bus authoritative.
6. **Safety** — caps at tool boundary (reuse `compute_admission`); dry-run + kill-switch; `ceo_supervisor` runs in parallel (no removal yet).

**Definition of done:** spawn a worker on a real open issue, then mid-run Nick sends "status?" → grounded answer; "stop" → supersede; session never blocks.

**Out of scope for A:** org-driven spawn, child orchestrators, retiring the supervisor, full memo-lifecycle automation.

---

## 6. Recommended sequence (prerequisites first)

1. **Fix the worker runtime** (§1) — route off flaky CCR→OpenRouter; surface real errors. *Prerequisite; verifiable by a worker completing a real issue.* ← **Nick leaning to start here.**
2. **Fix Hermes session persistence** (§2).
3. **Spec the memory design** (§4) — small written design, Nick's ok.
4. **Build Phase-A CEO orchestrator** (§5).

---

## 7. State of the system as of this memo (already shipped, honest)

Dashboard honesty/plumbing layer was fixed earlier in the session (all pushed):
- ISSUE-BUS-001 closed (worker_model robust + regression test); gated queue hygiene (resolved items drop); DISPATCH-001 closed; FOCUS-001 no longer pollutes the active queue; ISSUE-24 (Telegram PA → Option B) and ISSUE-15 (skill tiers → Option A) resolved + recorded in `ai-agents-workspace/DECISIONS.md`.
- Memo systems unified on MKA style (no more progress-bar/404 memos).
- Audit C/D/F: bus-status counts live jobs only; reflect blocked-count excludes finished workers; pattern_detector test isolated → `witness_dashboard_honesty.py` PASSES.
- **Cost bug fixed:** `cumulative_weekly_spend_usd` now accumulates (was frozen at 0 — fake $0.00); sub-cent costs no longer rounded to $0.00. (Estimate is input-rate-per-token, slightly low — could refine with prompt/completion split.)
- **Sync scripts fixed:** the `git stash --include-untracked` + `stash pop || true` in both sync scripts silently dropped in-progress edits into orphan stashes. Replaced with defer-if-dirty + `--autostash`; cleared 33 orphan stashes.

Open big-ticket item: **B+E** = the orchestrator vision above. The fleet currently sits idle while 15 ready-for-agent issues are open, because (a) workers hang (§1) and (b) the dispatch loop re-churned landed work.

---

*Generated 2026-07-01 by Claude (Opus 4.8) with Nick. Persisted so the plan survives a context reset. No orchestrator code authorized by this document alone.*
