/**
 * Nick2 Operating Dashboard
 * Source of truth: logs/ceo-ledger.jsonl (append-only)
 */

let dataUrls = { ...Nick2LiveConfig.STATIC, source: 'github-static' };
const GATED_POLL_MS = 20000;
const BUS_LIVE_POLL_MS = 8000;
const WIP_STALE_MS = 30 * 60 * 1000;
const BUS_STALE_MS = 2 * 60 * 1000;
let liveTimerInterval = null;
const ROADMAP_LANES = {
  near_term: 'Near-term',
  capability: 'Capability-building',
  experimental: 'Experimental',
  revenue: 'Revenue-generating',
};

const ACTIVE_STATUSES = new Set(['queued', 'in_progress', 'blocked', 'approved']);
const COMPLETED_STATUSES = new Set(['completed']);
const QUEUE_SKIP_EVENTS = new Set([
  'decision_needed', 'decision_resolved', 'nick_gate', 'nick_gate_resolved',
  'roadmap_item', 'trust_snapshot', 'focus_snapshot', 'policy_set',
]);

const NICK_PRIORITY = { high: 1, medium: 2, low: 3 };

function isGatedByNick(t, resolvedIds) {
  const id = t.task_id;
  if (!id || resolvedIds.has(id)) return false;
  if (t.gated_by_nick || t.needs_nicholas) return true;
  if (t.status === 'awaiting_nicholas') return true;
  if (t.last_event === 'nick_gate' || t.last_event === 'decision_needed') return true;
  return false;
}

function nickPriorityRank(t) {
  if (typeof t.nick_priority === 'number') return t.nick_priority;
  return NICK_PRIORITY[t.priority] ?? NICK_PRIORITY[t.nick_priority] ?? 99;
}

let allEvents = [];
let filterText = '';

function $(id) {
  return document.getElementById(id);
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s ?? '';
  return d.innerHTML;
}

function badge(status) {
  if (!status) return '';
  const cls = `badge badge-${String(status).replace(/\s+/g, '_')}`;
  return `<span class="${cls}">${esc(status)}</span>`;
}

function fmtTs(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-SG', { timeZone: 'Asia/Singapore', dateStyle: 'short', timeStyle: 'medium' });
  } catch {
    return esc(ts);
  }
}

function fmtUsd(n) {
  if (n == null || Number.isNaN(n)) return '—';
  return `$${Number(n).toFixed(2)}`;
}

function parseIso(ts) {
  if (!ts) return null;
  try {
    const d = new Date(String(ts).replace(/\+08:00$/, '+08:00'));
    return Number.isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

function ageMs(ts) {
  const d = parseIso(ts);
  return d ? Math.max(0, Date.now() - d.getTime()) : null;
}

function formatLiveDuration(ms) {
  if (ms == null) return '—';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

function liveTimerSpan(sinceIso, label, { stale = false } = {}) {
  if (!sinceIso) return '';
  return `<span class="live-timer${stale ? ' live-timer-stale' : ''}" data-live-since="${esc(sinceIso)}" data-live-label="${esc(label)}" data-live-stale="${stale ? '1' : '0'}">${esc(label)} …</span>`;
}

function tickLiveTimers() {
  document.querySelectorAll('[data-live-since]').forEach((el) => {
    const ms = ageMs(el.dataset.liveSince);
    if (ms == null) return;
    const label = el.dataset.liveLabel || 'On';
    el.textContent = `${label} ${formatLiveDuration(ms)}`;
    const stale = el.dataset.liveStale === '1' || ms >= WIP_STALE_MS;
    el.classList.toggle('live-timer-stale', stale);
  });
  const fleetUpdated = $('org-fleet-updated');
  if (fleetUpdated?.dataset.busGeneratedAt) {
    const ms = ageMs(fleetUpdated.dataset.busGeneratedAt);
    if (ms != null) {
      const snap = formatLiveDuration(ms);
      const stale = ms >= BUS_STALE_MS;
      fleetUpdated.textContent = stale
        ? `Bus snapshot ${snap} ago (stale)`
        : `Bus live · refreshed ${snap} ago`;
      fleetUpdated.classList.toggle('meta-stale', stale);
    }
  }
  const lastUp = $('last-updated');
  if (lastUp?.dataset.ledgerTs) {
    const ms = ageMs(lastUp.dataset.ledgerTs);
    if (ms != null) {
      const stale = ms >= WIP_STALE_MS;
      lastUp.textContent = stale
        ? `Ledger ${formatLiveDuration(ms)} ago (POL-002)`
        : `Ledger ${formatLiveDuration(ms)} ago`;
      lastUp.classList.toggle('meta-stale', stale);
    }
  }
}

function startLiveTimers() {
  tickLiveTimers();
  if (!liveTimerInterval) liveTimerInterval = setInterval(tickLiveTimers, 1000);
}

async function loadLedger() {
  const res = await fetch(`${dataUrls.ledger}?t=${Date.now()}`);
  if (!res.ok) throw new Error(`Failed to load ledger (${res.status})`);
  const text = await res.text();
  return text
    .trim()
    .split('\n')
    .filter(Boolean)
    .map((line, i) => {
      try {
        return JSON.parse(line);
      } catch (e) {
        console.warn(`Skipping malformed line ${i + 1}:`, e);
        return null;
      }
    })
    .filter(Boolean);
}

function latestByKey(events, keyFn) {
  const map = new Map();
  for (const ev of events) {
    const k = keyFn(ev);
    if (k) map.set(k, ev);
  }
  return map;
}

function buildState(events) {
  const sorted = [...events].sort((a, b) => new Date(a.ts) - new Date(b.ts));
  const tasks = new Map();
  const trust = new Map();
  const roadmap = [];
  const artifacts = new Set();
  const budgetEntries = [];
  const resolvedDecisionIds = new Set();
  let weeklyBudget = null;
  let budgetMode = 'unknown';
  let cumulativeSpend = 0;
  let modelBackend = null;
  let autonomyMode = null;
  let currentCeoTask = null;
  let focusSnapshot = null;

  for (const ev of sorted) {
    if (ev.weekly_budget_usd != null) weeklyBudget = ev.weekly_budget_usd;
    if (ev.budget_mode) budgetMode = ev.budget_mode;
    if (ev.cumulative_weekly_spend_usd != null) cumulativeSpend = ev.cumulative_weekly_spend_usd;
    if (ev.model) modelBackend = ev.model;

    if (ev.task_id) {
      const prev = tasks.get(ev.task_id) || {};
      tasks.set(ev.task_id, { ...prev, ...ev, last_event: ev.event });
    }

    if (ev.trust && typeof ev.trust === 'object') {
      for (const [agent, rec] of Object.entries(ev.trust)) {
        trust.set(agent, { ...trust.get(agent), ...rec });
      }
    }

    if (ev.event === 'trust_update' && ev.actor) {
      const rec = trust.get(ev.actor) || { runs: 0, successes: 0, failures: 0 };
      rec.runs = (rec.runs || 0) + 1;
      if (ev.status === 'completed' || ev.witness_passed) rec.successes = (rec.successes || 0) + 1;
      if (ev.status === 'failed' || ev.witness_failed) rec.failures = (rec.failures || 0) + 1;
      if (ev.autonomy) rec.autonomy = ev.autonomy;
      if (ev.ts) rec.last_reviewed = ev.ts.slice(0, 10);
      trust.set(ev.actor, rec);
    }

    if ((ev.event === 'decision_resolved' || ev.event === 'nick_gate_resolved') && ev.task_id) {
      resolvedDecisionIds.add(ev.task_id);
    }

    if (ev.event === 'focus_snapshot') {
      focusSnapshot = ev;
    }

    if (ev.event === 'ceo_focus') {
      focusSnapshot = { ...focusSnapshot, ...ev, focus_line: ev.focus_line || ev.output };
    }

    if (ev.event === 'roadmap_item') {
      roadmap.push(ev);
    }

    if (Array.isArray(ev.artifacts)) {
      for (const a of ev.artifacts) {
        if (a) artifacts.add(a);
      }
    }

    if (ev.cost_usd > 0 || ev.event === 'budget_set' || ev.event === 'budget_authorized') {
      budgetEntries.push(ev);
    }

    if (ev.event === 'ceo_focus') {
      currentCeoTask = ev;
    } else if (ev.event === 'focus_snapshot' && ev.focus_line) {
      currentCeoTask = ev;
    }
  }

  const taskList = [...tasks.values()];
  const gatedByNick = taskList
    .filter((t) => isGatedByNick(t, resolvedDecisionIds))
    .sort((a, b) => nickPriorityRank(a) - nickPriorityRank(b) || new Date(a.ts) - new Date(b.ts));

  const active = taskList.filter(
    (t) =>
      ACTIVE_STATUSES.has(t.status) &&
      !COMPLETED_STATUSES.has(t.status) &&
      !QUEUE_SKIP_EVENTS.has(t.last_event) &&
      !isGatedByNick(t, resolvedDecisionIds)
  );
  const completed = taskList.filter((t) => COMPLETED_STATUSES.has(t.status) || t.event === 'task_completed');

  const spendByModel = {};
  const spendByProject = {};
  for (const ev of sorted) {
    if (ev.cost_usd > 0) {
      const m = ev.model || 'unknown';
      spendByModel[m] = (spendByModel[m] || 0) + ev.cost_usd;
      const p = ev.project || ev.actor || 'general';
      spendByProject[p] = (spendByProject[p] || 0) + ev.cost_usd;
    }
  }

  const budgetRemaining =
    weeklyBudget != null && weeklyBudget > 0 ? Math.max(0, weeklyBudget - cumulativeSpend) : weeklyBudget === 0 ? 0 : null;

  autonomyMode = budgetMode === 'off' ? 'manual_only' : workerEnabled(sorted) ? 'auto_dispatch' : 'recommend_only';

  const memoKindByTaskId = new Map();
  for (const t of taskList) {
    const tid = t.task_id;
    if (!tid) continue;
    if (isGatedByNick(t, resolvedDecisionIds)) memoKindByTaskId.set(tid, 'gated');
    else if (COMPLETED_STATUSES.has(t.status) || t.last_event === 'task_completed') {
      memoKindByTaskId.set(tid, 'completed');
    } else if (ACTIVE_STATUSES.has(t.status) && !QUEUE_SKIP_EVENTS.has(t.last_event)) {
      memoKindByTaskId.set(tid, 'queue');
    }
  }

  return {
    sorted,
    weeklyBudget,
    budgetMode,
    cumulativeSpend,
    budgetRemaining,
    modelBackend,
    autonomyMode,
    currentCeoTask,
    focusSnapshot,
    active,
    completed,
    trust,
    gatedByNick,
    roadmap,
    artifacts: [...artifacts],
    budgetEntries,
    spendByModel,
    spendByProject,
    memoKindByTaskId,
  };
}

function workerEnabled(events) {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    if (ev.event === 'worker_status') {
      return ev.status !== 'blocked' && !String(ev.output || '').includes('enabled=false');
    }
  }
  return false;
}

function renderSnapshot(state) {
  const cards = [
    {
      label: 'Weekly Budget',
      value: state.weeklyBudget === 0 ? 'OFF' : fmtUsd(state.weeklyBudget),
      sub: state.budgetMode === 'off' ? 'per_cycle: 0 = disabled' : 'Authorized cap',
      badge: state.weeklyBudget === 0 ? badge('off') : badge('on'),
    },
    {
      label: 'Spend (week)',
      value: fmtUsd(state.cumulativeSpend),
      sub: state.budgetRemaining != null ? `Remaining: ${fmtUsd(state.budgetRemaining)}` : 'No cap set',
    },
    {
      label: 'Model Backend',
      value: state.modelBackend ? state.modelBackend.split('/').pop() : '—',
      sub: state.modelBackend || 'Not configured',
    },
    {
      label: 'Autonomy',
      value: state.autonomyMode?.replace(/_/g, ' ') ?? '—',
      sub:
        state.autonomyMode === 'manual_only'
          ? 'Worker off'
          : state.autonomyMode === 'recommend_only'
            ? 'Budget on, worker off'
            : 'Frontier orchestrator',
      badge: badge(state.autonomyMode === 'auto_dispatch' ? 'on' : 'off'),
    },
    {
      label: 'CEO Focus',
      valueHtml: state.currentCeoTask
        ? taskMemoLinkFromState(
            focusPlainLine(state.currentCeoTask, state) || state.currentCeoTask.task_id,
            state.currentCeoTask.focus_task_id || state.currentCeoTask.task_id,
            state,
            'stat-link'
          )
        : null,
      value: state.currentCeoTask ? focusPlainLine(state.currentCeoTask, state) || 'Idle' : 'Idle',
      sub: state.currentCeoTask ? fmtTs(state.currentCeoTask.ts) : 'No active CEO task',
    },
    {
      label: 'Gated by Nick',
      value: String(state.gatedByNick.length),
      sub: 'Parked — agents work elsewhere',
      badge: state.gatedByNick.length ? badge('awaiting_nicholas') : '',
    },
  ];

  $('snapshot-grid').innerHTML = cards
    .map(
      (c) => `
    <div class="stat-card">
      <div class="stat-label">${esc(c.label)} ${c.badge || ''}</div>
      <div class="stat-value">${c.valueHtml || esc(String(c.value))}</div>
      <div class="stat-sub">${esc(c.sub)}</div>
    </div>`
    )
    .join('');
}

function renderActivity(events, state) {
  const filtered = events
    .filter((ev) => {
      if (!filterText) return true;
      const hay = JSON.stringify(ev).toLowerCase();
      return hay.includes(filterText.toLowerCase());
    })
    .sort((a, b) => new Date(b.ts) - new Date(a.ts));

  if (!filtered.length) {
    $('activity-feed').innerHTML = '<p class="empty">No activity matches filter.</p>';
    return;
  }

  $('activity-feed').innerHTML = filtered
    .map(
      (ev) => `
    <div class="feed-item">
      <div class="feed-item-header">
        <span class="feed-actor">${esc(ev.actor)} · ${esc(ev.event)} ${badge(ev.status)}</span>
        <span class="feed-ts">${fmtTs(ev.ts)}</span>
      </div>
      <div class="feed-task">${taskMemoLinkFromState(ev.task || ev.task_id || '', ev.task_id, state)}</div>
      <div class="feed-output">${esc(ev.output || '')}${ev.cost_usd ? ` · ${fmtUsd(ev.cost_usd)}` : ''}</div>
    </div>`
    )
    .join('');
}

function renderTable(el, headers, rows, emptyMsg) {
  if (!el) {
    console.warn('renderTable: missing element');
    return;
  }
  if (!rows.length) {
    el.innerHTML = `<p class="empty">${emptyMsg}</p>`;
    return;
  }
  el.innerHTML = `
    <table>
      <thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>
      <tbody>${rows.join('')}</tbody>
    </table>`;
}

const GATE_ROOM_WIN = 'popup=yes,width=1120,height=860,menubar=no,toolbar=no,location=yes,status=no';

function openGateRoom(taskId) {
  if (!taskId) return;
  const url = `gate-room.html?task=${encodeURIComponent(taskId)}`;
  const win = window.open(url, `nick2_gate_${taskId}`, GATE_ROOM_WIN);
  if (win) win.focus();
}

function openWorkRoom(taskId) {
  if (!taskId) return;
  const url = `work-room.html?task=${encodeURIComponent(taskId)}`;
  const win = window.open(url, `nick2_work_${taskId}`, GATE_ROOM_WIN);
  if (win) win.focus();
}

function memoHref(kind, taskId) {
  if (!taskId || !kind) return null;
  if (kind === 'gated') return `gate-room.html?task=${encodeURIComponent(taskId)}`;
  if (kind === 'queue') return `work-room.html?task=${encodeURIComponent(taskId)}`;
  // Dynamic loader — always fetches fresh .md (static .html lags behind live ledger)
  const mdPath = `memos/${kind}/${taskId}.md`;
  return `memo.html?p=${encodeURIComponent(mdPath)}`;
}

function shortJobId(jobId) {
  if (!jobId) return '';
  const m = String(jobId).match(/^JOB-\d{8}-(\d+)$/);
  return m ? `JOB-${m[1]}` : jobId;
}

function jobMemoHref(jobId) {
  if (!jobId) return null;
  return memoHref('jobs', jobId);
}

function fleetJobTitle(job) {
  const jid = job.job_id || '';
  const shortId = job.short_job_id || shortJobId(jid);
  const feature =
    job.feature_name ||
    (job.display_name || '').split('[')[0].trim() ||
    jid ||
    'job';
  return shortId ? `${shortId} · ${feature}` : feature;
}

/** Gated queue titles open the gate room popup (MKA + chat). */
function gateTaskLink(text, taskId, className = 'memo-link') {
  const label = text ?? '—';
  if (!taskId) return esc(label);
  return `<a class="${className} gate-open-link" href="gate-room.html?task=${encodeURIComponent(taskId)}" data-gate-id="${esc(taskId)}">${esc(label)}</a>`;
}

function bindGateOpenLinks(root) {
  if (!root) return;
  root.querySelectorAll('.gate-open-link').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      openGateRoom(a.dataset.gateId);
    });
  });
}

/** Active queue tasks open the work room popup (execution brief + agent chat). */
function workTaskLink(text, taskId, className = 'memo-link') {
  const label = text ?? '—';
  if (!taskId) return esc(label);
  return `<a class="${className} work-open-link" href="work-room.html?task=${encodeURIComponent(taskId)}" data-work-id="${esc(taskId)}">${esc(label)}</a>`;
}

function bindWorkOpenLinks(root) {
  if (!root) return;
  root.querySelectorAll('.work-open-link').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      openWorkRoom(a.dataset.workId);
    });
  });
}

/** Wrap label in memo link when a memo exists; otherwise plain escaped text. */
function taskMemoLink(text, kind, taskId, className = 'memo-link') {
  if (kind === 'gated') return gateTaskLink(text, taskId, className);
  if (kind === 'queue') return workTaskLink(text, taskId, className);
  const label = text ?? '—';
  const href = memoHref(kind, taskId);
  if (!href) return esc(label);
  return `<a class="${className}" href="${href}">${esc(label)}</a>`;
}

function taskMemoLinkFromState(text, taskId, state, className = 'memo-link') {
  return taskMemoLink(text, state.memoKindByTaskId.get(taskId), taskId, className);
}

function pickCurrentFocus(state) {
  const snap = state.focusSnapshot;
  if (snap?.focus_task_id) {
    const linked = state.active.find((t) => t.task_id === snap.focus_task_id);
    if (linked) return { ...linked, focus_line: snap.focus_line, focus_detail: snap.focus_detail };
  }
  const inProg = state.active.find((t) => t.status === 'in_progress');
  if (inProg) return inProg;
  const queued = state.active.find((t) => t.status === 'queued');
  if (queued) return queued;
  return state.active[0] || snap || null;
}

function focusPlainLine(focus, state) {
  if (!focus) return null;
  if (focus.focus_line) return focus.focus_line;
  const tid = focus.task_id || focus.focus_task_id;
  const task = (focus.task || '').trim();
  const done = COMPLETED_STATUSES.has(focus.status) || focus.status === 'idle';
  const outFirst = (focus.output || '').split(/[.!?\n]/)[0]?.trim();
  if (done && outFirst && outFirst.length <= 120) return outFirst;
  if (task && !task.includes('POL-') && task.length <= 80 && !done) return task;
  if (outFirst && outFirst.length <= 100) return outFirst;
  return task ? `${tid}: ${task.slice(0, 60)}` : tid || 'Idle';
}

function setFocusPanel(focus, state) {
  const headline = $('focus-headline');
  const detail = $('focus-detail');
  const meta = $('focus-meta');
  if (!headline || !detail || !meta) return;

  if (!focus) {
    headline.innerHTML =
      '<a class="focus-link" href="memos/current.html">Idle — no active work in queue</a>';
    detail.textContent = 'Check the roadmap or authorize work in the ledger.';
    meta.innerHTML = '';
    return;
  }

  const taskId = focus.focus_task_id || focus.task_id;
  const line = focusPlainLine(focus, state) || '—';
  headline.innerHTML = state && taskId
    ? taskMemoLinkFromState(line, taskId, state, 'focus-link')
    : esc(line);
  const done = COMPLETED_STATUSES.has(focus.status) || focus.status === 'idle';
  let detailSrc = focus.focus_detail || focus.output || '';
  if (done && focus.output) {
    const dot = focus.output.indexOf('.');
    detailSrc =
      dot >= 0
        ? focus.output.slice(dot + 1).trim()
        : 'Next: dispatch ranked issues to coding_worker (see PMO-001_TRIAGE_SUMMARY.md).';
  }
  detail.textContent = detailSrc.length > 220 ? `${detailSrc.slice(0, 217)}…` : detailSrc;
  const focusStale = focus.ts && ageMs(focus.ts) >= WIP_STALE_MS;
  meta.innerHTML = `
    <span class="meta-pill">${badge(focus.status)}</span>
    <span class="meta-pill">${esc(taskId || '')}</span>
    <span class="meta-pill">${liveTimerSpan(focus.ts, 'Focus age', { stale: focusStale })}</span>`;
  bindWorkOpenLinks(headline);
  bindGateOpenLinks(headline);
}

function renderCurrentFocus(state) {
  setFocusPanel(pickCurrentFocus(state), state);
}

function renderQueue(state) {
  const rows = state.active.map((t) => {
    const stale = t.ts && ageMs(t.ts) >= WIP_STALE_MS;
    const statusCell = stale
      ? `${badge(t.status)} <span class="queue-stale-tag" title="POL-002: no ledger heartbeat 30+ min">stale</span>`
      : badge(t.status);
    return `<tr class="${stale ? 'queue-row-stale' : ''}">
      <td>${statusCell}</td>
      <td>${esc(t.owner || t.actor)}</td>
      <td>${taskMemoLink(t.task, 'queue', t.task_id)}</td>
      <td>${esc(t.task_id || '')}</td>
      <td>${liveTimerSpan(t.ts, 'Since update', { stale })}</td>
    </tr>`;
  });
  renderTable(
    $('work-queue'),
    ['Status', 'Owner', 'Task', 'ID', 'Age'],
    rows,
    'No active work in queue.'
  );
  bindWorkOpenLinks($('work-queue'));
}

function renderCompleted(state) {
  const rows = state.completed.map(
    (t) => `<tr>
      <td>${fmtTs(t.ts)}</td>
      <td>${esc(t.actor)}</td>
      <td>${taskMemoLink(t.task, 'completed', t.task_id)}</td>
      <td>${fmtUsd(t.cost_usd || 0)}</td>
      <td>${esc((t.artifacts || []).join(', ') || '—')}</td>
    </tr>`
  );
  renderTable(
    $('completed-work'),
    ['Time', 'Owner', 'Task', 'Cost', 'Artifacts'],
    rows,
    'No completed tasks yet.'
  );
}

function renderBudget(state) {
  $('budget-summary').innerHTML = `
    <div class="budget-stat">Weekly cap: <strong>${state.weeklyBudget === 0 ? 'OFF' : fmtUsd(state.weeklyBudget)}</strong></div>
    <div class="budget-stat">Spent: <strong>${fmtUsd(state.cumulativeSpend)}</strong></div>
    <div class="budget-stat">Remaining: <strong>${state.budgetRemaining != null ? fmtUsd(state.budgetRemaining) : '—'}</strong></div>`;

  const models = Object.entries(state.spendByModel);
  const maxSpend = Math.max(...models.map(([, v]) => v), 0.01);
  $('budget-chart').innerHTML = models.length
    ? models
        .map(
          ([m, v]) => `
      <div class="bar-row">
        <span class="bar-label">${esc(m.split('/').pop())}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${(v / maxSpend) * 100}%"></div></div>
        <span class="bar-value">${fmtUsd(v)}</span>
      </div>`
        )
        .join('')
    : '<p class="empty">No spend by model yet.</p>';

  const spendEvents = state.sorted.filter((e) => e.cost_usd > 0);
  const rows = spendEvents.map(
    (e) => `<tr>
      <td>${fmtTs(e.ts)}</td>
      <td>${esc(e.project || e.actor)}</td>
      <td>${esc(e.model || '—')}</td>
      <td>${fmtUsd(e.cost_usd)}</td>
      <td>${fmtUsd(e.cumulative_weekly_spend_usd)}</td>
      <td>${esc(e.output?.slice(0, 60) || '')}</td>
    </tr>`
  );
  renderTable($('budget-ledger'), ['Time', 'Project', 'Model', 'Cost', 'Cumulative', 'Notes'], rows, 'No budget transactions yet.');
}

function renderTrust(state) {
  const agents = [...state.trust.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  const rows = agents.map(
    ([name, rec]) => `<tr>
      <td>${esc(name)}</td>
      <td>${rec.runs ?? 0}</td>
      <td>${rec.successes ?? 0}</td>
      <td>${rec.failures ?? 0}</td>
      <td>${esc(rec.autonomy || '—')}</td>
      <td>${esc(rec.last_reviewed || '—')}</td>
    </tr>`
  );
  renderTable(
    $('trust-ledger'),
    ['Agent', 'Runs', 'Successes', 'Failures', 'Autonomy', 'Last Reviewed'],
    rows,
    'Trust ledger empty — no agent runs recorded.'
  );
}

function renderNickGate(state) {
  const rows = state.gatedByNick.map(
    (g, i) => `<tr>
      <td><strong>${i + 1}</strong></td>
      <td>${badge(g.priority || 'medium')}</td>
      <td>${gateTaskLink(g.task, g.task_id)}</td>
      <td>${esc(g.task_id || '')}</td>
      <td>${esc(g.output?.slice(0, 80) || '')}</td>
      <td>${fmtTs(g.ts)}</td>
      <td><button type="button" class="btn btn-sm gate-discuss-btn" data-gate-id="${esc(g.task_id || '')}">Discuss</button></td>
    </tr>`
  );
  renderTable(
    $('nick-gate-queue'),
    ['#', 'Priority', 'Waiting on Nick', 'ID', 'What Nick must do', 'Since', ''],
    rows,
    'Nothing gated — all work is unblocked or agents are executing autonomously.'
  );

  const table = $('nick-gate-queue');
  if (!table) return;
  bindGateOpenLinks(table);
  table.querySelectorAll('.gate-discuss-btn').forEach((btn) => {
    btn.addEventListener('click', () => openGateRoom(btn.dataset.gateId));
  });
}

function renderRoadmap(state) {
  const el = $('roadmap-list');
  if (!el) return;
  const byLane = {};
  for (const item of state.roadmap) {
    const lane = item.roadmap_lane || 'near_term';
    if (!byLane[lane]) byLane[lane] = [];
    byLane[lane].push(item);
  }

  const lanes = Object.keys(ROADMAP_LANES);
  el.innerHTML = lanes
    .map((lane) => {
      const items = (byLane[lane] || []).sort((a, b) => (a.priority || 99) - (b.priority || 99));
      return `
      <div class="roadmap-lane">
        <h3>${esc(ROADMAP_LANES[lane])}</h3>
        ${
          items.length
            ? items.map((i) => `<div class="roadmap-item">${badge(i.status)} ${esc(i.task)}</div>`).join('')
            : '<p class="empty" style="padding:0">—</p>'
        }
      </div>`;
    })
    .join('');
}

function renderArtifacts(state) {
  const el = $('artifacts-list');
  if (!el) return;
  if (!state.artifacts.length) {
    el.innerHTML = '<p class="empty">No artifacts recorded yet.</p>';
    return;
  }
  el.innerHTML = state.artifacts
    .sort()
    .map((a) => `<div class="artifact-item">${esc(a)}</div>`)
    .join('');
}

const ORG_LIVE = new Set(['live']);
const ORG_SCHEDULED = new Set(['timer']);
const ORG_ASLEEP = new Set(['asleep', 'idle']);
let orgFleetFilter = 'now';
let orgFleetDataCache = null;
let busLiveDataCache = null;

function orgRoleCard(node, { compact = false } = {}) {
  const status = node.status || 'asleep';
  const maps = node.maps_to
    ? `<span class="org-card-maps">${esc(node.maps_to)}</span>`
    : '';
  const sched = node.schedule
    ? `<span class="org-card-schedule">${esc(node.schedule)}</span>`
    : '';
  const detail = node.detail
    ? `<p class="org-card-detail">${esc(node.detail)}</p>`
    : '';
  const cls = compact ? 'org-card org-card-compact' : 'org-card';
  return `<article class="${cls} org-status-${esc(status)}" data-status="${esc(status)}">
    <div class="org-card-head">
      <span class="org-card-icon" aria-hidden="true">${esc(node.icon || '·')}</span>
      <div class="org-card-titles">
        <h4 class="org-card-title">${esc(node.title)}</h4>
        ${maps}
      </div>
      ${sched}
    </div>
    ${detail}
  </article>`;
}

function renderOrgFleetLegend(legend) {
  const el = $('org-fleet-legend');
  if (!el || !legend) return;
  el.innerHTML = Object.entries(legend)
    .map(
      ([k, v]) =>
        `<span class="org-legend-pill org-status-${esc(k)}" title="${esc(k)}">${esc(v)}</span>`
    )
    .join('');
}

function renderOrgFleetContext(ctx, bus) {
  const el = $('org-fleet-context');
  if (!el) return;
  const chips = [];
  const pmo = bus?.pmo_focus;
  if (pmo?.task_id) {
    const state = pmo.bus_state || pmo.ledger_status || 'unknown';
    const warn = state === 'stale' || state === 'held' ? ' org-context-warn' : '';
    const pmoTimer = pmo.since ? liveTimerSpan(pmo.since, 'PMO ledger', { stale: state === 'stale' }) : '';
    chips.push(
      `<div class="org-context-chip${warn}" title="${esc(pmo.note || '')}">PMO ${esc(pmo.task_id)} · ${esc(state)} ${pmoTimer}</div>`
    );
  } else if (ctx?.focus?.task_id) {
    chips.push(
      `<div class="org-context-chip">${esc(ctx.focus.task_id)} · ${esc(ctx.focus.status || '—')}</div>`
    );
  }
  if (ctx?.budget?.weekly_usd != null) {
    chips.push(
      `<div class="org-context-chip">$${ctx.budget.weekly_usd}/wk · $${ctx.budget.remaining_usd} left</div>`
    );
  }
  const running = (bus?.running || []).length;
  const held = (bus?.held || []).length;
  chips.push(`<div class="org-context-chip">${running} executing · ${held} held</div>`);
  el.innerHTML = chips.join('');
}

function bindOrgFleetFilters() {
  const el = $('org-fleet-filters');
  if (!el || el.dataset.bound) return;
  el.dataset.bound = '1';
  const filters = [
    ['now', 'Working now'],
    ['scheduled', 'Scheduled'],
    ['asleep', 'Asleep'],
    ['all', 'All'],
  ];
  const paint = () => {
    el.innerHTML = filters
      .map(
        ([id, label]) =>
          `<button type="button" class="btn btn-sm org-filter-btn${orgFleetFilter === id ? ' is-active' : ''}" data-filter="${id}">${esc(label)}</button>`
      )
      .join('');
  };
  paint();
  el.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-filter]');
    if (!btn) return;
    orgFleetFilter = btn.dataset.filter;
    el.querySelectorAll('.org-filter-btn').forEach((b) => {
      b.classList.toggle('is-active', b.dataset.filter === orgFleetFilter);
    });
    renderOrgFleet(orgFleetDataCache, busLiveDataCache);
  });
}

function busWorkCard(job, kind) {
  const session = job.to_session ? `<span class="fleet-pipe-step">${esc(job.to_session)}</span>` : '';
  const hold =
    kind === 'held' && job.hold_reason
      ? `<p class="fleet-job-hold">${esc(job.hold_reason)}</p>`
      : '';
  const title = fleetJobTitle(job);
  const jobBrief = jobMemoHref(job.job_id);
  const missionBrief = job.mission_id ? memoHref('queue', job.mission_id) : null;
  const preview = job.objective_preview
    ? `<p class="fleet-job-preview">${esc(job.objective_preview)}</p>`
    : '';
  const links = [];
  if (jobBrief) {
    links.push(`<a class="fleet-job-link" href="${esc(jobBrief)}">Job brief</a>`);
  }
  if (missionBrief) {
    links.push(
      `<a class="fleet-job-link" href="${esc(missionBrief)}">${esc(job.mission_id)} mission</a>`
    );
  }
  const linkRow = links.length
    ? `<p class="fleet-job-links">${links.join('<span class="fleet-job-link-sep">·</span>')}</p>`
    : '';
  let timerRow = '';
  if (kind === 'running') {
    const sessionSince = job.started_at || job.updated_at || job.created_at;
    timerRow = `<p class="fleet-job-timers">${liveTimerSpan(sessionSince, 'Worker on')} ${liveTimerSpan(job.created_at, 'Job queued')}</p>`;
  } else if (kind === 'queued') {
    timerRow = `<p class="fleet-job-timers">${liveTimerSpan(job.created_at, 'Queued')}</p>`;
  } else if (kind === 'held') {
    timerRow = `<p class="fleet-job-timers">${liveTimerSpan(job.updated_at || job.created_at, 'Held')}</p>`;
  }
  const fullId =
    job.job_id && (job.short_job_id || shortJobId(job.job_id)) !== job.job_id
      ? `<p class="fleet-job-id" title="${esc(job.job_id)}">${esc(job.job_id)}</p>`
      : '';
  return `<article class="fleet-job-card fleet-job-${esc(kind)}">
    <div class="fleet-job-route">
      <span class="fleet-pipe-step">Nick</span><span class="fleet-pipe-arrow">→</span>
      <span class="fleet-pipe-step">harness</span><span class="fleet-pipe-arrow">→</span>
      ${session || `<span class="fleet-pipe-step">${esc(job.lane || 'worker')}</span>`}
    </div>
    <h4 class="fleet-job-title">${jobBrief ? `<a class="fleet-job-title-link" href="${esc(jobBrief)}">${esc(title)}</a>` : esc(title)}</h4>
    ${fullId}
    <p class="fleet-job-meta">${esc(job.repo || '')} · ${esc(job.worker_status || job.status || kind)}</p>
    ${timerRow}
    ${preview}
    ${linkRow}
    ${hold}
  </article>`;
}

function collectOrgNodes(root) {
  const scheduled = [];
  const liveInfra = [];
  const asleepBucket = [];
  let asleepCount = 0;

  for (const child of root?.children || []) {
    if (child.id === 'asleep_bucket' || (ORG_ASLEEP.has(child.status) && (child.children || []).length)) {
      const bucketKids = (child.children || []).filter((c) => c.id !== 'asleep_more');
      asleepCount = bucketKids.length;
      const moreLine = (child.children || []).find((c) => c.id === 'asleep_more');
      if (moreLine?.title) {
        const m = moreLine.title.match(/\+(\d+)/);
        if (m) asleepCount += parseInt(m[1], 10);
      }
      asleepBucket.push(child, ...bucketKids);
    } else if (ORG_SCHEDULED.has(child.status)) {
      scheduled.push(child);
    } else if (ORG_LIVE.has(child.status)) {
      liveInfra.push(child);
    } else if (ORG_ASLEEP.has(child.status)) {
      asleepBucket.push(child);
      asleepCount += 1;
    }
  }
  return { scheduled, liveInfra, asleepBucket, asleepCount };
}

function renderAsleepAccordion(asleepBucket, asleepCount) {
  if (!asleepBucket.length) return '<p class="empty">No budget-gated roles.</p>';
  const bucketNode = asleepBucket[0];
  const inner = asleepBucket
    .slice(1)
    .map((n) => orgRoleCard(n, { compact: true }))
    .join('');
  const label = bucketNode.detail || `${asleepCount || asleepBucket.length - 1} roles asleep`;
  return `<details class="org-asleep-accordion" open>
    <summary>
      <span class="org-asleep-icon">${esc(bucketNode.icon || '💤')}</span>
      <span class="org-asleep-label">${esc(bucketNode.title || 'Budget-gated roles')}</span>
      <span class="org-asleep-count">${esc(label)}</span>
    </summary>
    <div class="org-card-grid org-card-grid-compact">${inner}</div>
  </details>`;
}

function renderOrgFleetBoard(root, bus) {
  const { scheduled, liveInfra, asleepBucket, asleepCount } = collectOrgNodes(root);
  const running = bus?.running || [];
  const queued = bus?.queued || [];
  const held = bus?.held || [];
  const done = bus?.recent_completed || [];

  if (orgFleetFilter === 'scheduled') {
    if (!scheduled.length) return '<p class="empty">No scheduled roles.</p>';
    return `<div class="org-card-grid">${scheduled.map((n) => orgRoleCard(n)).join('')}</div>`;
  }

  if (orgFleetFilter === 'asleep') {
    return renderAsleepAccordion(asleepBucket, asleepCount);
  }

  if (orgFleetFilter === 'all') {
    let html = renderOrgFleetNowBoard(running, queued, held, liveInfra);
    if (scheduled.length) {
      html += `<div class="fleet-section"><h3 class="fleet-section-title">Scheduled</h3><div class="org-card-grid">${scheduled.map((n) => orgRoleCard(n)).join('')}</div></div>`;
    }
    html += `<div class="fleet-section"><h3 class="fleet-section-title">Asleep</h3>${renderAsleepAccordion(asleepBucket, asleepCount)}</div>`;
    if (done.length) {
      html += `<div class="fleet-section fleet-section-done"><h3 class="fleet-section-title">Recently done</h3><ul class="bus-done-list">${done.map((j) => {
        const href = jobMemoHref(j.job_id);
        const label = fleetJobTitle(j);
        return `<li>${href ? `<a class="fleet-job-link" href="${esc(href)}">${esc(label)}</a>` : esc(label)}</li>`;
      }).join('')}</ul></div>`;
    }
    return html;
  }

  return renderOrgFleetNowBoard(running, queued, held, liveInfra);
}

function renderOrgFleetNowBoard(running, queued, held, liveInfra) {
  const parts = [];
  if (running.length) {
    parts.push(
      `<div class="fleet-section"><h3 class="fleet-section-title">Executing now <span class="bus-section-count">${running.length}</span></h3>
      <div class="fleet-job-grid">${running.map((j) => busWorkCard(j, 'running')).join('')}</div></div>`
    );
  }
  if (held.length) {
    parts.push(
      `<div class="fleet-section"><h3 class="fleet-section-title">Held <span class="bus-section-count">${held.length}</span></h3>
      <div class="fleet-job-grid">${held.map((j) => busWorkCard(j, 'held')).join('')}</div></div>`
    );
  }
  if (queued.length) {
    parts.push(
      `<div class="fleet-section"><h3 class="fleet-section-title">Queued <span class="bus-section-count">${queued.length}</span></h3>
      <div class="fleet-job-grid fleet-job-grid-compact">${queued.map((j) => busWorkCard(j, 'queued')).join('')}</div></div>`
    );
  }
  if (liveInfra.length) {
    parts.push(
      `<div class="fleet-section"><h3 class="fleet-section-title">Always on</h3>
      <div class="org-card-grid org-card-grid-compact">${liveInfra.map((n) => orgRoleCard(n, { compact: true })).join('')}</div></div>`
    );
  }
  if (!parts.length) {
    return '<p class="empty">Nothing executing on the bus right now.</p>';
  }
  return parts.join('');
}

function renderOrgFleet(orgData, busData) {
  const tree = $('org-fleet-tree');
  const updated = $('org-fleet-updated');
  const legend = $('org-fleet-legend');
  if (!tree) return;
  orgFleetDataCache = orgData;
  busLiveDataCache = busData;
  bindOrgFleetFilters();
  if (!orgData?.root && !busData) {
    tree.innerHTML = '<p class="empty">Fleet data not available.</p>';
    return;
  }
  renderOrgFleetContext(orgData?.context, busData);
  tree.innerHTML = renderOrgFleetBoard(orgData?.root || { children: [] }, busData);
  if (legend) {
    const showLegend = orgFleetFilter === 'all';
    legend.hidden = !showLegend;
    if (showLegend && orgData?.legend) renderOrgFleetLegend(orgData.legend);
  }
  const ts = busData?.generated_at || orgData?.generated_at;
  if (updated) {
    if (ts) {
      updated.dataset.busGeneratedAt = ts;
      updated.classList.toggle('meta-stale', (ageMs(ts) || 0) >= BUS_STALE_MS);
    } else {
      delete updated.dataset.busGeneratedAt;
    }
  }
  startLiveTimers();
}

async function loadOrgFleet() {
  try {
    const res = await fetch(`${dataUrls.orgFleet}?t=${Date.now()}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    console.warn('org-fleet load failed', e);
    return null;
  }
}

async function loadBusLive() {
  try {
    const res = await fetch(`${dataUrls.busLive}?t=${Date.now()}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    console.warn('bus-live load failed', e);
    return null;
  }
}

async function refreshFleetPanel() {
  const [orgFleet, busLive] = await Promise.all([loadOrgFleet(), loadBusLive()]);
  renderOrgFleet(orgFleet, busLive);
}

function renderAll(state) {
  renderCurrentFocus(state);
  renderSnapshot(state);
  renderActivity(state.sorted, state);
  renderQueue(state);
  renderCompleted(state);
  renderBudget(state);
  renderTrust(state);
  renderNickGate(state);
  renderRoadmap(state);
  renderArtifacts(state);

  const latest = state.sorted[state.sorted.length - 1];
  const lastUp = $('last-updated');
  if (lastUp) {
    if (latest?.ts) {
      lastUp.dataset.ledgerTs = latest.ts;
    } else {
      delete lastUp.dataset.ledgerTs;
      lastUp.textContent = 'No events';
    }
    if (dataUrls.source && dataUrls.source !== 'github-static') {
      lastUp.title = `Data: droplet live (${dataUrls.apiBase || 'same origin'})`;
    }
  }
  const tagline = document.querySelector('.tagline');
  if (tagline && dataUrls.source && dataUrls.source !== 'github-static') {
    tagline.textContent = 'AI-native operating company · droplet live ledger';
  }
  startLiveTimers();
}

function showError(msg) {
  const existing = document.querySelector('.error-banner');
  if (existing) existing.remove();
  const banner = document.createElement('div');
  banner.className = 'error-banner';
  banner.textContent = msg;
  document.querySelector('.container').prepend(banner);
}

async function refresh() {
  document.querySelector('.error-banner')?.remove();
  let events;
  let orgFleet = null;
  let busLive = null;
  try {
    [events, orgFleet, busLive] = await Promise.all([
      loadLedger(),
      loadOrgFleet(),
      loadBusLive(),
    ]);
    allEvents = events;
  } catch (err) {
    const hint = dataUrls.source === 'github-static'
      ? ' Set config.json liveDataApi to your droplet gate URL, or open the dashboard on :8788.'
      : ' Check gate server on droplet (port 8788) and /api/live/ledger.';
    showError(`Could not load ledger: ${err.message}.${hint}`);
    console.error(err);
    return;
  }
  try {
    renderOrgFleet(orgFleet, busLive);
    renderAll(buildState(events));
  } catch (err) {
    showError(`Could not render dashboard: ${err.message}`);
    console.error(err);
    try {
      setFocusPanel(pickCurrentFocus(buildState(events)), buildState(events));
    } catch (_) { /* ignore */ }
  }
}

$('refresh-btn').addEventListener('click', refresh);
$('activity-filter').addEventListener('input', (e) => {
  filterText = e.target.value;
  if (allEvents.length) {
    const st = buildState(allEvents);
    renderActivity(st.sorted, st);
  }
});

async function refreshGatedSection() {
  if (!allEvents.length) return;
  try {
    const res = await fetch(`${dataUrls.gated}?t=${Date.now()}`);
    if (res.ok) {
      const gatedSnapshot = await res.json();
      const st = buildState(allEvents);
      const resolved = new Set(
        [...allEvents]
          .filter((e) => e.event === 'decision_resolved' || e.event === 'nick_gate_resolved')
          .map((e) => e.task_id)
          .filter(Boolean)
      );
      st.gatedByNick = gatedSnapshot
        .filter((g) => !resolved.has(g.task_id))
        .map((g) => ({
          task_id: g.task_id,
          task: g.task,
          priority: g.priority,
          output: g.what_nick_must_do,
          ts: g.since,
        }));
      renderNickGate(st);
      renderSnapshot(st);
    }
  } catch (e) {
    console.warn('gated poll failed', e);
  }
}

window.addEventListener('message', (ev) => {
  if (ev.data?.type === 'nick2-gate-updated') {
    refresh();
    refreshGatedSection();
  }
});

(async function boot() {
  dataUrls = await Nick2LiveConfig.resolveLiveDataUrls();
  await refresh();
})();
setInterval(refresh, 5 * 60 * 1000);
setInterval(refreshGatedSection, GATED_POLL_MS);
setInterval(refreshFleetPanel, BUS_LIVE_POLL_MS);