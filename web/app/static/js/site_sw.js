self.addEventListener('install', () => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
    let payload = {};
    if (event.data) {
        try {
            payload = event.data.json();
        } catch (_error) {
            payload = { body: event.data.text() };
        }
    }

    const title = payload.title || '魔丸娛樂價格提醒';
    const options = {
        body: payload.body || '你關注的三角洲行情已達到提醒條件。',
        icon: '/static/img/site-app-icon-512.png?v=20261025-4',
        badge: '/static/img/favicon-64.png?v=20261025-5',
        tag: payload.tag || 'mowan-market-alert',
        renotify: false,
        data: {
            url: payload.url || '/games/delta-force/notifications',
            market: payload.data || null,
        },
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const target = new URL(event.notification.data?.url || '/', self.location.origin).href;

    event.waitUntil((async () => {
        const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const client of windows) {
            if (client.url === target && 'focus' in client) {
                return client.focus();
            }
        }
        if (self.clients.openWindow) {
            return self.clients.openWindow(target);
        }
        return undefined;
    })());
});
