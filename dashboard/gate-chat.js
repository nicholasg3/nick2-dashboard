/**
 * Gate room — MKA brief (HTML) + Nick ↔ agent chat per gated item.
 * Opens in its own window from the dashboard Discuss button.
 *
 * Live web chat: set config.gateChatApi (gate_chat_server.py behind auth).
 * Until then: Send opens Telegram with full gate context (temporary workaround).
 */
(function (global) {
  const CHAT_URL = (taskId) => `logs/gate-chats/${taskId}.jsonl`;
  const BRIEFS_URL = 'reports/gate-briefs.json';

  let config = { gateChatApi: '', pollIntervalMs: 8000, telegramDeepLink: '' };
  let pollTimer = null;
  let activeTaskId = null;
  let cachedBrief = null;

  async function loadConfig() {
    try {
      const res = await fetch(`config.json?t=${Date.now()}`);
      if (res.ok) config = { ...config, ...(await res.json()) };
    } catch (_) { /* defaults */ }
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s ?? '';
    return d.innerHTML;
  }

  function stripMd(s) {
    return String(s || '').replace(/\*\*/g, '');
  }

  function fmtTs(ts) {
    if (!ts) return '';
    try {
      return new Date(ts).toLocaleString('en-SG', {
        timeZone: 'Asia/Singapore',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return ts;
    }
  }

  function pendingKey(taskId) {
    return `nick2-gate-pending-${taskId}`;
  }

  function loadPending(taskId) {
    try {
      return JSON.parse(localStorage.getItem(pendingKey(taskId)) || '[]');
    } catch {
      return [];
    }
  }

  function savePending(taskId, text) {
    const prev = loadPending(taskId);
    prev.push({ ts: new Date().toISOString(), text, role: 'nick', actor: 'Nicholas' });
    localStorage.setItem(pendingKey(taskId), JSON.stringify(prev));
  }

  function clearPending(taskId) {
    localStorage.removeItem(pendingKey(taskId));
  }

  function notifyGateUpdate(taskId) {
    try {
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage({ type: 'nick2-gate-updated', taskId }, '*');
      }
    } catch (_) { /* ignore */ }
  }

  async function fetchMessages(taskId) {
    const api = (config.gateChatApi || '').replace(/\/$/, '');
    if (api) {
      try {
        const res = await fetch(`${api}/api/gate/${taskId}/messages?t=${Date.now()}`);
        if (res.ok) {
          const data = await res.json();
          return (data.messages || []).sort((a, b) => new Date(a.ts) - new Date(b.ts));
        }
      } catch (_) { /* fall through */ }
    }

    let server = [];
    try {
      const res = await fetch(`${CHAT_URL(taskId)}?t=${Date.now()}`);
      if (res.ok) {
        const text = await res.text();
        server = text
          .trim()
          .split('\n')
          .filter(Boolean)
          .map((line) => {
            try {
              return JSON.parse(line);
            } catch {
              return null;
            }
          })
          .filter(Boolean);
      }
    } catch (_) { /* offline */ }

    const pending = loadPending(taskId).map((p) => ({
      ts: p.ts,
      role: 'nick',
      actor: p.actor || 'Nicholas',
      text: p.text,
      pending: true,
    }));
    return [...server, ...pending].sort((a, b) => new Date(a.ts) - new Date(b.ts));
  }

  function renderMessages(el, messages) {
    if (!messages.length) {
      el.innerHTML =
        '<p class="gate-chat-empty">No messages yet. Tell the agent what you need to clear this gate.</p>';
      return;
    }
    el.innerHTML = messages
      .map((m) => {
        const role = m.role === 'nick' ? 'nick' : 'agent';
        const who = m.actor || (role === 'nick' ? 'Nicholas' : 'Agent');
        const pending = m.pending ? ' <em>(pending sync)</em>' : '';
        return `<div class="gate-chat-msg gate-chat-msg-${role}">
          <div class="gate-chat-msg-head"><strong>${esc(who)}</strong> <span>${fmtTs(m.ts)}${pending}</span></div>
          <div class="gate-chat-msg-body">${esc(m.text)}</div>
        </div>`;
      })
      .join('');
    el.scrollTop = el.scrollHeight;
  }

  function renderBrief(el, brief, task) {
    if (!brief) {
      el.innerHTML = `<p class="empty">${esc(task?.output || 'No brief loaded.')}</p>`;
      return;
    }
    const mece = (brief.mece || [])
      .map(
        ([b, scope, state]) =>
          `<tr><td>${esc(b)}</td><td>${esc(scope)}</td><td>${esc(state)}</td></tr>`
      )
      .join('');
    const options = (brief.options || [])
      .map((o, i) => {
        const letter = String.fromCharCode(65 + i);
        return `<div class="gate-brief-option"><strong>Option ${letter}: ${esc(o.name)}</strong>
          <p>${esc(o.upside)}</p><p class="muted">${esc(o.downside)}</p></div>`;
      })
      .join('');
    el.innerHTML = `
      <div class="gate-brief-tag">MKA Decision Memo</div>
      <h3>${esc(brief.task_id)}: ${esc(brief.title)}</h3>
      <p class="gate-brief-meta">Priority ${esc(brief.priority)} · #${brief.rank} in queue</p>
      <h4>1. Executive Framing</h4>
      <p><strong>Objective</strong><br>${esc(brief.objective)}</p>
      <p><strong>Decision</strong><br>${esc(stripMd(brief.decision))}</p>
      ${mece ? `<h4>2. MECE</h4><table class="gate-brief-table"><thead><tr><th>Bucket</th><th>Scope</th><th>State</th></tr></thead><tbody>${mece}</tbody></table>` : ''}
      <h4>3. Root cause</h4><p>${esc(brief.root_cause)}</p>
      ${options ? `<h4>4. Strategic options</h4>${options}` : ''}
      <h4>5. Recommendation</h4><p>${esc(stripMd(brief.recommendation))}</p>
      <h4>What Nick must do</h4><p>${esc(brief.what_nick_must_do)}</p>`;
  }

  async function loadBrief(taskId) {
    try {
      const res = await fetch(`${BRIEFS_URL}?t=${Date.now()}`);
      if (!res.ok) return null;
      const all = await res.json();
      return all[taskId] || null;
    } catch {
      return null;
    }
  }

  function telegramUrl(text) {
    const base = config.telegramDeepLink || 'https://t.me/NMGs_Hermes_bot';
    return `${base}?text=${encodeURIComponent(text)}`;
  }

  async function buildOutboundMessage(taskId, text, taskMeta, kind) {
    const brief = cachedBrief || (await loadBrief(taskId));
    const title = brief?.title || taskMeta?.task || taskId;
    const lines = [`[Nick2 Gate ${taskId}]`, title, ''];
    if (brief?.objective) lines.push(`Objective: ${brief.objective}`);
    if (brief?.decision) lines.push(`Decision: ${stripMd(brief.decision)}`);
    if (brief?.what_nick_must_do) lines.push(`Needs: ${brief.what_nick_must_do}`);
    lines.push('');
    if (kind === 'clear') {
      lines.push(`Nick clears gate ${taskId}:`);
      lines.push(text || 'Approved / resolved. Append nick_gate_resolved to ledger.');
    } else {
      lines.push('Nick instructs:');
      lines.push(text);
    }
    lines.push('');
    lines.push('(Reply in gate thread; COO will append ledger events.)');
    return lines.join('\n');
  }

  function bridgeLive() {
    return Boolean((config.gateChatApi || '').trim());
  }

  function renderBridgeBanner(el) {
    if (bridgeLive()) {
      el.innerHTML =
        '<span class="gate-bridge-live">● Live web bridge</span> — messages go directly to the agent with full gate context.';
    } else {
      el.innerHTML =
        '<span class="gate-bridge-off">○ Offline mode</span> — Set gateChatApi in config.json to the live gate bridge (HTTPS). Until then, Send falls back to Telegram.';
    }
  }

  async function sendMessage(taskId, text, taskMeta, statusEl, messagesEl) {
    const api = (config.gateChatApi || '').replace(/\/$/, '');
    if (api) {
      statusEl.textContent = 'Sending to agent…';
      try {
        const res = await fetch(`${api}/api/gate/${taskId}/message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, actor: 'Nicholas' }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        clearPending(taskId);
        statusEl.textContent = data.resolved
          ? 'Sent and gate cleared — dashboard queue will refresh.'
          : 'Sent — worker dispatched with full gate context.';
        const msgs = await fetchMessages(taskId);
        renderMessages(messagesEl, msgs);
        if (data.resolved) notifyGateUpdate(taskId);
        return true;
      } catch (err) {
        statusEl.textContent = `Bridge error: ${err.message}. Falling back to Telegram.`;
      }
    }

    savePending(taskId, text);
    const outbound = await buildOutboundMessage(taskId, text, taskMeta, 'send');
    window.open(telegramUrl(outbound), '_blank', 'noopener');
    const msgs = await fetchMessages(taskId);
    renderMessages(messagesEl, msgs);
    statusEl.textContent =
      'Opened Telegram with full gate context. Agent reply will sync here after ledger/chat update.';
    return false;
  }

  async function resolveGate(taskId, note, taskMeta, statusEl, messagesEl) {
    const api = (config.gateChatApi || '').replace(/\/$/, '');
    if (api) {
      statusEl.textContent = 'Clearing gate…';
      try {
        const res = await fetch(`${api}/api/gate/${taskId}/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note, actor: 'Nicholas' }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        clearPending(taskId);
        statusEl.textContent = 'Gate cleared — queue will refresh on the dashboard.';
        const msgs = await fetchMessages(taskId);
        renderMessages(messagesEl, msgs);
        notifyGateUpdate(taskId);
        return true;
      } catch (err) {
        statusEl.textContent = `Could not clear gate: ${err.message}`;
        return false;
      }
    }
    const outbound = await buildOutboundMessage(taskId, note, taskMeta, 'clear');
    window.open(telegramUrl(outbound), '_blank', 'noopener');
    statusEl.textContent =
      'Opened Telegram to confirm gate clearance. Set gateChatApi for direct web resolve.';
    return false;
  }

  function startPolling(taskId, messagesEl) {
    stopPolling();
    const tick = async () => {
      if (activeTaskId !== taskId) return;
      try {
        const msgs = await fetchMessages(taskId);
        renderMessages(messagesEl, msgs);
      } catch (_) { /* ignore */ }
    };
    tick();
    pollTimer = setInterval(tick, config.pollIntervalMs || 8000);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  async function mountGateChat(root, taskMeta) {
    await loadConfig();
    activeTaskId = taskMeta.task_id;
    cachedBrief = await loadBrief(taskMeta.task_id);

    root.innerHTML = `
      <div class="gate-room-layout">
        <div class="gate-brief-panel" id="gate-brief-panel"></div>
        <div class="gate-chat-panel">
          <p class="gate-bridge-banner" id="gate-bridge-banner"></p>
          <div class="gate-chat-head">
            <h3>Discuss with agent</h3>
            <p class="muted">Instructions for <strong>${esc(taskMeta.task_id)}</strong> — agent uses the MKA brief on the left.</p>
          </div>
          <div class="gate-chat-messages" id="gate-chat-messages"></div>
          <form class="gate-chat-form" id="gate-chat-form">
            <textarea id="gate-chat-input" rows="4" placeholder="e.g. Approve default PMO scoring framework for pilot on top 3 issues…" required></textarea>
            <div class="gate-chat-actions">
              <button type="submit" class="btn btn-primary">Send to agent</button>
              <button type="button" class="btn btn-ghost" id="gate-chat-clear-gate">Mark gate cleared</button>
            </div>
          </form>
          <p class="gate-chat-status" id="gate-chat-status"></p>
        </div>
      </div>`;

    const briefEl = root.querySelector('#gate-brief-panel');
    const messagesEl = root.querySelector('#gate-chat-messages');
    const form = root.querySelector('#gate-chat-form');
    const input = root.querySelector('#gate-chat-input');
    const statusEl = root.querySelector('#gate-chat-status');
    const clearBtn = root.querySelector('#gate-chat-clear-gate');
    const bannerEl = root.querySelector('#gate-bridge-banner');

    renderBrief(briefEl, cachedBrief, taskMeta);
    renderBridgeBanner(bannerEl);
    const msgs = await fetchMessages(taskMeta.task_id);
    renderMessages(messagesEl, msgs);
    startPolling(taskMeta.task_id, messagesEl);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      await sendMessage(taskMeta.task_id, text, taskMeta, statusEl, messagesEl);
    });

    clearBtn.addEventListener('click', async () => {
      const tid = taskMeta.task_id;
      const note = input.value.trim() || 'Gate cleared by Nicholas via dashboard.';
      input.value = '';
      await resolveGate(tid, note, taskMeta, statusEl, messagesEl);
    });
  }

  function unmountGateChat() {
    activeTaskId = null;
    cachedBrief = null;
    stopPolling();
  }

  global.Nick2GateChat = { mountGateChat, unmountGateChat, loadConfig, openGateRoom: null };
})(window);