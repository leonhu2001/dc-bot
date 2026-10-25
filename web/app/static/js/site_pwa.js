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
