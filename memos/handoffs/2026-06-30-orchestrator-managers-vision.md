# Design intent: Orchestrator managers (heartbeat + chat + parallel workers)

**Audience:** Claude Code / next agent session  
**Author context:** Nick + Grok harness (Cursor), 2026-06-30 conversation  
**Status:** Intent only — **do not implement** until Nick approves a concrete plan  
**Companion docs:**  
- `memos/handoffs/2026-06-30-ceo-reflect-intention-vs-reality.md` (what we built today vs gaps)  
- `Projects-for-agents/frontier-orchestrator/org.json` (role tree, charters, budget)  
- `agent-bus/registry.yaml` (delegation contract, worker sessions)

---

## 1. Summary (one paragraph)

Nick wants the operating company modeled as **managers**, not **functions**. Each role (CEO, PMO, COO, or any node in the org tree) should be a **long-lived heartbeat orchestrator** he can **talk to at any time** — including **while subordinate workers are executing jobs**. Managers **set up work**, **check in on subordinates**, **course-correct**, and **stay conversational**; implementers remain **bounded bus workers** (or child orchestrators) running in parallel. Roles must **not** be hard-coded into a narrow pipeline (“PMO only triages, CEO only admits, COO only runs scripts”). Charter, authority, and subtree come from **data** (`org.json`), not fixed Python stages.

---

## 2. What Nick is rejecting

### 2.1 Narrow role boxes

Do **not** design around this:

| Role | Hard-coded function |
|------|---------------------|
| PMO | Only rank ISSUEs |
| CEO | Only admission + unstick |
| COO | Only deterministic janitor scripts |
| Hermes | Only Telegram PA |

That was a useful simplification for POL-010 / `ceo_reflect.py`, but it is **not** the target architecture.

### 2.2 Blocking manager

Do **not** make the manager session block on `bus.py wait` or worker completion before accepting Nick’s messages. Blocking kills “talk while work runs.”

### 2.3 Single company-wide pipeline

Do **not** force a fixed LangGraph / cron pipeline: `Hermes → PMO → CEO → COO → worker` every cycle. Overlap between executives is acceptable; **ownership of spawned work** must be clear, not job titles.

### 2.4 CEO as batch script only

`ceo_supervisor.py` + `ceo_reflect.py` are **stepping stones** (observability + bounded mechanical actions), not the final form of “CEO.”

---

## 3. Target mental model

### 3.1 Two species of agent

```
┌─────────────────────────────────────┐
│  ORCHESTRATOR (manager role)        │
│  - heartbeat (stays warm / wakes) │
│  - chat with Nick anytime           │
│  - memory across cycles             │
│  - tools: spawn, status, steer      │
│  - does NOT usually own long coding │
└──────────────┬──────────────────────┘
               │ spawns / supervises (async)
               ▼
┌─────────────────────────────────────┐
│  WORKER (implementer)               │
│  - ephemeral, job-bounded           │
│  - branch-per-job, witness exit 0   │
│  - agent-bus: coding_worker, etc.   │
│  - reports back; session may end    │
└─────────────────────────────────────┘
```

**Analogy:** Manager on Slack while a contractor is on site. Nick can ping the manager; manager checks contractor status; contractor keeps working.

### 3.2 Nick’s experience

1. Opens chat with **whichever role owns the work** (or routes via Hermes — see §7).
2. Says “set up dashboard worker on ISSUE-80” → manager spawns JOB, **returns immediately**: “JOB-924 running; I’m watching.”
3. While JOB runs, Nick asks “still on track?” → manager calls **status tools** (bus, ledger, job memo), answers **without** joining the worker’s context.
4. Nick says “stop / pivot” → manager **supersedes** or spawns replacement work within admission/claims.
5. Manager may **proactively** message on heartbeat: stall detected, gate needed, job completed.

---

## 4. Roles are data, not code branches

Use `org.json` (and dashboard org fleet) as the source of role definitions:

| Field | Meaning for orchestrators |
|-------|---------------------------|
| `charter` | How this manager thinks; system prompt + accountability |
| `parent` | Who they report to; budget may fold up tree |
| `tier` | Auto-run vs Nick-gated (A/B/C) |
| `value` / `cost` | Portfolio admission (frontier SPEC) |
| `maps_to` | Optional link to existing service (telegram-bridge, skill-radar, …) |

**Adding or renaming a role** should be: edit org data + spawn a session from a **template** — not rewrite a central pipeline.

A role’s capabilities = **charter + tool belt + spend cap + which subordinates it may spawn** (bus sessions and/or child orchestrators).

---

## 5. Orchestrator internals (conceptual)

Each orchestrator session needs:

### 5.1 Heartbeat

- **Timer** — e.g. every 5–15 min when portfolio active; slower when idle.
- **Events** — bus job completed/failed, ledger `needs_nicholas`, Nick message, gate cleared.
- On tick: glance at subordinates → act or rest → **remain ready for chat**.

Heartbeat ≠ “run one LLM call and exit.” It means the **session persists** and the loop continues.

### 5.2 Tools (illustrative, not final API)

| Tool class | Purpose |
|------------|---------|
| `status_job` / `status_portfolio` | Check subordinates without blocking |
| `bus_submit` / `bus_supersede` | Delegate implementation |
| `ledger_append` / `nick_gate` | Commit truth to dashboard |
| `spawn_child_role` | Wake another orchestrator in org tree |
| `read_triage` / `read_memories` | Context for judgment |
| `run_mechanical` | Invoke COO-style scripts (janitor, witness) as **tools**, not as “the whole COO” |

Mechanical scripts stay valuable; they should not **be** the executive — they should be **callable**.

### 5.3 Memory

- Session transcript + `memories.jsonl` (CEO already has this pattern under `agent-bus/sessions/ceo/`).
- Compaction when long — same discipline as role_memory / PA memories.
- **Ledger + bus remain authoritative** for “what is true”; manager memory is for “what did I already try.”

### 5.4 Admission and safety (unchanged principles)

- Bus scheduler stays **dumb** — no LLM in admit path (`registry.yaml`).
- Managers **request** dispatches; bus enforces **repo claims**, parallelism, timeouts.
- POL-010-style caps (max delegations, no dispatch on `deferred-work.json`) apply at **tool boundary**, not as “CEO personality.”
- Definition of done for workers: witness exit 0 on job branch.

---

## 6. Interaction modes (one manager session)

| Mode | Trigger | Behavior |
|------|---------|----------|
| **Proactive** | Heartbeat / event | “Worker stalled; I superseded JOB-X” |
| **Reactive (Nick)** | Incoming message | Answer, steer, spawn, gate — **while workers run** |
| **Setup** | Nick or self | Spawn subordinate; non-blocking ack with job id |

**Human-in-the-loop** is continuous, not a single gate at the end of a graph.

---

## 7. Chat surfaces (open design)

Nick has **not** finalized one UI. Options:

| Surface | Today | Fit |
|---------|-------|-----|
| **Telegram / Hermes** | 24/7 router + PA | Route “talk to PMO” or task-scoped handoff |
| **Dashboard work-room** | Per-ISSUE chat | Natural “talk to owner of this work” |
| **Dedicated role channels** | Not built | PMO room, CEO room, etc. |
| **Cursor / Mac harness** | Manager-of-managers | Dispatch + “do it here” override |

**Hermes** should remain Nick-facing **router**, not absorb every executive function — unless Nick explicitly wants one inbox. The architecture allows **multiple orchestrators**; UX must show **who owns JOB-***.

---

## 8. Subordinates

Managers supervise **heterogeneous** reports:

| Subordinate type | Check-in via |
|------------------|--------------|
| `coding_worker` / `dashboard_worker` / `heavy_coder` | `jobs.sqlite`, `bus-live.json`, job memos |
| Child orchestrator (e.g. PMO under COO) | Child session status, child ledger events |
| Cron / script | Last exit code, log tail, sync heartbeat |

“Check in” = **read receipts** from shared infra, not sharing one giant LLM context with the worker.

---

## 9. Relationship to existing systems

### 9.1 agent-bus

**Keep.** Workers stay ephemeral, witness-gated, branch-per-job. Orchestrators are **clients** of the bus, not replacements.

### 9.2 Hermes (telegram-bridge)

**Keep as Chief of Staff / router.** Closest living example of “always-on chat agent.” Use as pattern for other orchestrators, not as the only executive.

### 9.3 frontier-orchestrator

Parallel autonomous lane (ROI, lanes, proposals). May **feed** managers or **merge** later — registry says do not blindly merge into bus. Orchestrator vision is compatible: frontier could become **one way to wake** a role cycle.

### 9.4 Today’s CEO reflect stack

| Piece | Future role |
|-------|-------------|
| `ceo_reflect.py` | Tool(s) inside CEO orchestrator — rule pass |
| `ceo_reflect_llm.py` | Tool or subgraph node — synthesis |
| `ceo_supervisor.py` | Likely **deprecated or thinned** — mechanical steps become tools invoked by heartbeat, not a separate “fake CEO” |
| Dashboard focus / `ceo-queue.json` | Still fed by **tool commits** (`focus_snapshot`, artifacts) |

### 9.5 Cursor / Mac harness

Stays **Nick’s interactive override** (“do it here”). Droplet orchestrators are the **24/7** management layer; harness is not redundant.

---

## 10. LangGraph and orchestration frameworks

Nick asked about **LangGraph** (graph-based agent orchestration).

**Useful for:** each manager’s **inner** loop — cycles, checkpoints, branches (idle vs act vs gate Nick), resume after crash.

**Not a substitute for:** agent-bus job queue, org tree, or Nick’s multi-manager chat model.

Recommended framing:

```
Nick ↔ orchestrator session(s)     ← chat + heartbeat (maybe LangGraph inside)
              ↓ tools
       agent-bus workers           ← implementation queue (unchanged)
```

Company orchestration = **tree of managers + bus**; LangGraph = optional **implementation of one manager’s control flow**.

---

## 11. Gaps in current repo (honest)

| Gap | Note |
|-----|------|
| No persistent PMO/CEO chat session on droplet | Only Hermes + ephemeral workers |
| Work-room chat often **dispatches another worker** instead of **orchestrator check-in** | Fixed partially for “remove”; not full manager model |
| Manager/worker concurrency not modeled | No `status_job` tool belt for chat agents |
| Role = session not wired | `org.json` is design data; `maps_to` is partial |
| Authority collisions possible | Need clear `owner` on ledger + spawn audit trail |
| Cost | Many heartbeat sessions → token spend; need idle cheap mode |

---

## 12. Non-goals (for v1 planning)

- Replacing bus with LLM scheduler  
- One mega-agent that is CEO+PMO+COO+coding_worker  
- Nick reading raw worker logs — managers summarize  
- Hard-coding three executives in Python forever  

---

## 13. Open questions for Nick (before build)

1. **Chat routing:** One inbox (Hermes routes) vs per-role rooms on dashboard?  
2. **Session runtime:** Same as workers (`claude` + CCR on droplet) vs separate orchestrator runtime?  
3. **How many orchestrators run at once?** CEO only? CEO + PMO? Any role with budget wake?  
4. **Supersede authority:** Which roles can kill/requeue blocked jobs without Nick?  
5. **Migrate `ceo_supervisor`:** Wrap as CEO tools, or run in parallel during transition?  

---

## 14. Suggested implementation phases (when approved)

**Phase A — Pattern proof**  
One orchestrator (PMO or CEO) as tmux session: heartbeat + chat + `status_job` + `bus_submit` + non-blocking responses. One worker runs; Nick chats mid-flight.

**Phase B — Tool belt**  
Wire ledger, gates, janitor, reflect as tools. Retire linear supervisor script piecemeal.

**Phase C — Org-driven spawn**  
Load role from `org.json`; child roles spawnable; budget admission from frontier rules.

**Phase D — Surfaces**  
Dashboard work-room talks to **owning orchestrator**, not raw dispatch loop.

---

## 15. Definition of success

Nick can:

1. Message a **role** and get a response **while** a worker JOB is in progress.  
2. Ask for status and get **bus/ledger-grounded** answers.  
3. Steer or stop work **without** waiting for worker session to end.  
4. Add/rename roles in **org data** without rewriting orchestration code.  
5. Trust the dashboard because managers **commit** focus/queue via tools, not chat hallucination.

---

## 16. One-line handoff to Claude

> Build toward **heartbeat orchestrator managers** (chat + tools + memory) that supervise **async bus workers** and stay talkable mid-job; roles are **flexible and org-defined**, not a hard-coded CEO/PMO/COO pipeline. Today’s reflect/supervisor stack is a partial tool layer, not the destination.

---

*Generated 2026-06-30 — design intent from Nick + Grok harness. No code authorized by this document alone.*