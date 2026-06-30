# Handoff: CEO reflection + dashboard honesty (2026-06-30)

**Audience:** Claude Code / next agent session  
**Repos:** `nick2-dashboard` (primary), `ai-agents-workspace` (bus + frontier cross-wiring)  
**Policy:** POL-010 (CEO reflection), POL-002 (WIP heartbeat), POL-003 (bus–ledger coupling), POL-009 (dashboard honesty witness)

---

## 1. What we were trying to build (intention)

Nick wanted the AI-native operating company to behave like a real CEO layer — not just a ledger that accumulates events.

### North-star behaviors

| Intent | What “done” looks like |
|--------|------------------------|
| **CEO reflects** | On idle supervisor cycles, CEO reads bus + ledger + triage, names bottlenecks, and proposes fixes — not only PMO dispatch scripts. |
| **CEO unsticks** | When something is wedged (dispatch failed, held chain, stale WIP, ledger drift), CEO takes *bounded* mechanical action within admission caps — janitor repass, one retry, one new delegation. |
| **CEO delegates proactively** | When capacity exists, CEO pushes the highest-value unblocked ISSUE to the bus without waiting for Nick to notice stall. |
| **Dashboard tells the truth** | “Currently Working On” shows what the org is *actually* doing; reflection is visible; stale WIP is flagged; deferred/decision-gated work does not pollute the active queue. |
| **Work-room chat is operational** | Saying “take ISSUE-24 out” in the work chat removes it from active execution — not dispatch another worker on top. |
| **LLM adds judgment, not bypass** | Optional OpenRouter layer synthesizes situation summary + ideas; every action still passes admission rules. |

### Architectural picture (target)

```
ceo_supervisor cycle
  → PMO triage/dispatch (existing)
  → ceo_reflect.py (POL-010)     ← rule pass: detect, admit, unstick
  → ceo_reflect_llm.py (optional)  ← synthesis + validated actions
  → artifacts: ceo-queue.json, latest.md, ledger events
  → focus_snapshot (fresh headline for dashboard)

dashboard
  → pickCurrentFocus: running bus job > newest active > fresh reflect > old snapshot
  → reflection block under focus (LLM situation_summary)
  → deferred-work.json excludes dispatch:false from active queue
```

### What Nick should *feel* when this works

- Open dashboard → immediately see an honest one-liner of org state + a short CEO read underneath.
- If the bus is stuck, CEO either unsticks it or escalates to Nick gate with a clear ask — not silent drift.
- Active queue matches reality; completed/landed/deferred issues disappear from “we’re working on this.”

---

## 2. What we actually have (reality)

### Shipped and working

| Component | Status | Notes |
|-----------|--------|-------|
| `scripts/ceo_reflect.py` | ✅ Runnable | Gathers context, detects bottlenecks, admission, mechanical unstick, writes artifacts. Wired in `ceo_supervisor.py` step 5. |
| `scripts/ceo_reflect_llm.py` | ✅ Runnable | OpenRouter `openai/gpt-4.1-mini`, 60-min interval gate, `--force-llm` for manual. |
| `reports/ceo-queue.json` | ✅ Written each cycle | Rule + LLM proposals, actions taken/rejected, counts. |
| `memos/ceo-reflect/latest.md` | ✅ Written each cycle | Human-readable reflect memo. |
| Ledger events | ✅ | `ceo_reflect`, `ceo_reflect_llm`, `focus_snapshot` appended on `--ledger`. |
| Dashboard reflection UI | ✅ Deployed | `#focus-reflect` under Currently Working On; loads static `ceo-queue.json` or live `/api/live/ceo-queue`. |
| Focus picker rewrite | ✅ Deployed | Prefers running job → newest active → fresh reflect over stale PMO snapshot. |
| Deferred queue filter | ✅ | `reports/deferred-work.json`; PMO/dashboard skip `dispatch: false`. |
| Work-room remove path | ✅ | `work_queue_ops.py` phrases → `work_removed` + idle; gate chat wired. |
| Unit tests | ✅ | `test_ceo_reflect.py` for admission/bottleneck rules. |
| Policy doc | ✅ | POL-010 + LLM table in `memos/policy.md`. |

### Key commits (2026-06-30)

- `nick2-dashboard` `d6b91b7` — dashboard reflection + focus picker
- `nick2-dashboard` `1c2c3ba` — fix `_focus_from_report` dict sort bug
- `nick2-dashboard` `a33e9cd` — droplet ledger + fresh ceo-queue after reflect
- Earlier: LLM layer (`35cf654`), work-remove + deferred filter, POL-010 rule pass

---

## 3. Intention vs reality — gap analysis

### A. CEO reflects → **partially true**

**Intention:** CEO produces a trustworthy organizational read every cycle.  
**Reality:** Rule pass + LLM *do* produce reads (`situation_summary`, bottleneck list, proposals). Dashboard now surfaces the summary.

**Gap:** Reflection can read “healthy” (`bottleneck_count: 0`) while the bus still has **7 blocked jobs** and **0 runners**. Blocked jobs are not always promoted to bottlenecks if ledger tasks are deferred/dispatch:false. The CEO *describes* stall well but the rule engine under-detects blocked-bus vs deferred-ledger mismatch.

### B. CEO unsticks → **mechanically limited**

**Intention:** CEO clears wedges without Nick.  
**Reality:** Janitor repass, one undispatched retry, one delegation slot — all admission-gated. On 2026-06-30 evening:

- LLM proposed delegate `ISSUE-BUS-001` → **rejected** (“already active on ledger”).
- `max_retries: 0` in admission (no undispatched retry slot).
- Deferred issues (ISSUE-80, ISSUE-ROUTING-001) correctly skipped.

**Gap:** Unstick actions are narrow. When the real blocker is **crashed/failed bus jobs** (ISSUE-BUS-001 cluster) or **ledger says active but bus is blocked**, CEO does not yet have a “reconcile and respawn” or “supersede dead job” primitive. Reflection proposes; admission blocks; **nothing moves**.

### C. CEO delegates proactively → **mostly not happening**

**Intention:** One delegation slot → highest-ranked ISSUE gets a worker.  
**Reality:** Slot exists (`max_new_delegations: 1`) but targets are often already on ledger, deferred, or decision-gated. PMO dispatch may have already run in the same supervisor cycle.

**Gap:** No crisp “pick the one thing that will actually run” scorer that crosses: triage rank × bus feasibility × not deferred × not claim-blocked.

### D. Dashboard tells the truth → **much better, not perfect**

**Intention:** Currently Working On = ungated, live, honest.  
**Reality (after fix):**

- Stale PMO “Dispatching ISSUE-BUS-001…” no longer wins by default.
- CEO reflect updates `focus_snapshot` with LLM first sentence.
- Reflection paragraph visible under focus.
- Deferred items filtered from active queue table.

**Remaining lies / confusion:**

| Symptom | Cause |
|---------|--------|
| Focus says ISSUE-BUS-001 while nothing runs | Ledger still lists it active; bus jobs blocked; focus picks ledger-linked issue. |
| “Stale” tag confusing | POL-002 flags old `ts`; reflect-derived focus exempts stale styling — inconsistent UX. |
| ISSUE-80 in completed memos but in deferred-work | Landed work correctly deferred; still referenced in reflect prose about “blocked jobs.” |
| GitHub Pages vs droplet live | Static copy lags until droplet commit/push; live mode needs gate server on `:8788`. |

### E. Work-room remove → **fixed for mechanism, not UX**

**Intention:** Chat command removes item from active queue.  
**Reality:** `work_removed` + idle works. ISSUE-24 cleared on droplet.

**Gap:** No explicit user-facing confirmation pattern in chat; user had to discover that first attempt dispatched a worker instead of removing. Dashboard doesn't show "removed by Nick via chat" distinctly.

### F. LLM layer → **synthesis yes, execution rarely**

**Intention:** LLM helps CEO decide; validated actions execute.  
**Reality:** Good `situation_summary` and `llm_nick_attention` proposals. `CEO_REFLECT_LLM_EXECUTE=1` but most actions are `llm_delegate_rejected` or `already_deferred`. 60-min interval means dashboard reflection static between runs.

**Gap:** LLM cost (~$0.001/call) buys narrative, not locomotion. Consider whether interval should shorten when `blocked > 0 && running == 0`.

---

## 4. Current org state (snapshot at handoff)

From `reports/ceo-queue.json` (2026-06-30T15:29:42Z):

```
running: 0 | queued: 0 | held: 0 | blocked: 7 (bus)
admission: 1 delegation slot, 0 retries
bottlenecks (rule): []     ← rule pass says clean
LLM: sees blocked bus cluster around ISSUE-80 / ISSUE-BUS-001
```

**Deferred (do not dispatch):** ISSUE-80, ISSUE-ROUTING-001, ISSUE-15, ISSUE-24 — see `reports/deferred-work.json`.

**Nick gates still blocking real progress:**

- ISSUE-15 — tier schema decision
- ISSUE-24 — Telegram PA permissions decision

**Likely real work if we want movement:** ISSUE-BUS-001 — bus/worker_model crash; 7 blocked jobs depend on it.

---

## 5. Known bugs fixed today (don't re-break)

1. **`_focus_from_report` sorted dict keys not `.items()`** — caused `AttributeError` on first droplet `--ledger` run. Fixed `1c2c3ba`.
2. **`pickCurrentFocus` first-queued-wins** — caused stale ISSUE-BUS-001 headline. Fixed in `d6b91b7`.
3. **Gate server 404 on `/api/live/ceo-queue`** — old process needed restart after deploy; use PID kill not `pkill -f` (kills SSH wrapper).

---

## 6. Files to read first

| Path | Why |
|------|-----|
| `memos/policy.md` § POL-010 | Intended behavior |
| `scripts/ceo_reflect.py` | Rule pass + `focus_snapshot` |
| `scripts/ceo_reflect_llm.py` | LLM gate + action validation |
| `dashboard/app.js` | `pickCurrentFocus`, `renderFocusReflect` |
| `reports/ceo-queue.json` | Latest machine-readable reflect |
| `memos/ceo-reflect/latest.md` | Latest human reflect |
| `reports/deferred-work.json` | What must stay out of active queue |
| `scripts/work_queue_ops.py` | Chat remove/defer mechanics |
| `scripts/witness_dashboard_honesty.py` | POL-009 runnable check |

---

## 7. Recommended next work (priority order)

### P1 — Unblock the bus (real locomotion)

1. Diagnose ISSUE-BUS-001 blocked jobs — worker_model crash, janitor, supersede stale JOBs.
2. Add CEO unstick primitive: **supersede/requeue blocked bus job** when ledger task is genuinely active and admission allows — not just retry undispatched.
3. Re-run `ceo_reflect.py --ledger --force-llm`; verify `actions` contains something other than `llm_delegate_rejected`.

### P2 — Reconcile ledger ↔ bus ↔ deferred

1. If task is in `deferred-work.json`, ledger status should be `idle`/`completed`, not `queued`/`in_progress`.
2. Rule bottleneck detect should flag **blocked bus count > 0 && running == 0** as high severity even when ledger issues are deferred.
3. `pickCurrentFocus` should not link to ISSUE memo when `_fromReflect` and issue is deferred.

### P3 — Dashboard honesty witness

1. Run `python3 scripts/witness_dashboard_honesty.py` on droplet after changes.
2. Extend witness: focus headline must not cite deferred task_id; reflection `ts` must be &lt; 2h or show “reflect stale”.

### P4 — Ops hardening

1. systemd user unit for `gate_chat_server.py` (restart on pull).
2. Stop job-memo churn from blocking `git pull` on droplet — separate generated memos commit cadence or `.gitignore` local-only exports.

### P5 — Nick gates (human)

- ISSUE-15, ISSUE-24 — cannot be automated; ensure `nick_gate` entries are crisp in gated queue.

---

## 8. Env reference (droplet: `/home/nicholas/.hermes/.env`)

```
OPENROUTER_API_KEY=...          # enables LLM reflect
CEO_REFLECT_LLM=1               # or omit if key present
CEO_REFLECT_INTERVAL_MIN=60
CEO_REFLECT_MODEL=openai/gpt-4.1-mini
CEO_REFLECT_LLM_EXECUTE=1
BUS_MAX_PARALLEL=4
CEO_MAX_CODING_PARALLEL=2
```

Manual reflect:

```bash
cd ~/nick2-dashboard
python3 scripts/ceo_reflect.py --ledger --force-llm
git add logs/ceo-ledger.jsonl reports/ceo-queue.json memos/ceo-reflect/latest.md
git commit -m "CEO reflect cycle" && git push
```

---

## 9. One-paragraph summary for Claude

We built POL-010: a CEO reflection loop (rule-based bottleneck detection + optional OpenRouter synthesis) that writes `ceo-queue.json`, updates the dashboard focus panel, and takes admission-bounded unstick actions. We also fixed dashboard honesty bugs (stale focus picker, deferred queue filtering, work-chat remove). **The intention** was a self-unsticking executive layer that keeps the company moving and tells Nick the truth on the dashboard. **The reality** is a working *observability and narration* layer that correctly refuses to dispatch deferred/decision-gated work, but **does not yet reliably convert reflection into bus locomotion** — the org can show `healthy: true` with zero runners and seven blocked jobs. The highest-leverage next step is ISSUE-BUS-001 / blocked-job reconciliation, not more reflection prose.

---

*Generated 2026-06-30 — session handoff from Grok/Cursor harness to Claude Code.*