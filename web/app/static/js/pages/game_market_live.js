(() => {
    const shell = document.querySelector('.game-tool-shell');
    if (!shell) return;

    const updatedNode = document.querySelector('[data-market-updated-at]');
    const ageNode = document.querySelector('[data-market-age]');
    const liveNode = document.querySelector('[data-market-live-state]');
    const filterHost = document.querySelector('[data-market-category-filters]');
    const tierHost = document.querySelector('[data-market-tier-filters]');
    const resultMeta = document.querySelector('[data-market-result-meta]');
    const listHost = document.querySelector('.game-market-list');
    const sortSelect = document.querySelector('.game-market-search select[name="sort"]');
    const marketEventBar = document.querySelector('.game-market-livebar[aria-label="市場事件預測"]');
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

    const pageParams = new URLSearchParams(window.location.search);
    const requestedSort = String(pageParams.get('sort') || 'name').trim().toLowerCase();
    const smartSortEnabled = requestedSort === '' || requestedSort === 'name';
    const favorites = new Set();

    let activeCategory = '';
    let activeQuickFilter = 'all';
    let favoritesReady = false;
    let quickFilterHost = null;
    let refreshTimer = null;
    let lastUpdatedAt = updatedNode?.getAttribute('datetime') || '';

    rows.forEach((row, index) => {
        row.dataset.marketOriginalIndex = String(index);
    });

    function removeStandaloneAnomalyBar() {
        if (!marketEventBar) return;
        const label = String(marketEventBar.querySelector('strong')?.textContent || '').trim();
        if (label.includes('單品異常')) marketEventBar.remove();
    }

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

    function itemKeyForRow(row) {
        try {
            const url = new URL(row.getAttribute('href') || '', window.location.origin);
            const parts = url.pathname.split('/').filter(Boolean);
            return decodeURIComponent(parts[parts.length - 1] || '');
        } catch (_error) {
            return '';
        }
    }

    function signalState(row) {
        const labels = Array.from(row.querySelectorAll('.game-market-value-badge'))
            .map((node) => String(node.textContent || '').trim());
        const abnormalDown = labels.some((label) => label.includes('異常跌價'));
        const restock = labels.some((label) => label.includes('疑似補貨'));
        const abnormalUp = labels.some((label) => label.includes('異常拉升'));
        return {
            abnormalDown,
            restock,
            abnormalUp,
            hasSignal: abnormalDown || restock || abnormalUp,
        };
    }

    function favoriteState(row) {
        return row.dataset.marketFavorite === '1';
    }

    function visibleRows() {
        return rows.filter((row) => !row.hidden);
    }

    function rowMatchesQuickFilter(row) {
        const signals = signalState(row);
        if (activeQuickFilter === 'favorites') return favoriteState(row);
        if (activeQuickFilter === 'abnormal') return signals.abnormalDown || signals.abnormalUp;
        if (activeQuickFilter === 'restock') return signals.restock;
        return true;
    }

    function updateResultMeta() {
        if (!resultMeta) return;
        const count = visibleRows().length;
        const suffixes = [];
        if (activeCategory) suffixes.push(activeCategory);
        if (activeQuickFilter === 'favorites') suffixes.push('只看收藏');
        if (activeQuickFilter === 'abnormal') suffixes.push('只看異常');
        if (activeQuickFilter === 'restock') suffixes.push('只看疑似補貨');
        resultMeta.textContent = suffixes.length
            ? `顯示 ${count} 個品項 · ${suffixes.join(' · ')}`
            : `顯示 ${count} 個品項`;
    }

    function applyFilters() {
        rows.forEach((row) => {
            const rowCategory = (row.dataset.marketCategory || '').trim();
            const categoryMatches = !activeCategory || rowCategory === activeCategory;
            row.hidden = !(categoryMatches && rowMatchesQuickFilter(row));
        });

        if (filterHost) {
            filterHost.querySelectorAll('button[data-market-category]').forEach((button) => {
                const selected = (button.dataset.marketCategory || '') === activeCategory;
                button.classList.toggle('is-active', selected);
                button.setAttribute('aria-pressed', selected ? 'true' : 'false');
            });
        }

        if (quickFilterHost) {
            quickFilterHost.querySelectorAll('button[data-market-quick-filter]').forEach((button) => {
                const selected = (button.dataset.marketQuickFilter || '') === activeQuickFilter;
                button.classList.toggle('is-active', selected);
                button.setAttribute('aria-pressed', selected ? 'true' : 'false');
            });
        }

        updateResultMeta();
    }

    function applyCategoryFilter(category) {
        activeCategory = category || '';
        applyFilters();
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

    function installQuickFilters() {
        if (!filterHost || rows.length === 0) return;
        if (!quickFilterHost) {
            quickFilterHost = document.createElement('div');
            quickFilterHost.className = 'game-market-category-filters';
            quickFilterHost.dataset.marketQuickFilters = '';
            quickFilterHost.setAttribute('aria-label', '行情快速篩選');
            filterHost.insertAdjacentElement('afterend', quickFilterHost);
        }

        quickFilterHost.replaceChildren();
        const options = [['全部行情', 'all']];
        if (favoritesReady) options.push(['★ 只看收藏', 'favorites']);
        options.push(['⚠️ 只看異常', 'abnormal']);
        options.push(['📦 只看疑似補貨', 'restock']);

        options.forEach(([label, value]) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.marketQuickFilter = value;
            button.textContent = label;
            const selected = activeQuickFilter === value;
            button.classList.toggle('is-active', selected);
            button.setAttribute('aria-pressed', selected ? 'true' : 'false');
            button.addEventListener('click', () => {
                activeQuickFilter = value;
                applyFilters();
            });
            quickFilterHost.appendChild(button);
        });
    }

    function markFavorites() {
        rows.forEach((row) => {
            const itemKey = itemKeyForRow(row);
            const favorite = itemKey && favorites.has(itemKey);
            row.dataset.marketFavorite = favorite ? '1' : '0';

            const firstCell = row.firstElementChild;
            if (!firstCell) return;
            let badge = firstCell.querySelector('[data-market-favorite-badge]');
            if (favorite && !badge) {
                badge = document.createElement('span');
                badge.dataset.marketFavoriteBadge = '';
                badge.className = 'game-market-value-badge is-value-low';
                badge.textContent = '★ 收藏';
                firstCell.appendChild(badge);
            } else if (!favorite && badge) {
                badge.remove();
            }
        });
    }

    function smartSortRank(row) {
        const favorite = favoriteState(row);
        const signals = signalState(row);
        const group = favorite && signals.hasSignal
            ? 0
            : favorite
                ? 1
                : signals.hasSignal
                    ? 2
                    : 3;
        const signalRank = signals.abnormalDown
            ? 0
            : signals.restock
                ? 1
                : signals.abnormalUp
                    ? 2
                    : 3;
        const originalIndex = Number.parseInt(row.dataset.marketOriginalIndex || '0', 10) || 0;
        return [group, signalRank, originalIndex];
    }

    function applySmartSort() {
        if (!smartSortEnabled || !listHost || rows.length === 0) return;
        const sorted = [...rows].sort((left, right) => {
            const leftRank = smartSortRank(left);
            const rightRank = smartSortRank(right);
            for (let index = 0; index < leftRank.length; index += 1) {
                if (leftRank[index] !== rightRank[index]) return leftRank[index] - rightRank[index];
            }
            return 0;
        });
        sorted.forEach((row) => listHost.appendChild(row));
    }

    async function loadFavorites() {
        const notificationsPath = window.location.pathname.replace(/\/market\/?$/, '/notifications');
        if (notificationsPath === window.location.pathname) return;

        try {
            const response = await fetch(notificationsPath, {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: { Accept: 'text/html' },
            });
            if (!response.ok) return;
            if (response.redirected && new URL(response.url).origin !== window.location.origin) return;

            const html = await response.text();
            const documentCopy = new DOMParser().parseFromString(html, 'text/html');
            documentCopy.querySelectorAll('.game-notification-watch[href*="/market/items/"]').forEach((link) => {
                try {
                    const url = new URL(link.getAttribute('href') || '', window.location.origin);
                    const parts = url.pathname.split('/').filter(Boolean);
                    const itemKey = decodeURIComponent(parts[parts.length - 1] || '');
                    if (itemKey) favorites.add(itemKey);
                } catch (_error) {
                    // Ignore malformed watchlist links and keep the market usable.
                }
            });

            favoritesReady = true;
            markFavorites();
            applySmartSort();
            installQuickFilters();
            applyFilters();
        } catch (_error) {
            // Logged-out visitors and unavailable personalization simply skip favorites.
        }
    }

    async function installTierFilters() {
        if (!tierHost) return;

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
                    .filter((tier) => Number.isInteger(tier) && tier >= 4 && tier <= 10)
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

    if (sortSelect) {
        const smartOption = sortSelect.querySelector('option[value="name"]');
        if (smartOption) smartOption.textContent = '智慧排序';
    }

    removeStandaloneAnomalyBar();
    installCategoryFilters();
    installQuickFilters();
    applySmartSort();
    applyFilters();
    loadFavorites();
    installTierFilters();
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
