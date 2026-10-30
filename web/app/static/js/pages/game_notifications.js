(() => {
    const root = document.querySelector('[data-market-push]');
    if (!root) return;

    const button = root.querySelector('[data-market-push-button]');
    const testButton = root.querySelector('[data-market-push-test]');
    const status = root.querySelector('[data-market-push-status]');
    const configUrl = root.dataset.configUrl || '';
    const subscribeUrl = root.dataset.subscribeUrl || '';
    const testUrl = root.dataset.testUrl || '';
    const unsubscribeUrl = root.dataset.unsubscribeUrl || '';
    const canEnable = root.dataset.canEnable === '1';
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    let config = null;
    let currentSubscription = null;

    const setStatus = (message, kind = '') => {
        if (!status) return;
        status.textContent = message;
        status.dataset.kind = kind;
    };

    const setTestButton = ({ subscribed = false, busy = false } = {}) => {
        if (!testButton) return;
        testButton.hidden = !subscribed;
        testButton.disabled = !subscribed || busy;
        testButton.textContent = busy ? '傳送中…' : '傳送測試通知';
    };

    const setButton = ({ enabled = true, subscribed = false, busy = false } = {}) => {
        if (button) {
            button.disabled = !enabled || busy;
            button.dataset.subscribed = subscribed ? '1' : '0';
            button.textContent = busy
                ? '處理中…'
                : (subscribed ? '關閉價格推播' : '開啟價格推播');
        }
        setTestButton({ subscribed, busy });
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
            currentSubscription = await getExistingSubscription();
        } catch (_error) {
            currentSubscription = null;
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
            if (currentSubscription) {
                setButton({ enabled: true, subscribed: true });
                setStatus('目前無法讀取伺服器推播設定，但仍可測試或關閉這台裝置的既有訂閱。', 'error');
            } else {
                setButton({ enabled: false });
                setStatus(error?.message || '無法讀取推播設定。', 'error');
            }
            return;
        }

        if (currentSubscription) {
            setButton({ enabled: true, subscribed: true });
            setStatus('這台裝置已開啟價格推播，可用測試通知確認實際送達。', 'enabled');
            return;
        }

        if (!canEnable) {
            setButton({ enabled: false, subscribed: false });
            setStatus('先建立至少一個價格提醒，之後才能為這台裝置開啟推播。', 'idle');
            return;
        }

        if (!config?.enabled || !config?.public_key) {
            setButton({ enabled: false });
            setStatus('網站推播尚未完成伺服器設定；價格提醒仍會保留在通知中心。', 'unavailable');
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
        if (!canEnable || !config?.enabled || !config?.public_key) return;
        if (Notification.permission === 'denied') {
            setStatus('瀏覽器已封鎖通知；請先到網站權限中重新允許。', 'denied');
            return;
        }

        setButton({ enabled: true, subscribed: false, busy: true });
        let subscription = null;
        try {
            // Request permission immediately from the click handler before
            // awaiting Service Worker work; Safari/iOS ties the prompt to a
            // live user gesture more strictly than some desktop browsers.
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

            const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
            await navigator.serviceWorker.ready;

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
            setStatus('價格推播已開啟；你現在可以傳送測試通知確認這台裝置。', 'enabled');
        } catch (error) {
            setStatus(error?.message || '開啟價格推播失敗。', 'error');
        } finally {
            setButton({
                enabled: Boolean(currentSubscription) || canEnable,
                subscribed: Boolean(currentSubscription),
                busy: false,
            });
        }
    };

    const testPush = async () => {
        if (!testUrl) return;

        let subscription = currentSubscription;
        if (!subscription) {
            try {
                subscription = await getExistingSubscription();
            } catch (_error) {
                subscription = null;
            }
        }
        if (!subscription) {
            currentSubscription = null;
            setButton({ enabled: canEnable, subscribed: false });
            setStatus('這台裝置目前沒有可測試的推播訂閱。', 'idle');
            return;
        }

        currentSubscription = subscription;
        setButton({ enabled: true, subscribed: true, busy: true });
        setStatus('正在傳送測試通知到這台裝置…', 'idle');
        try {
            const response = await postJson(testUrl, {
                endpoint: subscription.endpoint,
            });
            if (!response.ok) {
                const message = await readError(response, '測試通知暫時無法送達。');
                if (response.status === 404 || response.status === 410) {
                    await subscription.unsubscribe().catch(() => false);
                    currentSubscription = null;
                }
                throw new Error(message);
            }

            setStatus('測試通知已送出；若系統通知權限正常，這台裝置應會立即看到通知。', 'enabled');
        } catch (error) {
            setStatus(error?.message || '測試通知暫時無法送達。', 'error');
        } finally {
            setButton({
                enabled: Boolean(currentSubscription) || canEnable,
                subscribed: Boolean(currentSubscription),
                busy: false,
            });
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
            setButton({
                enabled: Boolean(currentSubscription) || canEnable,
                subscribed: Boolean(currentSubscription),
                busy: false,
            });
        }
    };

    button?.addEventListener('click', async () => {
        if (button.dataset.subscribed === '1') {
            await disablePush();
        } else {
            await enablePush();
        }
    });

    testButton?.addEventListener('click', testPush);

    refreshState();
})();
