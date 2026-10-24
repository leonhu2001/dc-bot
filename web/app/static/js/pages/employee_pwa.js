(() => {
    const isStandalone = () => (
        window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true
    );

    if (isStandalone()) {
        document.documentElement.classList.add('employee-app-standalone');
        return;
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'employee-pwa-install';
    button.setAttribute('aria-label', '安裝魔丸員工 App');
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11 3h2v10.17l3.59-3.58L18 11l-6 6-6-6 1.41-1.41L11 13.17V3Zm-6 16h14v2H5v-2Z"/></svg><span>安裝員工 App</span>';
    document.body.appendChild(button);

    let deferredPrompt = null;
    const ua = navigator.userAgent || '';
    const isIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

    if (isIOS) {
        button.querySelector('span').textContent = '加入主畫面';
        button.classList.add('is-visible');
        button.addEventListener('click', () => {
            window.alert('在 Safari 點「分享」→「加入主畫面」→ 開啟「打開為網頁 App」→「加入」。');
        });
        return;
    }

    window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        deferredPrompt = event;
        button.classList.add('is-visible');
    });

    button.addEventListener('click', async () => {
        if (!deferredPrompt) {
            return;
        }
        button.disabled = true;
        try {
            await deferredPrompt.prompt();
            await deferredPrompt.userChoice;
        } finally {
            deferredPrompt = null;
            button.classList.remove('is-visible');
            button.disabled = false;
        }
    });

    window.addEventListener('appinstalled', () => {
        deferredPrompt = null;
        button.classList.remove('is-visible');
    });
})();
