(() => {
    const shell = document.querySelector('.game-tool-shell');
    if (!shell) return;

    const updatedNode = document.querySelector('[data-market-updated-at]');
    const ageNode = document.querySelector('[data-market-age]');
    const liveNode = document.querySelector('[data-market-live-state]');
    const filterHost = document.querySelector('[data-market-category-filters]');
    const tierHost = document.querySelector('[data-market-tier-filters]');
    const resultMeta = document.querySelector('[data-market-result-meta]');
    const rows = Array.from(document.querySelectorAll('[data-market-row]'));

    const formatter = new Intl.DateTimeFormat('zh-TW', {
        timeZone: 'Asia/Taipei',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    });

    let activeCategory = '';
    let refreshTimer = null;
    let lastUpdatedAt = updatedNode?.getAttribute('datetime') || '';

    function parseUpdatedAt() {
        if (!lastUpdatedAt) return null;
        const value = new Date(lastUpdatedAt);
        return Number.isNaN(value.getTime()) ? null : value;
    }

    function updateFreshness() {
        const updatedAt = parseUpdatedAt();
        if (!updatedAt) return;

        if (updatedNode) {
            updatedNode.textContent = formatter.format(updatedAt) + '（台灣時間）';
        }

        if (!ageNode) return;
        const ageMinutes = Math.max(0, Math.floor((Date.now() - updatedAt.getTime()) / 60000));
        if (ageMinutes < 1) {
            ageNode.textContent = '剛剛更新';
        } else if (ageMinutes < 60) {
            ageNode.textContent = `${ageMinutes} 分鐘前更新`;
        } else {
            const hours = Math.floor(ageMinutes / 60);
            ageNode.textContent = `${hours} 小時前更新`;
        }
    }

    function visibleRows() {
        return rows.filter((row) => !row.hidden);
    }

    function applyCategoryFilter(category) {
        activeCategory = category || '';
        rows.forEach((row) => {
            const rowCategory = (row.dataset.marketCategory || '').trim();
            row.hidden = Boolean(activeCategory && rowCategory !== activeCategory);
        });

        if (filterHost) {
            filterHost.querySelectorAll('button[data-market-category]').forEach((button) => {
                const selected = (button.dataset.marketCategory || '') === activeCategory;
                button.classList.toggle('is-active', selected);
                button.setAttribute('aria-pressed', selected ? 'true' : 'false');
            });
        }

        if (resultMeta) {
            const count = visibleRows().length;
            resultMeta.textContent = activeCategory
                ? `顯示 ${count} 個品項 · ${activeCategory}`
                : `顯示 ${count} 個品項`;
        }
    }

    function installCategoryFilters() {
        if (!filterHost || rows.length === 0) return;
        const categories = Array.from(new Set(
            rows
                .map((row) => (row.dataset.marketCategory || '').trim())
                .filter(Boolean)
        )).sort((a, b) => a.localeCompare(b, 'zh-Hant'));

        if (categories.length === 0) return;

        filterHost.hidden = false;
        filterHost.replaceChildren();

        const makeButton = (label, value) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.marketCategory = value;
            button.textContent = label;
            button.setAttribute('aria-pressed', value === activeCategory ? 'true' : 'false');
            if (value === activeCategory) button.classList.add('is-active');
            button.addEventListener('click', () => applyCategoryFilter(value));
            return button;
        };

        filterHost.appendChild(makeButton('全部口徑', ''));
        categories.forEach((category) => {
            filterHost.appendChild(makeButton(category, category));
        });
    }

    async function installTierFilters() {
        if (!tierHost) return;

        const pageParams = new URLSearchParams(window.location.search);
        const activeTier = String(pageParams.get('tier') || '').trim();
        const discoveryParams = new URLSearchParams(pageParams);
        discoveryParams.delete('tier');
        const query = discoveryParams.toString();
        const apiUrl = `${window.location.pathname}/api/items${query ? `?${query}` : ''}`;

        try {
            const response = await fetch(apiUrl, {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            if (!response.ok) return;
            const payload = await response.json();
            const items = Array.isArray(payload?.items) ? payload.items : [];
            const tiers = Array.from(new Set(
                items
                    .map((item) => Number.parseInt(String(item?.tier ?? ''), 10))
                    .filter((tier) => Number.isInteger(tier) && tier >= 1 && tier <= 10)
            )).sort((left, right) => left - right);
            if (!tiers.length) return;

            const makeLink = (label, tier) => {
                const params = new URLSearchParams(pageParams);
                if (tier === '') params.delete('tier');
                else params.set('tier', String(tier));
                const encoded = params.toString();
                const link = document.createElement('a');
                link.href = `${window.location.pathname}${encoded ? `?${encoded}` : ''}`;
                link.textContent = label;
                const selected = String(tier) === activeTier;
                link.classList.toggle('is-active', selected);
                if (selected) link.setAttribute('aria-current', 'page');
                return link;
            };

            tierHost.replaceChildren(makeLink('全部', ''));
            tiers.forEach((tier) => tierHost.appendChild(makeLink(`${tier}級`, tier)));
        } catch (_error) {
            // Keep the server-rendered fallback filters when discovery is unavailable.
        }
    }

    async function checkForNewSnapshot() {
        if (document.hidden || !lastUpdatedAt) return;
        const apiUrl = `${window.location.pathname}/api/items${window.location.search}`;

        try {
            if (liveNode) liveNode.textContent = '檢查最新行情…';
            const response = await fetch(apiUrl, {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            if (!response.ok) throw new Error(`market refresh failed: ${response.status}`);
            const payload = await response.json();
            const nextUpdatedAt = String(payload?.updated_at || '');
            if (nextUpdatedAt && nextUpdatedAt !== lastUpdatedAt) {
                if (liveNode) liveNode.textContent = '偵測到新行情，更新畫面…';
                window.location.reload();
                return;
            }
            if (liveNode) liveNode.textContent = '自動更新中';
        } catch (_error) {
            if (liveNode) liveNode.textContent = '自動更新暫時離線';
        }
    }

    function scheduleRefresh() {
        if (refreshTimer) window.clearInterval(refreshTimer);
        refreshTimer = window.setInterval(checkForNewSnapshot, 60_000);
    }

    installCategoryFilters();
    installTierFilters();
    applyCategoryFilter('');
    updateFreshness();
    window.setInterval(updateFreshness, 30_000);
    scheduleRefresh();

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            updateFreshness();
            checkForNewSnapshot();
        }
    });
})();
