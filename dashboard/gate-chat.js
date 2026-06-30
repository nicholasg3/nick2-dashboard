/**
 * Gate chat — Nick ↔ agent thread for gated priority-queue items.
 * Messages persist in logs/gate-chats/{task_id}.jsonl (polled) or via gateChatApi POST.
 */
(function (global) {
  const CHAT_URL = (taskId) => `logs/gate-chats/${taskId}.jsonl`;
  const BRIEFS_URL = 'reports/gate-briefs.json';

  let config = { gateChatApi: '', pollIntervalMs: 8000, telegramDeepLink: '' };
  let pollTimer = null;
  let activeTaskId = null;

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

  async function fetchMessages(taskId) {
    const res = await fetch(`${CHAT_URL(taskId)}?t=${Date.now()}`);
    if (!res.ok) return [];
    const text = await res.text();
    return text
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

  function renderMessages(el, messages) {
    if (!messages.length) {
      el.innerHTML = '<p class="gate-chat-empty">No messages yet. Tell the agent what you need to clear this gate.</p>';
      return;
    }
    el.innerHTML = messages
      .map((m) => {
        const role = m.role === 'nick' ? 'nick' : 'agent';
        const who = m.actor || (role === 'nick' ? 'Nicholas' : 'Agent');
        return `<div class="gate-chat-msg gate-chat-msg-${role}">
          <div class="gate-chat-msg-head"><strong>${esc(who)}</strong> <span>${fmtTs(m.ts)}</span></div>
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
      .map(([b, scope, state]) => `<tr><td>${esc(b)}</td><td>${esc(scope)}</td><td>${esc(state)}</td></tr>`)
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
      <h4>Objective</h4><p>${esc(brief.objective)}</p>
      <h4>Decision</h4><p>${esc(brief.decision)}</p>
      ${mece ? `<h4>MECE</h4><table class="gate-brief-table"><thead><tr><th>Bucket</th><th>Scope</th><th>State</th></tr></thead><tbody>${mece}</tbody></table>` : ''}
      <h4>Root cause</h4><p>${esc(brief.root_cause)}</p>
      ${options ? `<h4>Options</h4>${options}` : ''}
      <h4>Recommendation</h4><p>${esc(brief.recommendation)}</p>
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

  function pendingKey(taskId) {
    return `nick2-gate-pending-${taskId}`;
  }

  function savePending(taskId, text) {
    const key = pendingKey(taskId);
    const prev = JSON.parse(localStorage.getItem(key) || '[]');
    prev.push({ ts: new Date().toISOString(), text });
    localStorage.setItem(key, JSON.stringify(prev));
  }

  function buildFallbackCommand(taskId, text) {
    const payload = JSON.stringify({ text }).replace(/'/g, "'\\''");
    const api = config.gateChatApi || 'http://127.0.0.1:8787';
    return `curl -s -X POST '${api}/api/gate/${taskId}/message' -H 'Content-Type: application/json' -d '${payload}'`;
  }

  function telegramLink(taskId, text) {
    const base = config.telegramDeepLink || 'https://t.me/NMGs_Hermes_bot';
    const msg = `[Gate ${taskId}] ${text}`;
    return `${base}?text=${encodeURIComponent(msg)}`;
  }

  async function sendMessage(taskId, text, statusEl) {
    const api = (config.gateChatApi || '').replace(/\/$/, '');
    if (api) {
      statusEl.textContent = 'Sending…';
      try {
        const res = await fetch(`${api}/api/gate/${taskId}/message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, actor: 'Nicholas' }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        statusEl.textContent = 'Sent — agent is responding.';
        return true;
      } catch (err) {
        statusEl.textContent = `Bridge error: ${err.message}`;
        savePending(taskId, text);
        return false;
      }
    }
    savePending(taskId, text);
    statusEl.innerHTML = `Bridge offline — message saved locally. Run on your Mac:<br><code class="gate-curl">${esc(buildFallbackCommand(taskId, text))}</code><br>Or <a href="${telegramLink(taskId, text)}" target="_blank" rel="noopener">send via Telegram</a>.`;
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

  /**
   * Mount gate chat into container.
   * @param {HTMLElement} root
   * @param {{ task_id, task, priority, output }} taskMeta
   */
  async function mountGateChat(root, taskMeta) {
    await loadConfig();
    activeTaskId = taskMeta.task_id;
    root.innerHTML = `
      <div class="gate-room-layout">
        <div class="gate-brief-panel" id="gate-brief-panel"></div>
        <div class="gate-chat-panel">
          <div class="gate-chat-head">
            <h3>Discuss with agent</h3>
            <p class="muted">Give instructions to clear <strong>${esc(taskMeta.task_id)}</strong>. Agent replies appear here and in the ledger.</p>
          </div>
          <div class="gate-chat-messages" id="gate-chat-messages"></div>
          <form class="gate-chat-form" id="gate-chat-form">
            <textarea id="gate-chat-input" rows="3" placeholder="e.g. Approve default framework for pilot. Use interim weights until we tune…" required></textarea>
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

    const brief = await loadBrief(taskMeta.task_id);
    renderBrief(briefEl, brief, taskMeta);
    startPolling(taskMeta.task_id, messagesEl);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      await sendMessage(taskMeta.task_id, text, statusEl);
      const msgs = await fetchMessages(taskMeta.task_id);
      renderMessages(messagesEl, msgs);
    });

    clearBtn.addEventListener('click', () => {
      const tid = taskMeta.task_id;
      const snippet = JSON.stringify(
        {
          actor: 'Nicholas',
          event: 'nick_gate_resolved',
          task_id: tid,
          task: taskMeta.task,
          status: 'completed',
          output: 'Cleared via gate chat on dashboard.',
          resolved_by: 'Nicholas',
        },
        null,
        2
      );
      statusEl.innerHTML = `Append to ledger when ready:<br><pre class="gate-ledger-snippet">${esc(snippet)}</pre>`;
    });
  }

  function unmountGateChat() {
    activeTaskId = null;
    stopPolling();
  }

  global.Nick2GateChat = { mountGateChat, unmountGateChat, loadConfig };
})(window);