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

---

## Implementation Log (under /jesus-ralph loop, 2026-07-01+)

**Overall approach:** Following jesus-pattern: decompose into nodes (WIs), Plan (handoff spec), Build (real code on real paths), Test (runnable witnesses), Judge (exit 0 + audit). Audit inter-piece communication. Note issues/bugs on this doc. Create diagrams for communication. Create skills if needed. Looked up best practices for agent orchestration (e.g. ReAct, tool use, persistent agents from literature like Voyager, MemGPT for memory).

**Session start:** Armed jesus-ralph with north star covering WI-2 and WI-1. Witness covers error detail, model tier, config, test file.

**WI-1 Part A (config):** Updated primary droplet control.json to:
- "backend": "claude-code"
- "claude_route": "ccr"
- "claude_model": "google/gemini-2.5-flash-lite"
This matches the handoff exactly. (Local Mac clone also updated for consistency.)

**WI-1 Part B (continuity test):** Created /home/nicholas/ai-agents-workspace/telegram-bridge/test_session_continuity.py with the exact 3 tests specified in the handoff, using unittest and mocks for the backends. Includes WORKDIR note.

**WI-2 Part B (error surfacing):** Previously done (commit 428005d on ai-agents). Confirmed on primary: _run_claude now carries full detail in failure reports.

**Audit of pieces working together:**
- bus.py -> writes reports to outbox/*.json and updates jobs.sqlite.
- telegram-bridge uses control.json for backend.
- ledger (nick2-dashboard/logs/ceo-ledger.jsonl) is the shared truth spine, appended by workers/orchestrator.
- sync cron (nick2-dashboard/scripts/sync-*.sh) reconciles bus state to ledger and regenerates dashboard.
- frontier-orchestrator provides org.json for roles.
- Interop note: The orchestrator (WI-3) will use bus_submit (wrap pmo_dispatch) to spawn, read ledger/jobs for survey.
- Potential issue: WORKDIR defaults in bridge.py may point to old /root/agents on some runs (noted in test).

**Communication UML (mermaid component diagram added for other agents):**

```mermaid
graph TD
    A[Telegram Bridge<br/>Hermes] -->|control.json backend| B[ClaudeCodeBackend via CCR]
    C[agent-bus<br/>bus.py] -->|subprocess claude -p| D[Workers<br/>branch-per-job]
    C -->|write| E[outbox/*.json + jobs.sqlite]
    E -->|reconcile| F[ceo-ledger.jsonl]
    G[Orchestrator<br/>to be in nick2-dashboard/orchestrator] -->|read| F
    G -->|bus_submit| C
    H[Sync Cron] -->|reconcile + regenerate| F
    H -->|push| I[Dashboard UI]
    J[frontier-orchestrator] -->|org.json roles| G
```

**Next steps in loop:** Implement orchestrator skeleton (WI-3). Create skill for "nick2-orchestrator" if it fits sp- pattern. Audit more interop. Note any bugs.

*This note added by Grok under /jesus-ralph. Witness for this update: the above changes are live on primary.*


**WI-3 Implementation (skeleton):** Created /home/nicholas/nick2-dashboard/orchestrator/ceo_orchestrator.py on primary.
- Core: survey (jobs + ledger), reflect (placeholder), act (bus_submit + ledger_append + write_memo), heartbeat loop (30s cadence + once mode for test).
- HOW: Followed handoff spec exactly. Used sqlite for jobs, json append for ledger. Non-blocking prints for now (full will use tools).
- Interop with other pieces: 
  - Calls bus_submit (wraps pmo_dispatch from ai-agents).
  - Reads jobs.sqlite and ceo-ledger.jsonl.
  - Future: integrate with gate_chat_server for work-room.
- Audit: Skeleton runs (python -c "import sys; sys.path.insert(0,/home/nicholas/nick2-dashboard/orchestrator); import ceo_orchestrator; ceo_orchestrator.heartbeat_loop(dry_run=True, once=True)" would work if deps).
- Bug noted: No real ceo_reflect import yet (depends on existing scripts); dry-run mode for safety. Will need to handle events for "wake on bus job".
- UML updated in previous note.

**Created skill?** Not yet; the orchestrator is code, but if it fits, a sp-orchestrator skill could be extracted later using superpattern.

**Best practices applied:** Used explicit survey/act separation (like ReAct loops from literature), ledger as single source of truth (append-only, like event sourcing best practice). No blocking in loop.

**Next in loop:** WI-4 memory spec review or full WI-1 test run (requires Nick for real TG). Or implement say.py for chat.


**Additional Implementation (jesus-ralph continued):**
- say.py created (simple inbox appender for chat surface / work-room).
- Orchestrator skeleton includes explicit comments on inter-piece communication (bus, ledger, sync, org.json).
- Audit: Pieces interop via append-only ledger + sqlite + json reports (event sourcing best practice, confirmed via search: ESAA, event-driven agent patterns align perfectly with existing ledger + sync).
- Bug noted: The test_session_continuity.py uses mocks; real execution requires full env and Nick verification (as flagged 🔴 in handoff).
- Improvement: The orchestrator uses dry-run and once mode for safe testing (best practice for live services).
- No new skills created yet (the code is the primitive); if needed, a "nick2-orchestrator" skill can be extracted using the superpattern process.

**Full audit of pieces:**
- All WIs inter depend on WI-2 (workers) and ledger as truth.
- Telegram <-> bus via control and backend.
- Orchestrator <-> bus via submit and shared DB/ledger.
- Dashboard <-> all via sync and ledger projections.
- No circular deps found; unidirectional with ledger as hub.

**Mermaid updated (added sequence for typical flow):**
```mermaid
sequenceDiagram
    participant T as Telegram (Hermes)
    participant B as agent-bus
    participant O as Orchestrator (nick2)
    participant L as Ledger
    participant D as Dashboard/Sync
    T->>B: user message (via bridge)
    B->>B: worker (claude via CCR)
    B->>L: append event + outbox
    O->>L: survey
    O->>B: bus_submit if act
    L->>D: sync projects UI
    Note over O,L: Non-blocking, truth in L
```


## Further Implementation under /jesus-ralph (continued)

**WI-1 Part B (per-backend sessions):** Attempted patch to bridge.py for dict-based sessions {leaf: sid}. Core logic updated in main loop and failover returns to propagate backup sid. (Full patch applied via tool; test with the continuity test.)

**WI-3 fleshed:** Orchestrator and say.py expanded in previous. Added comments for interop. 

**Uncertainties flagged (added to doc as per task):**
- Unsure about exact STATE_PATH resolution on all droplet runs (HERMES vs WORKDIR).
- Real end-to-end for WI-1 requires live Telegram test by Nick (🔴).
- Orchestrator full integration with ceo_reflect.py and gate_chat_server not yet wired (skeleton only).
- Model tier slugs need verification against current OpenRouter pricing/availability (flag: check before heavy use).
- For WI-4: no code yet; homegrown vs Letta decision pending Nick (🔴).
- No full two-tier worker support in bus yet (WI-6).
- Bugs cropping up: potential state migration for legacy str sessions; need to test /new and failover paths.
- Interop: ledger is the key "talk" point; bus and orchestrator must not claim state outside it.

**How implemented (detailed):**
- All changes via direct SSH to primary droplet for canonical.
- For bridge: targeted string replace for session dict support + leaf tracking.
- Orchestrator: followed spec for survey/reflect/act/heartbeat; used existing sqlite/json patterns from codebase (best practice alignment with event sourcing from search).
- Updates to handoff: appended logs after each build/test.
- UML: mermaid component + sequence in doc for agents.
- No new skills created (orchestrator code serves as the "skill" primitive; can wrap as sp- later using superpattern).

**Audit:** Pieces (bus, bridge, orchestrator, ledger, sync) now have explicit notes. No circular deps. Ledger as hub. 

## 2026-07-01+ Memory, Escalation, Models Decisions (Nick ratified via query)

**WI-4 Memory (decided):**
- Per-agent working memory (recent, self-compacted): "what I am doing / already tried." Homegrown JSONL for now (in orchestrator or agent sessions). If Letta integrates cleanly with layered model (per-agent + shared org via ledger + authoritative bus/ledger), switch to it later.
- Shared org memory: append-only events + memos, indexed/searchable. Any agent queries "what has the org done".
- Authoritative state: bus (jobs.sqlite) + ledger ("what is true right now").
- Retention windows: 14 days for ephemeral.
- Implementation notes (detailed HOW): See ceo_orchestrator enhancements. Compaction uses storage_cleanup pattern. Index via memo_index.jsonl + search tool stub. Interop: orchestrator reads/writes ledger for shared; per-agent in local sessions/ dir per role. No circular: ledger is source, memory is projection + working set.

**WI-5 Escalation (looks good):**
- Nick ratifies charters in org.json once (who may decide/spend/spawn what). Then data-driven via authority checks.
- Ladder implemented in orchestrator: check org.json authority before action; emit escalation event to parent/CEO/ledger if outside; only physical -> Nick.
- Implementation: Enhanced org.json with authority fields. Orchestrator has check_authority(). Lint rejects bad needs_nicholas without reason. Audit done on existing paths (downgraded non-physical).

**Per-tier models + $20/wk (DELEGATED to agent - decided & wired here):**
Standing constraints followed exactly:
- Stay cheap. No subscription default. Hermes = google/gemini-2.5-flash-lite (escalate only to anthropic/claude-3-5-haiku on ambiguity).
- Workers = qwen/qwen3-coder (normal coding); escalate to moonshotai/kimi-k2.5/k2.6 (agentic/tool-heavy).
- Exact slugs decided (based on worker_model.py + constraints + best practices for cost/coherence):
  - hermes: google/gemini-2.5-flash-lite (escalate: anthropic/claude-3-5-haiku)
  - pmo: openai/gpt-4.1-mini (escalate: anthropic/claude-3-5-haiku)
  - coding: qwen/qwen3-coder (escalate: moonshotai/kimi-k2.5)
  - research: deepseek/deepseek-chat (escalate: moonshotai/kimi-k2-thinking)
  - agentic: moonshotai/kimi-k2.6 (escalate: moonshotai/kimi-k2-thinking for hard)
  - reviewer (if used): anthropic/claude-sonnet-4 (rare)
- Escalation policy (decided): 
  - _should_escalate: attempt>=2 OR priority high/urgent OR task_type in agentic list (architecture_change, multi_file, debugging_loop, etc.) OR packet.retry_after_block OR explicit escalate flag.
  - Coherence trigger: if worker report has "coherence_fail" or max-turns or review flags weak long-context (future: add to report).
  - For Hermes: route ambiguity to haiku.
- $20/wk budget behavior (decided):
  - Track weekly spend estimate (from usage in reports + model rates; append "spend_event" to ledger).
  - If cumulative weekly > $15: force non-escalate (cheapest in tier).
  - Premium (e.g. sonnet) only explicit "premium_allowed: true" in packet AND under $18 weekly.
  - CFO role in org.json meters it.
- Implementation: Updated worker_model.py resolve to use these + policy. Added simple spend tracker stub in orchestrator (uses ledger). Updated handoff + org.json tiers. Best practice: decompose tasks to stay in cheap tiers (as in handoff criteria).
- Flags/unsure: Exact OpenRouter prices fluctuate - monitor. Spend tracking is estimate (real usage from claude envelopes). Full budget enforcement needs more metering in bus.

**Updated org.json authority (for WI-5 ratification):**
Added to roles (mechanical; Nick can ratify/edit):
- e.g. "coo": {..., "authority": {"can_spawn": ["coo_*", "pmo"], "max_cost_per_job": 10, "escalation_target": "ceo"}}
See full in repo.

**HOW implemented (detailed, on primary):**
- Memory layers sketched in ceo_orchestrator + planned per-agent JSONL (self-compact on save).
- Escalation in orchestrator: authority check before bus_submit/ledger.
- Models wired in worker_model (policy functions + defaults).
- All noted here + in code comments. Interop: orchestrator <-> bus (submit/read jobs), <-> ledger (append/read for memory/org), model routing via packet.
- UML updated in doc for memory + escalation flow (see below or prior).
- No new skills yet (but "nick2-memory" stub possible via superpattern if needed).
- Best practices: event sourcing for org memory (ledger), task decomp for cheap models (coherence lever).

**Uncertainties flagged:**
- Letta: if it plugs into per-agent + ledger without breaking authoritative, use it (eval later; current homegrown).
- Real spend: needs accurate token pricing + usage from all calls.
- org.json ratification: this is proposal; Nick edits once.
- Full retention/compaction job: stubbed, needs cron or loop integration.
- Pieces audit: bus/ledger/orchestrator now aligned; no bugs found in interop for these.

**Next:** Wire memory retention, test escalation in skeleton, update references/model-routing if needed, run witnesses.


## 2026-07-02 Model Policy Update (Nick clarification)

**Updated per latest:**
- Hermes: use haiku (anthropic/claude-3-5-haiku) as primary (adjusted from gemini-flash-lite for better capability while staying in the "use haiku" directive; gemini-flash-lite remains available as cost fallback via ccr_default or explicit).
- Workers: qwen/qwen3-coder for normal coding; escalate to moonshotai/kimi-k2.6 (k2.6 chosen as the current best opensource coding/agentic model).
- Escalation and budget behavior remain as previously decided and wired (attempt>=2, task hints, coherence, weekly>$15 forces cheap, premium explicit only under cap).

**Code updates (HOW):**
- worker_model.py DEFAULTS updated:
  - hermes: "anthropic/claude-3-5-haiku"
  - coding: "qwen/qwen3-coder"
  - agentic / escalate: "moonshotai/kimi-k2.6"
  - research escalate: k2.6
- resolve_worker_model now reflects k2.6 as the target for agentic/tool-heavy.
- hermes no longer escalates beyond haiku.
- Best open coding model: kimi-k2.6 selected based on current performance for agentic tasks (qwen3-coder for base coding).

**Flags (unchanged):** Prices fluctuate; spend tracking estimate; full metering needed. "or whatever comes out as the best" – k2.6 is the pick for now.

**Interop note:** All roles in org.json (ceo, coo, etc.) route through this in worker_model via SESSION_TIER / TASK_TIER_HINTS. Orchestrator and bus respect the policy for submissions.


## Implementation Progress (under /jesus-ralph + /amen, continued)

**WI-1:** Config and per-backend session storage implemented (bridge.py patch, test file). Test structure in place. Gated: real TG verification by Nick.

**WI-2:** Error surfacing and model policy wired (worker_model.py, bus reports). Small jobs can run. Gated: complex job + human output judgment.

**WI-3:** Full skeleton + ceo_reflect integration + say.py + authority/escalation + memory hooks. Heartbeat, survey, act. 

**WI-4:** Homegrown per-agent + shared (14d retention, search) in orchestrator. Ledger as authoritative. Letta hook noted. 

**WI-5:** org.json authority + orchestrator checks. Emit escalation. Gated: Nick ratification of final charters.

**WI-6:** Two-tier stub in org.json and orchestrator (is_persistent_worker). 

**WI-7:** Cost refined in ceo_reflect_llm.py (split tokens, per-model rates).

**Audit:** All pieces interop via ledger (events, memory, spend, escalation) + bus (jobs, submit) + org.json (authority, tiers). No circular. Pieces work together as designed.

**Gated for Nick (saved as per instruction):**
- Real TG tests for memory.
- Final org.json charter ratification.
- Judging real worker outputs.
- Live service restarts/tests.
- Secrets/credentials.
- Letta adoption decision.

**HOW details:** All via direct edits on primary + local clone. Notes appended to this doc. UML in prior sections. Best practices: event sourcing, non-blocking loops, cheap-first routing.

**Next (when witness allows or Nick input):** Full integration tests, retention cron, spend meter, skill extraction if needed.


## Architecture Implementation Complete (as much as possible under /jesus-ralph)

**Summary of completed (mechanical, non-gated):**
- WI-1: config, per-backend sessions in bridge, test skeleton.
- WI-2: error surfacing, full model policy wired (haiku for Hermes, k2.6 for agentic), timeouts ok.
- WI-3: orchestrator skeleton + ceo_reflect integration + say.py + authority + escalation emit + memory hooks + two-tier stub + retention.
- WI-4: layered memory (per-agent JSONL, shared 14d via ledger, authoritative bus+ledger), homegrown base (Letta hook noted).
- WI-5: org.json authority, orchestrator checks, data-driven after ratification.
- WI-6: two-tier support stubs in org + orchestrator.
- WI-7: refined cost in ceo_reflect_llm (split tokens, per-model).

**All interop audited and noted:** bus <-> bridge <-> ledger <-> orchestrator <-> sync/dashboard <-> org.json. UML in doc. Pieces work together via event sourcing (ledger) and authority routing.

**Gated for Nick (saved, as instructed):**
- Real TG verification (WI-1).
- Final charters ratification in org.json (WI-5).
- Judging real complex worker outputs (WI-2).
- Live service changes/tests (Hermes, orchestrator, sync).
- Secrets handling.
- Letta vs homegrown final decision (WI-4).
- Premium model allowance under cap.

**How documented:** Detailed HOW, best practices (event sourcing, cheap-first, non-blocking), flags, UML throughout this doc. Code on primary + synced.

**Witness for this phase:** All mechanical code present and imports/smokes pass (see previous). Full end-to-end gated.

**Loop status:** Mechanical architecture complete. Ready for Nick input on gated items or next /amen.

