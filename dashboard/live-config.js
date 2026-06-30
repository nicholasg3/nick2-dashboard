/**
 * Resolve dashboard data URLs — droplet live API vs GitHub Pages static copies.
 */
(function (global) {
  const STATIC = {
    ledger: 'logs/ceo-ledger.jsonl',
    busLive: 'reports/bus-live.json',
    orgFleet: 'reports/org-fleet.json',
    gated: 'reports/gated.json',
    deferredWork: 'reports/deferred-work.json',
    ceoQueue: 'reports/ceo-queue.json',
    gateBriefs: 'reports/gate-briefs.json',
    orchestrator: 'reports/orchestrator/status.json',
  };

  let cached = null;

  function apiBaseFromConfig(cfg) {
    const explicit = (cfg.liveDataApi || cfg.gateChatApi || '').replace(/\/$/, '');
    if (explicit) return explicit;
    if (cfg.dataSource === 'droplet') {
      if (location.port === '8788' || location.hostname === 'localhost') return '';
      return explicit;
    }
    return '';
  }

  async function resolveLiveDataUrls() {
    if (cached) return cached;
    let cfg = {};
    try {
      cfg = await fetch(`config.json?t=${Date.now()}`).then((r) => r.json());
    } catch (e) {
      console.warn('live-config: config.json unavailable', e);
    }
    const base = apiBaseFromConfig(cfg);
    const useLive = Boolean(base || cfg.dataSource === 'droplet');
    if (useLive && (base || location.port === '8788')) {
      const prefix = base ? base : '';
      cached = {
        source: 'droplet',
        apiBase: prefix,
        ledger: `${prefix}/api/live/ledger`,
        busLive: `${prefix}/api/live/bus-live`,
        orgFleet: `${prefix}/api/live/org-fleet`,
        gated: `${prefix}/api/live/gated`,
        ceoQueue: `${prefix}/api/live/ceo-queue`,
        gateBriefs: `${prefix}/api/live/gate-briefs`,
        orchestrator: `${prefix}/api/live/orchestrator`,
        gateChatApi: (cfg.gateChatApi || prefix).replace(/\/$/, ''),
      };
    } else if (cfg.dataSource === 'droplet' && cfg.gateChatApi) {
      const b = cfg.gateChatApi.replace(/\/$/, '');
      cached = {
        source: 'droplet-remote',
        apiBase: b,
        ledger: `${b}/api/live/ledger`,
        busLive: `${b}/api/live/bus-live`,
        orgFleet: `${b}/api/live/org-fleet`,
        gated: `${b}/api/live/gated`,
        ceoQueue: `${b}/api/live/ceo-queue`,
        gateBriefs: `${b}/api/live/gate-briefs`,
        orchestrator: `${b}/api/live/orchestrator`,
        gateChatApi: b,
      };
    } else {
      cached = { source: 'github-static', apiBase: '', gateChatApi: cfg.gateChatApi || '', ...STATIC };
    }
    return cached;
  }

  function resetLiveConfigCache() {
    cached = null;
  }

  global.Nick2LiveConfig = { resolveLiveDataUrls, resetLiveConfigCache, STATIC };
})(typeof window !== 'undefined' ? window : globalThis);
