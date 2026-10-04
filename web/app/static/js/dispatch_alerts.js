(function () {
  if (window.__mwDispatchAlertsStarted) {
    return;
  }
  window.__mwDispatchAlertsStarted = true;

  const HOURLY_REFRESH_MS = 60 * 60 * 1000;
  const ENABLED_KEY = 'mw_dispatch_alert_enabled';
  const DESKTOP_NOTIFICATION_KEY = 'mw_dispatch_desktop_notification_enabled';
  const ORIGINAL_TITLE = document.title;

  let enabled = localStorage.getItem(ENABLED_KEY) === '1';
  let desktopNotificationsEnabled =
    localStorage.getItem(DESKTOP_NOTIFICATION_KEY) === '1';
  let audioContext = null;
  let pendingAlert = false;
  let knownKeys = null;
  let knownSignature = null;
  let eventSource = null;
  let refreshPromise = null;
  let queuedAlertRefresh = false;
  let queuedNewOrderKeys = [];
  let connectionState = 'reconnecting';
  let lastSyncAt = null;
  let backgroundAlertPending = false;
  let onlineCompanionCount = null;
  let onlineSupportCount = null;

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

    updateSoundButton();
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

  function getSoundButton() {
    return document.querySelector('.dispatch-alert-toggle');
  }

  function updateSoundButton() {
    const btn = getSoundButton();
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

  function makeSoundButton() {
    if (getSoundButton()) {
      updateSoundButton();
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

        updateSoundButton();
        return;
      }

      if (!isAudioReady()) {
        if (await unlockAudio()) {
          pendingAlert = false;
          await dingDong();
        }

        updateSoundButton();
        return;
      }

      enabled = false;
      pendingAlert = false;
      localStorage.setItem(ENABLED_KEY, '0');
      updateSoundButton();
    });

    document.body.appendChild(btn);
    updateSoundButton();
  }

  function formatSyncTime(value) {
    if (!(value instanceof Date)) {
      return '--';
    }

    return new Intl.DateTimeFormat('zh-TW', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).format(value);
  }

  function updatePresenceIndicators() {
    if (onlineCompanionCount !== null) {
      document.querySelectorAll('[data-dispatch-online-companions]').forEach((node) => {
        node.textContent = '🟢 在線陪玩 ' + onlineCompanionCount + ' 人';
      });
    }

    if (onlineSupportCount !== null) {
      document.querySelectorAll('[data-dispatch-online-support]').forEach((node) => {
        node.textContent = '🟢 在線客服 ' + onlineSupportCount + ' 人';
      });
    }
  }

  function applyPresenceFromPayload(data) {
    if (!data) return;

    if (Number.isFinite(Number(data.online_companion_count))) {
      onlineCompanionCount = Number(data.online_companion_count);
    }

    if (Number.isFinite(Number(data.online_support_count))) {
      onlineSupportCount = Number(data.online_support_count);
    }

    updatePresenceIndicators();
  }

  function updateConnectionIndicators() {
    document.querySelectorAll('[data-dispatch-realtime-status]').forEach((node) => {
      node.dataset.state = connectionState;

      if (connectionState === 'online') {
        node.textContent = '🟢 即時連線正常';
      } else if (connectionState === 'offline') {
        node.textContent = '🔴 即時連線中斷';
      } else {
        node.textContent = '🟡 正在重新連線…';
      }
    });

    document.querySelectorAll('[data-dispatch-last-sync]').forEach((node) => {
      node.textContent = '最後同步 ' + formatSyncTime(lastSyncAt);
    });
  }

  function updateDesktopNotificationButton() {
    document.querySelectorAll('[data-dispatch-notification-toggle]').forEach((btn) => {
      if (!('Notification' in window)) {
        btn.dataset.state = 'blocked';
        btn.textContent = '🖥️ 此瀏覽器不支援桌面通知';
        btn.disabled = true;
        return;
      }

      btn.disabled = false;

      if (Notification.permission === 'denied') {
        btn.dataset.state = 'blocked';
        btn.textContent = '🖥️ 桌面通知已被瀏覽器封鎖';
        return;
      }

      if (
        desktopNotificationsEnabled
        && Notification.permission === 'granted'
      ) {
        btn.dataset.state = 'online';
        btn.textContent = '🖥️ 桌面通知已開';
        return;
      }

      btn.dataset.state = '';
      btn.textContent = '🖥️ 開啟桌面通知';
    });
  }

  async function toggleDesktopNotifications() {
    if (!('Notification' in window)) {
      updateDesktopNotificationButton();
      return;
    }

    if (
      desktopNotificationsEnabled
      && Notification.permission === 'granted'
    ) {
      desktopNotificationsEnabled = false;
      localStorage.setItem(DESKTOP_NOTIFICATION_KEY, '0');
      updateDesktopNotificationButton();
      return;
    }

    if (Notification.permission === 'denied') {
      updateDesktopNotificationButton();
      return;
    }

    let permission = Notification.permission;

    if (permission !== 'granted') {
      try {
        permission = await Notification.requestPermission();
      } catch (err) {
        console.warn('[dispatch-alert] notification permission failed', err);
      }
    }

    desktopNotificationsEnabled = permission === 'granted';
    localStorage.setItem(
      DESKTOP_NOTIFICATION_KEY,
      desktopNotificationsEnabled ? '1' : '0'
    );
    updateDesktopNotificationButton();
  }

  function renderRuntimeControls() {
    updateSoundButton();
    updateConnectionIndicators();
    updateDesktopNotificationButton();
    updatePresenceIndicators();
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
        updateSoundButton();
      }
    };

    window.addEventListener('pointerdown', tryUnlock, true);
    window.addEventListener('keydown', tryUnlock, true);

    document.addEventListener('visibilitychange', async () => {
      if (!document.hidden) {
        if (backgroundAlertPending) {
          backgroundAlertPending = false;
          document.title = ORIGINAL_TITLE;
        }

        if (
          enabled
          && audioContext
          && audioContext.state !== 'running'
        ) {
          try {
            await audioContext.resume();
          } catch (err) {
            console.warn('[dispatch-alert] foreground audio resume failed', err);
          }
        }

        updateSoundButton();
      }
    });
  }

  function installDesktopNotificationControl() {
    document.addEventListener('click', async (event) => {
      const target = event.target;
      if (!target || typeof target.closest !== 'function') return;

      const button = target.closest('[data-dispatch-notification-toggle]');
      if (!button) return;

      event.preventDefault();
      await toggleDesktopNotifications();
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
    lastSyncAt = new Date();
    renderRuntimeControls();
    return true;
  }

  function showDesktopNotification(newOrderKeys) {
    if (
      !desktopNotificationsEnabled
      || !('Notification' in window)
      || Notification.permission !== 'granted'
    ) {
      return;
    }

    const keys = normalizeKeys(newOrderKeys);
    const preview = keys.slice(0, 3).join('、');
    const extra = Math.max(0, keys.length - 3);
    const body = preview
      ? ('新單：' + preview + (extra ? ('，另有 ' + extra + ' 筆') : ''))
      : '接單大廳有新任務。';

    try {
      const notification = new Notification('魔丸娛樂｜有新單', {
        body,
        tag: 'mowan-dispatch-new-order',
        renotify: true
      });

      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    } catch (err) {
      console.warn('[dispatch-alert] desktop notification failed', err);
    }
  }

  function markBackgroundNewOrder(newOrderKeys) {
    if (!document.hidden) return;

    backgroundAlertPending = true;
    document.title = '🔔 有新單｜接單大廳';
    showDesktopNotification(newOrderKeys);
  }

  async function refreshDispatch(options) {
    const playAlert = Boolean(options && options.playAlert);
    const newOrderKeys = normalizeKeys(
      options && options.newOrderKeys
        ? options.newOrderKeys
        : []
    );

    if (refreshPromise) {
      if (playAlert) {
        queuedAlertRefresh = true;
        queuedNewOrderKeys = normalizeKeys([
          ...queuedNewOrderKeys,
          ...newOrderKeys
        ]);
      }
      return refreshPromise;
    }

    refreshPromise = (async () => {
      try {
        await fetchFreshDispatchShell();

        if (playAlert) {
          markBackgroundNewOrder(newOrderKeys);

          const played = await dingDong();
          if (!played && enabled) {
            pendingAlert = true;
            updateSoundButton();
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
        const queuedKeys = queuedNewOrderKeys;
        queuedAlertRefresh = false;
        queuedNewOrderKeys = [];

        setTimeout(() => {
          refreshDispatch({
            playAlert: true,
            newOrderKeys: queuedKeys
          });
        }, 0);
      }
    }

    return result;
  }

  async function refreshAfterNewOrder(attempt, newOrderKeys) {
    const retryAttempt = Number(attempt || 0);
    const ok = await refreshDispatch({
      playAlert: true,
      newOrderKeys
    });

    if (!ok && retryAttempt < 3) {
      setTimeout(() => {
        refreshAfterNewOrder(retryAttempt + 1, newOrderKeys);
      }, 3000);
    }
  }

  async function primeKnownState() {
    try {
      const res = await fetch('/dispatch/state?t=' + Date.now(), {
        cache: 'no-store',
        credentials: 'same-origin'
      });

      if (!res.ok) return;

      const data = await res.json();
      if (data && data.ok) {
        knownKeys = normalizeKeys(data.keys || []);
        knownSignature = String(data.signature || '');
        lastSyncAt = new Date();
        applyPresenceFromPayload(data);
        updateConnectionIndicators();
      }
    } catch (err) {
      console.warn('[dispatch-alert] initial state failed', err);
    }
  }

  function connectDispatchEvents() {
    if (eventSource) {
      eventSource.close();
    }

    connectionState = 'reconnecting';
    updateConnectionIndicators();

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
      const nextSignature = String(data.signature || '');
      lastSyncAt = new Date();
      connectionState = 'online';
      applyPresenceFromPayload(data);
      updateConnectionIndicators();

      if (knownKeys === null) {
        knownKeys = nextKeys;
        knownSignature = nextSignature;
        return;
      }

      const previousKeys = new Set(knownKeys);
      const newOrderKeys = nextKeys.filter((key) => !previousKeys.has(key));
      const hasNewOrder = newOrderKeys.length > 0;
      const hasStateChange =
        knownSignature !== null
        && nextSignature !== knownSignature;

      knownKeys = nextKeys;
      knownSignature = nextSignature;

      if (!hasStateChange) {
        return;
      }

      if (hasNewOrder) {
        console.log('[dispatch-alert] new order received, refreshing');
        await refreshAfterNewOrder(0, newOrderKeys);
      } else {
        console.log('[dispatch-alert] order state changed, refreshing silently');
        await refreshDispatch({ playAlert: false });
      }
    };

    eventSource.onopen = () => {
      connectionState = 'online';
      lastSyncAt = new Date();
      updateConnectionIndicators();
      console.log('[dispatch-alert] SSE connected');
    };

    eventSource.onerror = () => {
      connectionState = 'reconnecting';
      updateConnectionIndicators();
      console.warn('[dispatch-alert] SSE disconnected; browser will reconnect');
    };
  }

  function setFormBusy(form, busy) {
    const button = form.querySelector('button[type="submit"]');
    if (!button) return;

    if (busy) {
      if (!button.dataset.idleLabel) {
        button.dataset.idleLabel = button.textContent.trim();
      }
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.textContent =
        button.dataset.busyLabel
        || '處理中…';
      return;
    }

    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.textContent =
      button.dataset.idleLabel
      || button.textContent;
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

      if (form.dataset.dispatchSubmitting === '1') {
        return;
      }

      form.dataset.dispatchSubmitting = '1';
      setFormBusy(form, true);

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
        lastSyncAt = new Date();
        renderRuntimeControls();
      } catch (err) {
        console.warn('[dispatch-alert] soft action failed, falling back', err);
        form.dataset.dispatchSubmitting = '0';
        setFormBusy(form, false);
        HTMLFormElement.prototype.submit.call(form);
      }
    });
  }

  async function init() {
    if (!isDispatchPage()) return;

    makeSoundButton();
    installAudioUnlockFallback();
    installDesktopNotificationControl();
    installDispatchFormSoftSubmit();
    renderRuntimeControls();
    await primeKnownState();
    connectDispatchEvents();

    setInterval(() => {
      refreshDispatch({ playAlert: false });
    }, HOURLY_REFRESH_MS);

    console.log('[dispatch-alert] started v11 operations-upgrade');
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
