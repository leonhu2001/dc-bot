(function () {
  if (window.__mwDispatchAlertsStarted) {
    return;
  }
  window.__mwDispatchAlertsStarted = true;

  const HOURLY_REFRESH_MS = 60 * 60 * 1000;
  const ENABLED_KEY = 'mw_dispatch_alert_enabled';

  let enabled = localStorage.getItem(ENABLED_KEY) === '1';
  let audioContext = null;
  let pendingAlert = false;
  let knownKeys = null;
  let eventSource = null;
  let refreshPromise = null;
  let queuedAlertRefresh = false;

  function isDispatchPage() {
    return window.location.pathname === '/dispatch';
  }

  function getAudioContext() {
    const AudioClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioClass) return null;

    if (!audioContext) {
      audioContext = new AudioClass();
    }

    return audioContext;
  }

  function isAudioReady() {
    return Boolean(audioContext && audioContext.state === 'running');
  }

  async function unlockAudio() {
    const ctx = getAudioContext();
    if (!ctx) return false;

    try {
      if (ctx.state !== 'running') {
        await ctx.resume();
      }
    } catch (err) {
      console.warn('[dispatch-alert] audio unlock failed', err);
    }

    updateButton();
    return ctx.state === 'running';
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

  function crispChimeTone(ctx, freq, start, duration, volume, harmonics) {
    tone(ctx, freq, start, duration, volume);

    (harmonics || []).forEach(([multiple, gain]) => {
      tone(
        ctx,
        freq * multiple,
        start,
        duration,
        volume * gain
      );
    });
  }

  async function dingDong() {
    if (!enabled || !audioContext) return false;

    if (audioContext.state !== 'running') {
      try {
        await audioContext.resume();
      } catch (err) {
        console.warn('[dispatch-alert] audio resume failed', err);
      }
    }

    if (audioContext.state !== 'running') {
      return false;
    }

    const now = audioContext.currentTime;

    crispChimeTone(
      audioContext,
      1175,
      now,
      0.24,
      0.62,
      [[2, 0.22], [3, 0.08]]
    );

    crispChimeTone(
      audioContext,
      1568,
      now + 0.20,
      0.34,
      0.66,
      [[2, 0.18]]
    );

    return true;
  }

  function getButton() {
    return document.querySelector('.dispatch-alert-toggle');
  }

  function updateButton() {
    const btn = getButton();
    if (!btn) return;

    if (!enabled) {
      btn.textContent = '🔕 開啟新單提示';
      return;
    }

    if (!isAudioReady()) {
      btn.textContent = pendingAlert
        ? '🔔 有新單｜點一下啟用聲音'
        : '🔔 點一下啟用聲音';
      return;
    }

    btn.textContent = '🔔 新單提示已開';
  }

  function makeButton() {
    if (getButton()) {
      updateButton();
      return;
    }

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dispatch-alert-toggle';

    btn.addEventListener('click', async () => {
      if (!enabled) {
        enabled = true;
        localStorage.setItem(ENABLED_KEY, '1');

        if (await unlockAudio()) {
          pendingAlert = false;
          await dingDong();
        }

        updateButton();
        return;
      }

      if (!isAudioReady()) {
        if (await unlockAudio()) {
          pendingAlert = false;
          await dingDong();
        }

        updateButton();
        return;
      }

      enabled = false;
      pendingAlert = false;
      localStorage.setItem(ENABLED_KEY, '0');
      updateButton();
    });

    document.body.appendChild(btn);
    updateButton();
  }

  function installAudioUnlockFallback() {
    const tryUnlock = async (event) => {
      const target = event.target;
      if (
        target
        && typeof target.closest === 'function'
        && target.closest('.dispatch-alert-toggle')
      ) {
        return;
      }

      if (!enabled || isAudioReady()) return;

      if (await unlockAudio()) {
        if (pendingAlert) {
          pendingAlert = false;
          await dingDong();
        }
        updateButton();
      }
    };

    window.addEventListener('pointerdown', tryUnlock, true);
    window.addEventListener('keydown', tryUnlock, true);

    document.addEventListener('visibilitychange', async () => {
      if (
        !document.hidden
        && enabled
        && audioContext
        && audioContext.state !== 'running'
      ) {
        try {
          await audioContext.resume();
        } catch (err) {
          console.warn('[dispatch-alert] foreground audio resume failed', err);
        }
        updateButton();
      }
    });
  }

  function normalizeKeys(keys) {
    return (keys || []).map(String).sort();
  }

  function parseDispatchShell(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    return doc.querySelector('.dispatch-shell');
  }

  async function fetchFreshDispatchShell() {
    const res = await fetch('/dispatch?t=' + Date.now(), {
      cache: 'no-store',
      credentials: 'same-origin'
    });

    if (!res.ok) {
      throw new Error('dispatch refresh failed: ' + res.status);
    }

    const html = await res.text();
    const nextShell = parseDispatchShell(html);
    const currentShell = document.querySelector('.dispatch-shell');

    if (!nextShell || !currentShell) {
      throw new Error('dispatch shell missing from refresh response');
    }

    currentShell.replaceWith(nextShell);
    return true;
  }

  async function refreshDispatch(options) {
    const playAlert = Boolean(options && options.playAlert);

    if (refreshPromise) {
      if (playAlert) {
        queuedAlertRefresh = true;
      }
      return refreshPromise;
    }

    refreshPromise = (async () => {
      try {
        await fetchFreshDispatchShell();

        if (playAlert) {
          const played = await dingDong();
          if (!played && enabled) {
            pendingAlert = true;
            updateButton();
          }
        }

        return true;
      } catch (err) {
        console.warn('[dispatch-alert] soft refresh failed', err);
        return false;
      }
    })();

    let result = false;

    try {
      result = await refreshPromise;
    } finally {
      refreshPromise = null;

      if (queuedAlertRefresh) {
        queuedAlertRefresh = false;
        setTimeout(() => {
          refreshDispatch({ playAlert: true });
        }, 0);
      }
    }

    return result;
  }

  async function refreshAfterNewOrder(attempt) {
    const retryAttempt = Number(attempt || 0);
    const ok = await refreshDispatch({ playAlert: true });

    if (!ok && retryAttempt < 3) {
      setTimeout(() => {
        refreshAfterNewOrder(retryAttempt + 1);
      }, 3000);
    }
  }

  async function primeKnownKeys() {
    try {
      const res = await fetch('/dispatch/state?t=' + Date.now(), {
        cache: 'no-store',
        credentials: 'same-origin'
      });

      if (!res.ok) return;

      const data = await res.json();
      if (data && data.ok) {
        knownKeys = normalizeKeys(data.keys || []);
      }
    } catch (err) {
      console.warn('[dispatch-alert] initial state failed', err);
    }
  }

  function connectDispatchEvents() {
    if (eventSource) {
      eventSource.close();
    }

    eventSource = new EventSource('/dispatch/events');

    eventSource.onmessage = async (event) => {
      let data;

      try {
        data = JSON.parse(event.data);
      } catch (err) {
        console.warn('[dispatch-alert] invalid SSE payload', err);
        return;
      }

      if (!data || !data.ok) return;

      const nextKeys = normalizeKeys(data.keys || []);

      if (knownKeys === null) {
        knownKeys = nextKeys;
        return;
      }

      const previousKeys = new Set(knownKeys);
      const hasNewOrder = nextKeys.some((key) => !previousKeys.has(key));

      knownKeys = nextKeys;

      if (hasNewOrder) {
        console.log('[dispatch-alert] new order received, refreshing');
        await refreshAfterNewOrder(0);
      }
    };

    eventSource.onopen = () => {
      console.log('[dispatch-alert] SSE connected');
    };

    eventSource.onerror = () => {
      console.warn('[dispatch-alert] SSE disconnected; browser will reconnect');
    };
  }

  function installDispatchFormSoftSubmit() {
    document.addEventListener('submit', async (event) => {
      const form = event.target;

      if (
        !(form instanceof HTMLFormElement)
        || !form.closest('.dispatch-shell')
        || !String(form.action || '').includes('/dispatch/orders/')
      ) {
        return;
      }

      event.preventDefault();

      try {
        const res = await fetch(form.action, {
          method: String(form.method || 'POST').toUpperCase(),
          body: new FormData(form),
          credentials: 'same-origin',
          cache: 'no-store'
        });

        if (!res.ok) {
          throw new Error('dispatch action failed: ' + res.status);
        }

        const html = await res.text();
        const nextShell = parseDispatchShell(html);
        const currentShell = document.querySelector('.dispatch-shell');

        if (!nextShell || !currentShell) {
          throw new Error('dispatch action response missing shell');
        }

        currentShell.replaceWith(nextShell);
      } catch (err) {
        console.warn('[dispatch-alert] soft action failed, falling back', err);
        form.submit();
      }
    });
  }

  async function init() {
    if (!isDispatchPage()) return;

    makeButton();
    installAudioUnlockFallback();
    installDispatchFormSoftSubmit();
    await primeKnownKeys();
    connectDispatchEvents();

    setInterval(() => {
      refreshDispatch({ playAlert: false });
    }, HOURLY_REFRESH_MS);

    console.log('[dispatch-alert] started v10 single-SSE crisp-chime');
  }

  window.addEventListener('beforeunload', () => {
    if (eventSource) {
      eventSource.close();
    }
  });

  if (document.readyState === 'complete') {
    init();
  } else {
    window.addEventListener('load', init, { once: true });
  }
})();
