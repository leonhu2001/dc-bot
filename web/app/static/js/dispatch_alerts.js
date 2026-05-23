(function () {
  const REFRESH_INTERVAL_MS = 5000;
  const ENABLED_KEY = 'mw_dispatch_alert_enabled';
  let enabled = localStorage.getItem(ENABLED_KEY) === '1';
  let checking = false;
  let audioContext = null;
  let lastCount = null;

  function isDispatchPage() {
    return window.location.pathname === '/dispatch';
  }

  function getAudioContext() {
    const AudioClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioClass) return null;

    if (!audioContext) {
      audioContext = new AudioClass();
    }

    if (audioContext.state === 'suspended') {
      audioContext.resume().catch(() => {});
    }

    return audioContext;
  }

  function tone(ctx, freq, start, duration, volume) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, start);

    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start(start);
    osc.stop(start + duration + 0.05);
  }

  function dingDong() {
    if (!enabled) return;

    const ctx = getAudioContext();
    if (!ctx) return;

    const now = ctx.currentTime;
    tone(ctx, 880, now, 0.2, 0.18);
    tone(ctx, 660, now + 0.18, 0.28, 0.16);
  }

  function makeButton() {
    if (document.querySelector('.dispatch-alert-toggle')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dispatch-alert-toggle';
    btn.textContent = enabled ? '🔔 新單提示已開' : '🔕 開啟新單提示';

    btn.addEventListener('click', () => {
      enabled = !enabled;
      localStorage.setItem(ENABLED_KEY, enabled ? '1' : '0');

      if (enabled) {
        getAudioContext();
        dingDong();
      }

      btn.textContent = enabled ? '🔔 新單提示已開' : '🔕 開啟新單提示';
    });

    document.body.appendChild(btn);
  }

  async function fetchState() {
    const res = await fetch('/dispatch/state?t=' + Date.now(), {
      cache: 'no-store',
      credentials: 'same-origin'
    });

    if (!res.ok) return null;

    const data = await res.json();

    if (!data || !data.ok) return null;

    return data;
  }

  function getPageWebKeys() {
    const text = document.body.innerText || '';
    const matches = text.match(/WEB-\\d+/g) || [];

    return Array.from(new Set(matches.map((value) => value.replace('WEB-', '')))).sort();
  }

  function normalizeKeys(keys) {
    return (keys || []).map(String).sort();
  }

  function sameKeys(a, b) {
    if (a.length !== b.length) return false;

    for (let i = 0; i < a.length; i += 1) {
      if (a[i] !== b[i]) return false;
    }

    return true;
  }

  function shouldSkipReload() {
    const el = document.activeElement;
    if (!el) return false;

    return ['input', 'textarea', 'select'].includes(el.tagName.toLowerCase());
  }

  async function check() {
    if (checking || !isDispatchPage()) return;
    checking = true;

    try {
      const data = await fetchState();

      if (!data) return;

      const apiKeys = normalizeKeys(data.keys || []);
      const pageKeys = getPageWebKeys();

      console.log('[dispatch-alert] poll', {
        apiKeys,
        pageKeys,
        count: data.count,
        signature: data.signature
      });

      if (lastCount !== null && Number(data.count || 0) > lastCount) {
        dingDong();
      }

      lastCount = Number(data.count || 0);

      if (!sameKeys(apiKeys, pageKeys)) {
        console.log('[dispatch-alert] page mismatch, reloading');

        if (!shouldSkipReload()) {
          window.location.reload();
        }
      }
    } catch (err) {
      console.warn('[dispatch-alert] check failed', err);
    } finally {
      checking = false;
    }
  }

  async function init() {
    if (!isDispatchPage()) return;

    makeButton();

    const data = await fetchState();
    if (data) {
      lastCount = Number(data.count || 0);
    }

    setInterval(check, REFRESH_INTERVAL_MS);
    setTimeout(check, 1000);

    console.log('[dispatch-alert] started v4');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
