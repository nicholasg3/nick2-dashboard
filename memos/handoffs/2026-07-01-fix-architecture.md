# Nick2 — Fix & Build Architecture (delegatable execution doc)

**Author:** Claude (Opus 4.8) with Nick, 2026-07-01
**Purpose:** A detailed, self-contained spec another agent can execute. Nick is low on credits and may hand this to other agents. Each work item has: root cause, exact files/functions, the change, an acceptance test (witness), and a **delegation flag** (🟢 any competent coding agent / 🟡 needs care or judgment / 🔴 needs Nick or cannot be safely delegated).
**Companion docs (read first):**
- `memos/handoffs/2026-06-30-orchestrator-managers-vision.md` (Nick's north-star intent)
- `memos/handoffs/2026-07-01-orchestrator-phase-a-plan-and-findings.md` (decisions + findings)
- `memos/handoffs/2026-06-30-ceo-reflect-intention-vs-reality.md`

**Environment:** droplet `agents-sgp01` (Tailscale `100.67.143.88`, key `~/.ssh/molt_droplet`, user `nicholas`). Repos: `nicholasg3/nick2-dashboard` (dashboard, ledger, orchestrator-to-be) and `nicholasg3/ai-agents-workspace` (agent-bus, telegram-bridge, DECISIONS.md). Both are git-canonical; the droplet auto-commits/pushes via cron (now safe — see WI-0 context).

**Global rule for any agent working here:** commit your changes promptly (the sync cron now *defers* when non-generated files are dirty rather than stashing them — but don't leave work uncommitted for long). Never push to `main` of a repo you haven't been asked to; both these repos auto-push from the droplet, so just commit and let sync handle it, or `git pull --rebase --autostash` then push.

---

## 0. System map (so a cold agent understands the pieces)

| Piece | Path | Role |
|------|------|------|
| **agent-bus** | `ai-agents-workspace/agent-bus/` | Job queue. `scripts/bus.py` submits/schedules/runs **workers**. SQLite `jobs.sqlite`. Workers = `claude -p` subprocesses, branch-per-job, witness exit 0. |
| **telegram-bridge (Hermes)** | `ai-agents-workspace/telegram-bridge/bridge.py` | 24/7 Telegram PA. Persistent `claude --resume` per chat. systemd `telegram-bridge`. |
| **dashboard** | `nick2-dashboard/` | GitHub Pages + live API. `logs/ceo-ledger.jsonl` = append-only truth. `scripts/` = reflect/reconcile/export/memo generators. `dashboard/*.html` + `app.js` = UI. Gate server `gate_chat_server.py` (:8788) serves live API + chat rooms. |
| **CEO reflect stack** | `nick2-dashboard/scripts/ceo_reflect*.py`, `ceo_supervisor.py` | Current bounded "CEO" — batch reflection + mechanical unstick. To become **tools** inside the orchestrator. |
| **frontier-orchestrator** | `ai-agents-workspace/Projects-for-agents/frontier-orchestrator/` | Parallel autonomous lane + `org.json` role tree. |
| **sync cron** | `nick2-dashboard/scripts/sync-*.sh` | Every 3/15 min: reconcile ledger↔bus, regenerate, push. |

**Authority of truth:** `logs/ceo-ledger.jsonl` (events) + `jobs.sqlite` (bus state). The dashboard is a *projection*; agents must commit truth via ledger events, never claim state in chat.

---

## WI-1 — Hermes "no memory" (springs newborn). 🟢 + 🟡

### Root cause (PROVEN 2026-07-01)
`bridge.py` active backend is selected by `control.json` → `"backend": "failover"` → `FailoverBackend` (**Grok primary** → Claude → Codex). But `grok -p --output-format json` produces **no parseable JSON** on this box (broken/unconfigured — empirically returns empty/non-JSON). So:
1. Every message: `GrokBackend.send` fails → raises `BackendError`.
2. `FailoverBackend.send` falls back with **`self.claude.send(None, text)`** — `session_id` hardcoded to `None` → **fresh Claude conversation every time** (no `--resume`).
3. It returns `(reply, session_id)` using the **original** sid and **discards** Claude's new sid (`reply, _ =`), so the working session id is never stored.
Net: newborn every message. The stored `state.json` sid (`019f1836…`) is a stale Claude UUID Grok could never resume.

Verified facts: `claude -p --output-format json` envelope **does** contain `session_id` (snake_case); `ClaudeCodeBackend.send` already reads `data.get("session_id")` correctly (bridge.py ~L287) and `--resume`s on the next turn. So Claude-primary already has correct continuity logic — the bug is purely *which backend is primary* + *how the failover passes/stores sids*.

### Fix (two parts)

**IMPORTANT model constraint (Nick, 2026-07-01):** do NOT use Claude-on-subscription as primary — Nick runs out of Claude credits, and Claude-via-OpenRouter is too expensive. Hermes must run a **cheap** model. Per the `model-routing-policy` skill (`references/model-routing.yaml`), **Hermes tier = `google/gemini-2.5-flash-lite`** (default), escalate to **`anthropic/claude-3-5-haiku`** only on routing ambiguity. The memory fix is **model-agnostic**: `--resume`/`session_id` is a Claude-CLI *local* construct (the CLI stores transcripts in `~/.claude` and emits `session_id` regardless of which model CCR routes the API call to), so continuity works with a cheap routed model.

**Part A — make the Claude-CLI backend primary, routed cheaply via CCR (NOT subscription). 🟢**
The newborn bug is that `backend: "failover"` = Grok-primary, and Grok is broken → falls to `claude.send(None,…)` every turn. Fix = use the `claude-code` backend (the `claude` CLI, which has correct `--resume`/`session_id` continuity) but routed through CCR to a cheap model:
- File: `ai-agents-workspace/telegram-bridge/control.json`:
  - `"backend": "claude-code"` (single backend; or `"claude+codex"` if a Codex backup is wanted — but see Part B caveat, Codex is yet another runtime/cost).
  - `"claude_route": "ccr"` (so `ClaudeCodeBackend._run` sets `ANTHROPIC_BASE_URL=http://127.0.0.1:3456` and routes the slug through CCR → OpenRouter, NOT the subscription).
  - `"claude_model": "google/gemini-2.5-flash-lite"` (policy default for Hermes).
- Also align `~/.hermes/.env`: `BRIDGE_MODEL` currently `sonnet` (subscription-ish) — set it to the cheap slug or leave `claude_model` in control.json to win. Verify which the code prefers (`ctl.get("claude_model") or os.environ.get("BRIDGE_MODEL")` — control.json wins, good).
- `load_control()` is read live and `main()` re-makes the backend on change (~L635); restart `systemctl restart telegram-bridge` to be safe.
- **Why this fixes memory:** `ClaudeCodeBackend.send` resumes with the stored sid and returns the CLI's real `session_id` (emitted locally, model-agnostic — verified: `claude -p --output-format json` envelope contains `session_id`), which `main()` persists (L641–657). The stale `019f1836` resumes or auto-refreshes.
- **🟡 Tool-use caveat to VERIFY:** Nick's older CLAUDE.md note says CCR→OpenRouter was "flaky at tool-use," which is why the bridge had moved to subscription. The routing policy nonetheless designates Hermes = gemini-2.5-flash-lite via the CCR plumbing. So: after switching, **test the PA tools** (email read/draft, calendar, contacts) end-to-end. If gemini-2.5-flash-lite is too weak at tool-calling, bump `claude_model` to the escalate tier `anthropic/claude-3-5-haiku` (still cheap via OpenRouter, genuinely Haiku-smart — exactly the "~Haiku but not expensive" Nick wants). Do NOT fall back to subscription. `OpenRouter auto` is a third option if a fixed slug underperforms.

**Part B — make failover continuity-safe (so backup turns don't lose/poison memory). 🟡**
Both `FailoverBackend` and `ClaudeCodexFailoverBackend` have the same latent bug: on fallback they call `backup.send(None, text)` and `reply, _ =` (discard the backup's sid), returning the *primary's* old sid. This means a backup turn is amnesiac and its context is lost. Robust fix = **per-backend session storage**:
- Change `state["sessions"][chat_id]` from a single string to a dict `{backend_leaf_name: sid}` (migrate: if it's a `str`, treat as the claude sid).
- Failover backends resume each leaf with *its own* stored sid and return the leaf that actually answered + its new sid, so `main()` can store per-leaf.
- Cleanest contract change: have failover `.send` return `(reply, new_sid, backend_leaf_name)` (or a small dict), and `main()` stores `sessions[chat_id][leaf] = new_sid`. Keep single-backend `.send` signature backward-compatible (leaf = self.name).
- **Acceptance test (witness):** add `telegram-bridge/test_session_continuity.py`:
  1. `ClaudeCodeBackend().send(None, "remember codeword X")` → returns non-empty `sid1`.
  2. `.send(sid1, "what was the codeword?")` → reply contains `X`. (Asserts resume works.)
  3. Simulate primary failure in the failover backend (monkeypatch primary to raise `BackendError`) → assert the backup runs *and* its sid is captured & returned (not `None`/discarded).
  - **NOTE for the executing agent:** run the test with the bridge's real `WORKDIR` (`cd telegram-bridge` and ensure `WORKDIR=/home/nicholas/ai-agents-workspace`; do NOT let it default to `/root/agents`, which is an archived path and will throw `PermissionError`). This artifact bit the original author's quick test — it is *not* a bridge bug, but fix the `WORKDIR` default in `bridge.py`/env if it still points at `/root/agents`. 🟡
- **Definition of done:** Nick sends two Telegram messages minutes apart; the second clearly remembers the first, across a `systemctl restart telegram-bridge` in between.

### Delegation note
🟢 Part A is trivial and safe. 🟡 Part B touches a **live** bot and the per-backend state migration — do it behind the test, restart carefully, and watch `journalctl -u telegram-bridge -f` for one real exchange. 🔴 Nick must do the final human check (send real Telegram messages) — an agent cannot send as Nick.

---

## WI-2 — Workers hang / fail with empty errors (THE prerequisite). 🟡 + 🔴 verify

### ⚡ STATUS UPDATE (2026-07-01, Claude/Opus) — partially done + key finding
- **WI-2B (surface real errors) is DONE** — commit `428005d` in `ai-agents-workspace`. `_run_claude` now raises with `rc` + **both** stderr/stdout, guards the unwrapped `json.loads`, and labels in-band errors with their subtype. No more empty `"Worker failed: "`.
- **WI-2A diagnostic RUN (empirical):** submitted a tiny no-op `coding_worker` job (JOB-20260630-234, "report the branch, change nothing") on the **cheap CCR→qwen path** with a 150s cap. It **COMPLETED successfully** — correct branch reported, clean tree, no hang, no error.
- **What this means:** the worker runtime is **NOT universally broken.** Small, well-scoped tasks succeed on the cheap path. The earlier hangs (ISSUE-80, ISSUE-BUS-001) were **complex / multi-file / tool-heavy** jobs — i.e. the **coherence failure mode** (weak long-context model loses the thread on big tasks), not a plumbing failure. This **reframes the fix**: the priority is *task decomposition + output gating + model escalation for complex jobs* (the blast-radius lever), NOT a runtime swap. The CCR→OpenRouter path itself is fine for bounded work.
- **Next for delegated agents:** re-run a *complex* job (e.g. a real multi-file issue) and read the now-visible error to confirm it is a coherence/agentic-loop failure (look for max-turns, tool-call loops, or incoherent diffs), then apply WI-2A escalation (route to Kimi agentic tier) + WI-3 decomposition.

### Root cause (diagnosed 2026-07-01)
`ai-agents-workspace/agent-bus/scripts/bus.py::_run_claude` launches workers as:
```
claude -p --output-format json --permission-mode acceptEdits --model <slug> <prompt>
```
with `env ANTHROPIC_BASE_URL=http://127.0.0.1:3456` + `ANTHROPIC_AUTH_TOKEN=ccr-local` → **routed through CCR → OpenRouter open-weight models** (`worker_model.py` DEFAULTS: qwen3-coder, deepseek, kimi). Two failures:
1. **Wrong runtime for agentic tool-use.** This is the exact path the Telegram bridge *abandoned* (CLAUDE.md: "ccr→OpenRouter DeepSeek flaky at tool-use"). Open-weight models driving Claude Code's tool loop stall or fail. (CCR daemon on :3456 is healthy; the *routed models* are the problem.)
2. **Errors swallowed.** Recent workers (JOB-703, 576) ended `status=blocked, kind=error, bottom_line="Worker failed: "` — empty. `_run_claude` raises `RuntimeError((p.stderr or p.stdout or "claude failed")[:500])`; the real cause isn't reaching the outbox/ledger.

### Fix
**Cost constraint (Nick):** workers must stay on **cheap OpenRouter models via CCR** (subscription credits run out; OpenRouter-Claude is too expensive). Per `model-routing-policy`: coding tier = `qwen/qwen3-coder`, agentic/tool-heavy escalate = `moonshotai/kimi-k2.5` / `kimi-k2.6`, research = `deepseek/deepseek-chat`, reviewer (rare) = `anthropic/claude-sonnet-4`. So the fix is NOT "switch to subscription" — it's "make the cheap CCR path actually drive tool-use, and surface why it currently fails."

**Part A — diagnose & pick a tool-capable cheap model. 🟡 (do Part B FIRST to see the real error)**
- The hang is open-weight models failing Claude Code's agentic tool-loop through CCR. `qwen3-coder` is the *default* coding slug but may be weak at multi-step tool-use; the policy's **agentic escalate is `kimi-k2.5/k2.6`** precisely for "hard coding, multi-step tools." So: for tool-heavy issue work, route `coding_worker` to the **agentic tier (kimi)** rather than bare qwen, or escalate qwen→kimi on tool-use failure.
- Add a `runtime`/`model_tier` knob in `worker_model.py` so the model is chosen per task difficulty; **verify each slug on OpenRouter** before relying on it (policy marks qwen3-coder/kimi as "verify before spend").
- Keep `--permission-mode acceptEdits`, branch-per-job, witness exit 0.
- **🔴 Nick/lead decision:** confirm the per-tier model choices and the $20/wk cap behavior (drop a tier before burning frontier tokens). Subscription/Sonnet-reviewer only as a rare, explicit last resort — never the default.

**Model-selection criteria for coding workers (from Nick's Grok experience):** the dominant failure mode of cheap coders is **weak long-context coherence** ("shorter memory") — a change in file A is forgotten by the time file B is edited, producing locally-plausible but globally-inconsistent edits (bug litter). Two levers, which compound:
1. **Pick for coherence, not just price.** For multi-file / tool-heavy work prefer the large-context agentic tier (**Kimi k2.5/k2.6**) over bare `qwen3-coder`; reserve Opus/premium for genuinely hard, high-stakes tasks only.
2. **Contain the blast radius (the stronger, free lever).** Have the orchestrator **decompose into small, single-concern jobs** that fit a cheap model's working set, and **always gate output** (witness exit 0 + a `/code-review` pass) so an incoherent edit is caught before merge. A weak-memory model on a tiny, reviewed task is fine — cheaper and more robust than paying for a bigger model on everything.

**Part B — surface real errors. 🟢 ✅ DONE (commit `428005d`)**
- In `_run_claude`, when `p.returncode != 0` or `data.get("is_error")`, capture **full** `stderr` + `stdout` + envelope `result`/`error`/`subtype` into the failure report and ledger (truncate generously, e.g. 2000 chars). Kill the empty `"Worker failed: "`.
- Add a `failure_detail` field to the outbox report and a `worker_error` event to the ledger so the dashboard/orchestrator can show *why*.

**Part C — timeouts. 🟢**
- Confirm `dpolicy.worker_timeout_sec()` is sane (e.g. 15 min default, longer only for `heavy_coder`). A subprocess timeout should produce `kind=timeout` (already handled), not an indefinite hang.

### Acceptance test (witness) 🟡/🔴
- Submit a real, small, well-scoped open issue end-to-end (candidate: **#78** "host dashboard on droplet with nginx basic auth" is medium; a smaller doc/test task is safer for a first proof). Verify: worker runs, produces a branch with a diff, witness exits 0, outbox `status=completed` with a non-empty report, ledger shows completion.
- 🔴 A human (or a trusted agent) should sanity-check the worker's diff before merge — an autonomous "completed" is not proof of correctness.

### Delegation note
🟡 The runtime switch is the crux and needs care (don't break the bridge's shared auth). 🔴 The cost trade-off and the "is the produced work actually good" check are Nick/human calls.

---

## WI-3 — CEO Orchestrator, Phase A (the vision, minimal proof). 🟡

**Goal:** one persistent CEO manager that Nick can chat with *while a worker runs*, that surveys/reflects/acts on a heartbeat, and commits truth via tools. Depends on WI-2 (workers must actually run).

### Location & runtime
- New package `nick2-dashboard/orchestrator/` (co-located with reflect/ledger; calls `bus.py` as subprocess like `pmo_dispatch` does).
- Runtime: **fresh dedicated process** (Nick's choice — *not* generalizing Hermes). Run as a **systemd user service** `ceo-orchestrator.service` (auto-restart) with:
  - kill switch `CEO_ORCH_ENABLED=0`
  - `--dry-run` (log intended tool calls, take none)

### Core loop (`orchestrator/ceo_orchestrator.py`)
**Active heartbeat (Nick's explicit requirement — NOT idle-only):** wake on a **periodic cadence AND on events**. Each tick:
1. **Survey** — read `jobs.sqlite`, `bus-live.json`, `ceo-queue.json`, recent ledger, open GitHub issues. What's running/stuck; progress toward Nick's goals.
2. **Reflect** — call `ceo_reflect`/LLM as a *tool*; synthesize.
3. **Act** (within caps): spawn workers, kick off audits/research/exploration, propose initiatives, supersede own stuck jobs, explore/exploit.
4. **Document** — write memos (for Nick + org memory) on what it saw, decided, why.
5. **Stay talkable** — never block; answer Nick mid-job via status reads.
- Events that wake it: Nick message, bus job completed/failed, ledger `needs_nicholas` (rare — see WI-5), detected stall.
- **Effort routing:** moderate model for routine survey ticks; escalate to a stronger model for synthesis/decisions. Use the `model-routing-policy` skill / OpenRouter auto. (Addresses token cost.)

### Tool belt (all NON-BLOCKING, escalation-gated)
| Tool | Impl |
|------|------|
| `status_portfolio()` / `status_job(id)` | read `jobs.sqlite` + `bus-live.json` + `ceo-queue.json` (read receipts; never join worker context) |
| `bus_submit(...)` | wrap `pmo_dispatch.submit_bus_job`; return `job_id` immediately |
| `bus_supersede(id, reason)` | jobs it spawned; otherwise escalate (NOT to Nick) |
| `ledger_append(event)` | commit `focus_snapshot`/queue truth so dashboard stays honest |
| `run_reflect()` | wrap `ceo_reflect.py` |
| `write_memo(tier, audience, body)` | org-memory + Nick digest (see WI-6) |

### Chat surface — wire the dashboard work-room (Nick likes this UX)
- The per-issue chat thread (`dashboard/work-room.html` + `gate_chat_server.py`) should route messages to the **owning persistent orchestrator**, carrying the memo + prior thread as context.
- Today it dispatches a *new worker* / talks to an ephemeral one that can't do Q&A. Change: work-room messages append to the owning agent's inbox (a `reports/orchestrator/<role>-inbox.jsonl`) and the agent's reply posts back to the thread.
- For Phase A, a minimal CLI (`orchestrator/say.py`) is acceptable as a fallback to prove the loop; full work-room wiring is Phase D.

### Memory (Phase A minimal; full design in WI-4)
- Per-agent working memory file under `agent-bus/sessions/ceo/memories.jsonl` (existing pattern), compacted when long. Ledger/bus remain authoritative.

### Safety (machine guardrails — these do NOT ask Nick)
- Caps at the tool boundary: reuse `compute_admission` (max delegations, no dispatch on `deferred-work.json`, budget ≤ $20/wk).
- Start in `--dry-run`; then enable with the kill switch available.
- `ceo_supervisor.py` keeps running in parallel during transition (don't remove).

### Definition of done (maps to vision §15)
Spawn a worker on a real open issue; mid-run Nick sends "status?" → grounded answer; "stop" → supersede; session never blocks; orchestrator writes a memo about what it did and why.

### Delegation note
🟡 Substantial but well-scoped if WI-2 is done first. The non-blocking discipline and "commit truth via tools, never hallucinate state" are the easy-to-get-wrong parts — emphasize in the worker's brief.

---

## WI-4 — Memory architecture (spec before heavy build). 🟡 + 🔴 design-review

Nick: each agent needs its own memory AND visibility into what the org has done; he loves memos but fears bloat.

### Layered model
1. **Per-agent working memory** — recent, self-editing/compacted. Borrow **MemGPT/Letta** (self-editing working memory + archival memory with recall) rather than inventing. Library option: `letta` (formerly MemGPT) — evaluate vs a lightweight homegrown JSONL+compaction. 🔴 Nick/lead should pick "adopt Letta" vs "minimal homegrown" (dependency + runtime trade-off).
2. **Shared org memory** — append-only events + memos, **indexed/searchable** (the ledger is the event spine; add a memo index). Any agent can query "what has the org done / already tried on X."
3. **Authoritative state** — `jobs.sqlite` + `ceo-ledger.jsonl`. Source of truth for "what is true now." Memory is for "what did I try / learn."

### Memo lifecycle (anti-bloat)
- **Tier by durability:** `durable` (decisions, charters — kept) vs `ephemeral` (per-tick observations — TTL, e.g. 14 days).
- **Rollup/compaction job:** daily → summarize the day's ephemeral memos into one digest; weekly → roll up dailies; raw archived then expired (reuse the existing `storage_cleanup.py` RETENTION pattern from the workspace).
- **Split audience:** `for_nick` (surfaced as a short digest, e.g. via the morning Telegram brief) vs `for_agents` (org memory, searchable, not pushed).
- **Index + search:** a small `memo_index.jsonl` (id, tier, audience, tags, ts, path) + a `search_memos(query)` tool so agents don't re-read everything.

### Delegation note
🟡 buildable. 🔴 the Letta-vs-homegrown decision and the retention windows are Nick/lead calls — flag, propose defaults (homegrown JSONL + Letta later; ephemeral TTL 14d), let Nick confirm.

---

## WI-5 — Escalation ladder / gate minimization. 🟡

Nick: be the gate for **almost nothing** — only when *physically required*.

### Design
Replace the current "default `needs_nicholas: true`" pattern with an **escalation ladder**:
```
worker decides within its charter
  └─ outside charter? → its manager (PMO/CTO/COO) decides within ITS charter
        └─ still outside? → CEO
              └─ ONLY if physically required → Nick
```
"Physically required" = (a) a secret/credential only Nick holds; (b) a real-world or irreversible external action Nick must authorize (spend a real card, publish publicly, delete data, send external email); (c) a genuinely personal/strategic call (e.g. ISSUE-24 Telegram posture). **Never** for: triage sort order, commit-vs-merge, retries, model choice, internal refactors.

### Implementation
- Add `authority` to `org.json` per role (what each may decide/spend/spawn) and an `escalation_target` (parent).
- The orchestrator tool boundary checks authority: if an action is within charter → do it; else → emit an `escalation` event addressed to the parent role (not a `nick_gate`).
- Reserve `nick_gate` strictly for the three "physically required" categories; add a lint/guard that rejects `needs_nicholas: true` events that don't carry a `physically_required_reason`.
- Audit existing code paths that set `needs_nicholas`/`nick_gate` and downgrade the operational ones to in-charter or parent-escalation.

### Delegation note
🟡 mechanical once `org.json.authority` is defined. 🔴 Nick should ratify the *charters* (who may decide/spend what) once — that's a one-time governance input, then it's data-driven.

---

## WI-6 — Two-tier workers. 🟡 (after WI-2/WI-3)

- **Ephemeral bounded worker** — current bus worker; ends on completion; witness exit 0.
- **Persistent smart worker** — for creative/wide-scope tasks: a mini-orchestrator (own heartbeat + memory + tool belt, smaller charter than CEO). Same runtime as the orchestrator (WI-3), spawned by a manager, can itself spawn ephemeral workers, writes memos.
- `org.json` marks a role/task as `worker_kind: ephemeral | persistent`.

---

## WI-7 — Cost estimate refinement (small). 🟢

`ceo_reflect_llm.py::_estimate_cost` uses a flat input-rate-per-token (slightly low — ignores higher completion-token price). Refine to split `prompt_tokens`/`completion_tokens` with per-model in/out rates (or read OpenRouter's returned cost when available via `usage` with `include`). Already-fixed today: cumulative accumulation + sub-cent display. 🟢

---

## Recommended execution order

1. **WI-2** (workers actually run) — *prerequisite for the whole vision*. 🟡 + 🔴 verify.
2. **WI-1** (Hermes memory) — independent, high user value, mostly 🟢.
3. **WI-4 spec** (memory design) — 🔴 quick decision, then build.
4. **WI-5** (escalation ladder) — 🟡, governance input from Nick once.
5. **WI-3** (CEO orchestrator Phase A) — 🟡, depends on 1–4.
6. **WI-6**, **WI-7** — follow-ons.

---

## What CANNOT be safely delegated (flagged for Nick)

- 🔴 **Sending real Telegram messages** to verify Hermes memory — only Nick can act as the human.
- 🔴 **The per-tier model choices & $20/wk cap behavior** (WI-2A, WI-1): which cheap OpenRouter slug per role, and when (if ever) to spend on a premium tier. Constraint from Nick: stay cheap — subscription credits run out, OpenRouter-Claude is expensive. Hermes = gemini-2.5-flash-lite (escalate haiku); workers = qwen3-coder/kimi; never default to subscription.
- 🔴 **Judging whether autonomous worker output is actually good** before merge — needs human/trusted review; "witness exit 0" proves it ran, not that it's right.
- 🔴 **Ratifying role charters/authority** (WI-5) and **Letta-vs-homegrown memory** (WI-4) — one-time governance/architecture decisions.
- 🔴 **Anything touching credentials/secrets** in `~/.hermes/.env`, OAuth `auth.json`, or external publishing — physically requires Nick.
- 🟡 **Live-bot changes** (Hermes, the sync cron, the orchestrator service): delegate only to an agent that will test behind a witness and watch `journalctl`/logs after restart — these are running services, not static code.

---

## Already shipped this session (context, don't redo)

Dashboard honesty/plumbing fixed & pushed: ISSUE-BUS-001 closed (+regression test), gated-queue hygiene (resolved/idle items drop; `gated()` hardened), DISPATCH-001 closed, FOCUS-001 no longer pollutes the active queue (supervisor cycle = `completed`, not `blocked`), ISSUE-24 → Option B and ISSUE-15 → Option A resolved + recorded in `ai-agents-workspace/DECISIONS.md`. Memos unified on MKA style (no 404s/progress-bars). Audit C/D/F: bus-status counts live jobs; reflect blocked-count excludes finished workers; pattern_detector test isolated → `witness_dashboard_honesty.py` PASSES. Cost bug fixed (cumulative now accumulates; sub-cent shown). Sync scripts fixed (defer instead of stash-pop; 33 orphan stashes cleared).

**2026-07-01 follow-ups (this doc's WIs):** WI-2B shipped (worker errors now surfaced, `428005d`). WI-2A diagnostic: a tiny `coding_worker` job completed cleanly on the cheap CCR→qwen path → runtime works for bounded tasks; hangs are the complex-task coherence mode, so prioritize decompose+gate+escalate (see WI-2 STATUS UPDATE). Coherence model-selection criteria added to WI-2.

---

*Generated 2026-07-01 by Claude (Opus 4.8). This document authorizes planning and scoped implementation by delegated agents within the delegation flags above; 🔴 items require Nick.*
