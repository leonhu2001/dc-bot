(() => {
    const isStandalone = () => (
        window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true
    );

    if (isStandalone()) {
        document.documentElement.classList.add('mowan-app-standalone');
        return;
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'site-pwa-install';
    button.setAttribute('aria-label', '安裝魔丸娛樂 App');
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11 3h2v10.17l3.59-3.58L18 11l-6 6-6-6 1.41-1.41L11 13.17V3Zm-6 16h14v2H5v-2Z"/></svg><span>安裝魔丸 App</span>';
    document.body.appendChild(button);

    let deferredPrompt = null;
    const ua = navigator.userAgent || '';
    const isIOS = /iPad|iPhone|iPod/.test(ua)
        || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

    if (isIOS) {
        button.querySelector('span').textContent = '加入主畫面';
        button.classList.add('is-visible');
        button.addEventListener('click', () => {
            window.alert('在 Safari 點「分享」→「加入主畫面」→ 開啟「打開為網頁 App」→「加入」。');
        });
        return;
    }

    // Keep the install entry discoverable even before Chromium supplies a native prompt.
    button.classList.add('is-visible');

    window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        deferredPrompt = event;
    });

    button.addEventListener('click', async () => {
        if (!deferredPrompt) {
            window.alert('瀏覽器尚未提供一鍵安裝。請在 Chrome／Edge 右上角選單選「安裝魔丸娛樂」或使用網址列的安裝圖示。');
            return;
        }

        button.disabled = true;
        try {
            await deferredPrompt.prompt();
            const choice = await deferredPrompt.userChoice;
            deferredPrompt = null;
            if (choice?.outcome === 'accepted') {
                button.classList.remove('is-visible');
            }
        } finally {
            button.disabled = false;
        }
    });

    window.addEventListener('appinstalled', () => {
        deferredPrompt = null;
        button.classList.remove('is-visible');
    });
})();

// Keep dispatch desktop alerts alive while an eligible worker browses other
// Mowan pages. The dispatch lobby keeps its richer SSE + sound runtime; this
// lightweight companion intentionally skips /dispatch to prevent duplicate
// notifications and never requests Notification permission by itself.
(() => {
    const DESKTOP_NOTIFICATION_KEY = 'mw_dispatch_desktop_notification_enabled';
    const BACKGROUND_EVENTS_URL = '/dispatch/alerts/events';
    const BACKGROUND_CONFIG_URL = '/dispatch/alerts/config';

    if (window.location.pathname === '/dispatch') return;
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    if (localStorage.getItem(DESKTOP_NOTIFICATION_KEY) !== '1') return;

    let eventSource = null;
    let knownAlertKeys = null;
    let consecutiveErrors = 0;

    function normalizeKeys(keys) {
        return Array.from(new Set((keys || []).map(String))).sort();
    }

    function closeStream() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    }

    function showNotification(newKeys) {
        const keys = normalizeKeys(newKeys);
        if (!keys.length) return;

        const preview = keys.slice(0, 3).join('、');
        const extra = Math.max(0, keys.length - 3);
        const body = `新單：${preview}${extra ? `，另有 ${extra} 筆` : ''}`;

        try {
            const notification = new Notification('魔丸娛樂｜有新單', {
                body,
                tag: 'mowan-dispatch-new-order-background',
                renotify: true,
                icon: '/static/img/site-app-icon-512.png?v=20261025-4',
            });
            notification.onclick = () => {
                notification.close();
                window.focus();
                window.location.href = '/dispatch';
            };
        } catch (error) {
            console.warn('[dispatch-background-alert] notification failed', error);
        }
    }

    function applyPayload(payload) {
        const nextKeys = normalizeKeys(payload?.alert_keys);
        if (knownAlertKeys === null || payload?.initial) {
            knownAlertKeys = new Set(nextKeys);
            return;
        }

        const newKeys = nextKeys.filter((key) => !knownAlertKeys.has(key));
        knownAlertKeys = new Set(nextKeys);
        showNotification(newKeys);
    }

    function connect() {
        closeStream();
        eventSource = new EventSource(BACKGROUND_EVENTS_URL);

        eventSource.onopen = () => {
            consecutiveErrors = 0;
        };

        eventSource.onmessage = (event) => {
            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch (_error) {
                return;
            }
            if (!payload?.ok || payload?.heartbeat) return;
            applyPayload(payload);
        };

        eventSource.onerror = () => {
            consecutiveErrors += 1;
            if (consecutiveErrors >= 3) {
                closeStream();
            }
        };
    }

    async function start() {
        try {
            const response = await fetch(BACKGROUND_CONFIG_URL, {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            if (!response.ok) return;
            const payload = await response.json();
            if (!payload?.ok || !payload?.allowed) return;
            connect();
        } catch (_error) {
            // Site navigation must remain unaffected when the optional stream is unavailable.
        }
    }

    window.addEventListener('storage', (event) => {
        if (event.key !== DESKTOP_NOTIFICATION_KEY) return;
        if (event.newValue !== '1') closeStream();
    });

    window.addEventListener('pagehide', closeStream);
    start();
})();
