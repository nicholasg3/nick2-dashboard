/**
 * Nick2 Operating Dashboard
 * Source of truth: logs/ceo-ledger.jsonl (append-only)
 */

const LEDGER_URL = 'logs/ceo-ledger.jsonl';
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

async function loadLedger() {
  const res = await fetch(`${LEDGER_URL}?t=${Date.now()}`);
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

    if (ev.actor === 'CEO' && ACTIVE_STATUSES.has(ev.status)) {
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
      value: state.currentCeoTask?.task?.slice(0, 40) || 'Idle',
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
      <div class="stat-value">${esc(String(c.value))}</div>
      <div class="stat-sub">${esc(c.sub)}</div>
    </div>`
    )
    .join('');
}

function renderActivity(events) {
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
      <div class="feed-task">${esc(ev.task || ev.task_id || '')}</div>
      <div class="feed-output">${esc(ev.output || '')}${ev.cost_usd ? ` · ${fmtUsd(ev.cost_usd)}` : ''}</div>
    </div>`
    )
    .join('');
}

function renderTable(el, headers, rows, emptyMsg) {
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

function memoHref(kind, taskId) {
  if (!taskId) return null;
  return `memos/${kind}/${taskId}.md`;
}

function memoLink(kind, taskId) {
  const href = memoHref(kind, taskId);
  if (!href) return '—';
  return `<a class="memo-link" href="${href}" target="_blank" rel="noopener">memo</a>`;
}

function renderCurrentFocus(state) {
  const inProg = state.active.find((t) => t.status === 'in_progress');
  const focus = inProg || state.focusSnapshot || state.active[0];
  if (!focus) {
    $('focus-headline').textContent = 'Idle — no active work in queue';
    $('focus-detail').textContent = 'Check the roadmap or authorize work in the ledger.';
    $('focus-meta').innerHTML = '';
    return;
  }
  const owner = focus.owner || focus.actor || 'CEO';
  $('focus-headline').textContent = `${owner}: ${focus.task || '—'}`;
  $('focus-detail').textContent = focus.output || '';
  const memoPath = focus.focus_task_id
    ? memoHref('queue', focus.focus_task_id)
    : memoHref('queue', focus.task_id);
  if (memoPath) {
    $('focus-memo-link').href = memoPath;
    $('focus-memo-link').textContent = `Task memo (${focus.task_id || focus.focus_task_id}) →`;
  }
  $('focus-meta').innerHTML = `
    <span class="meta-pill">${badge(focus.status)}</span>
    <span class="meta-pill">${esc(focus.task_id || focus.focus_task_id || '')}</span>
    <span class="meta-pill">Updated ${fmtTs(focus.ts)}</span>`;
}

function renderQueue(state) {
  const rows = state.active.map(
    (t) => `<tr>
      <td>${badge(t.status)}</td>
      <td>${esc(t.owner || t.actor)}</td>
      <td>${esc(t.task)}</td>
      <td>${esc(t.task_id || '')}</td>
      <td>${memoLink('queue', t.task_id)}</td>
      <td>${fmtTs(t.ts)}</td>
    </tr>`
  );
  renderTable(
    $('work-queue'),
    ['Status', 'Owner', 'Task', 'ID', 'Memo', 'Updated'],
    rows,
    'No active work in queue.'
  );
}

function renderCompleted(state) {
  const rows = state.completed.map(
    (t) => `<tr>
      <td>${fmtTs(t.ts)}</td>
      <td>${esc(t.actor)}</td>
      <td>${esc(t.task)}</td>
      <td>${fmtUsd(t.cost_usd || 0)}</td>
      <td>${memoLink('completed', t.task_id)}</td>
      <td>${esc((t.artifacts || []).join(', ') || '—')}</td>
    </tr>`
  );
  renderTable(
    $('completed-work'),
    ['Time', 'Owner', 'Task', 'Cost', 'Memo', 'Artifacts'],
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
      <td>${esc(g.task)}</td>
      <td>${esc(g.task_id || '')}</td>
      <td>${esc(g.output?.slice(0, 80) || '')}</td>
      <td>${memoLink('gated', g.task_id)}</td>
      <td>${fmtTs(g.ts)}</td>
    </tr>`
  );
  renderTable(
    $('nick-gate-queue'),
    ['#', 'Priority', 'Waiting on Nick', 'ID', 'What Nick must do', 'Memo', 'Since'],
    rows,
    'Nothing gated — all work is unblocked or agents are executing autonomously.'
  );
}

function renderRoadmap(state) {
  const byLane = {};
  for (const item of state.roadmap) {
    const lane = item.roadmap_lane || 'near_term';
    if (!byLane[lane]) byLane[lane] = [];
    byLane[lane].push(item);
  }

  const lanes = Object.keys(ROADMAP_LANES);
  $('roadmap-list').innerHTML = lanes
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
  if (!state.artifacts.length) {
    $('artifacts-list').innerHTML = '<p class="empty">No artifacts recorded yet.</p>';
    return;
  }
  $('artifacts-list').innerHTML = state.artifacts
    .sort()
    .map((a) => `<div class="artifact-item">${esc(a)}</div>`)
    .join('');
}

function renderAll(state) {
  renderCurrentFocus(state);
  renderSnapshot(state);
  renderActivity(state.sorted);
  renderQueue(state);
  renderCompleted(state);
  renderBudget(state);
  renderTrust(state);
  renderNickGate(state);
  renderRoadmap(state);
  renderArtifacts(state);

  const latest = state.sorted[state.sorted.length - 1];
  $('last-updated').textContent = latest ? `Last event: ${fmtTs(latest.ts)}` : 'No events';
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
  try {
    allEvents = await loadLedger();
    const state = buildState(allEvents);
    renderAll(state);
  } catch (err) {
    showError(`Could not load ledger: ${err.message}. Ensure GitHub Pages deployed logs/ceo-ledger.jsonl alongside the dashboard.`);
    console.error(err);
  }
}

$('refresh-btn').addEventListener('click', refresh);
$('activity-filter').addEventListener('input', (e) => {
  filterText = e.target.value;
  if (allEvents.length) renderActivity(buildState(allEvents).sorted);
});

refresh();
setInterval(refresh, 5 * 60 * 1000);