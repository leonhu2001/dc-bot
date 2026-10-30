(() => {
    const root = document.querySelector('[data-market-push]');
    if (!root) return;

    const button = root.querySelector('[data-market-push-button]');
    const status = root.querySelector('[data-market-push-status]');
    const configUrl = root.dataset.configUrl || '';
    const subscribeUrl = root.dataset.subscribeUrl || '';
    const unsubscribeUrl = root.dataset.unsubscribeUrl || '';
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    let config = null;
    let currentSubscription = null;

    const setStatus = (message, kind = '') => {
        if (!status) return;
        status.textContent = message;
        status.dataset.kind = kind;
    };

    const setButton = ({ enabled = true, subscribed = false, busy = false } = {}) => {
        if (!button) return;
        button.disabled = !enabled || busy;
        button.dataset.subscribed = subscribed ? '1' : '0';
        button.textContent = busy
            ? '處理中…'
            : (subscribed ? '關閉價格推播' : '開啟價格推播');
    };

    const urlBase64ToUint8Array = (base64String) => {
        const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = window.atob(base64);
        return Uint8Array.from([...rawData].map((character) => character.charCodeAt(0)));
    };

    const readError = async (response, fallback) => {
        try {
            const payload = await response.json();
            return payload?.detail || fallback;
        } catch (_error) {
            return fallback;
        }
    };

    const postJson = async (url, payload) => fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrfToken,
        },
        body: JSON.stringify(payload),
    });

    const supportsPush = () => (
        'serviceWorker' in navigator
        && 'PushManager' in window
        && 'Notification' in window
    );

    const getExistingSubscription = async () => {
        const registration = await navigator.serviceWorker.getRegistration('/');
        if (!registration) return null;
        return registration.pushManager.getSubscription();
    };

    const refreshState = async () => {
        if (!supportsPush()) {
            setButton({ enabled: false });
            setStatus('這個瀏覽器目前不支援網站推播。', 'unavailable');
            return;
        }

        try {
            const response = await fetch(configUrl, {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            if (!response.ok) {
                throw new Error(await readError(response, '無法讀取推播設定。'));
            }
            config = await response.json();
        } catch (error) {
            setButton({ enabled: false });
            setStatus(error?.message || '無法讀取推播設定。', 'error');
            return;
        }

        if (!config?.enabled || !config?.public_key) {
            setButton({ enabled: false });
            setStatus('網站推播尚未完成伺服器設定；價格提醒仍會保留在通知中心。', 'unavailable');
            return;
        }

        try {
            currentSubscription = await getExistingSubscription();
        } catch (_error) {
            currentSubscription = null;
        }

        if (currentSubscription) {
            setButton({ enabled: true, subscribed: true });
            setStatus('這台裝置已開啟價格推播。', 'enabled');
            return;
        }

        setButton({ enabled: true, subscribed: false });
        if (Notification.permission === 'denied') {
            setStatus('瀏覽器已封鎖通知；請先到瀏覽器網站權限中重新允許。', 'denied');
        } else {
            setStatus('按下按鈕後才會向瀏覽器要求通知權限。', 'idle');
        }
    };

    const enablePush = async () => {
        if (!config?.enabled || !config?.public_key) return;
        if (Notification.permission === 'denied') {
            setStatus('瀏覽器已封鎖通知；請先到網站權限中重新允許。', 'denied');
            return;
        }

        setButton({ enabled: true, subscribed: false, busy: true });
        let subscription = null;
        try {
            const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
            await navigator.serviceWorker.ready;

            let permission = Notification.permission;
            if (permission === 'default') {
                permission = await Notification.requestPermission();
            }
            if (permission !== 'granted') {
                setStatus(
                    permission === 'denied'
                        ? '通知權限被拒絕；可在瀏覽器網站設定中重新開啟。'
                        : '沒有取得通知權限，因此尚未啟用推播。',
                    permission === 'denied' ? 'denied' : 'idle',
                );
                return;
            }

            subscription = await registration.pushManager.getSubscription();
            if (!subscription) {
                subscription = await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(config.public_key),
                });
            }

            const response = await postJson(subscribeUrl, {
                subscription: subscription.toJSON(),
            });
            if (!response.ok) {
                const message = await readError(response, '伺服器無法保存推播訂閱。');
                await subscription.unsubscribe().catch(() => false);
                subscription = null;
                throw new Error(message);
            }

            currentSubscription = subscription;
            setStatus('價格推播已開啟；提醒達標時會通知這台裝置。', 'enabled');
        } catch (error) {
            setStatus(error?.message || '開啟價格推播失敗。', 'error');
        } finally {
            setButton({ enabled: true, subscribed: Boolean(currentSubscription), busy: false });
        }
    };

    const disablePush = async () => {
        setButton({ enabled: true, subscribed: true, busy: true });
        try {
            const subscription = currentSubscription || await getExistingSubscription();
            if (!subscription) {
                currentSubscription = null;
                setStatus('這台裝置目前沒有價格推播訂閱。', 'idle');
                return;
            }

            const response = await postJson(unsubscribeUrl, {
                endpoint: subscription.endpoint,
            });
            if (!response.ok) {
                throw new Error(await readError(response, '伺服器無法關閉推播訂閱。'));
            }

            await subscription.unsubscribe();
            currentSubscription = null;
            setStatus('這台裝置的價格推播已關閉；網站內的價格提醒仍會保留。', 'idle');
        } catch (error) {
            setStatus(error?.message || '關閉價格推播失敗。', 'error');
        } finally {
            setButton({ enabled: true, subscribed: Boolean(currentSubscription), busy: false });
        }
    };

    button?.addEventListener('click', async () => {
        if (button.dataset.subscribed === '1') {
            await disablePush();
        } else {
            await enablePush();
        }
    });

    refreshState();
})();
