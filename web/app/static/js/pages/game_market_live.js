(() => {
    const shell = document.querySelector('.game-tool-shell');
    if (!shell) return;

    const updatedNode = document.querySelector('[data-market-updated-at]');
    const ageNode = document.querySelector('[data-market-age]');
    const liveNode = document.querySelector('[data-market-live-state]');
    const filterHost = document.querySelector('[data-market-category-filters]');
    const tierHost = document.querySelector('[data-market-tier-filters]');
    const resultMeta = document.querySelector('[data-market-result-meta]');
    const listPanel = document.querySelector('.game-market-list-panel');
    const rowContainer = document.querySelector('.game-market-list');
    const sortSelect = document.querySelector('.game-market-search select[name="sort"]');
    const marketEventBar = document.querySelector('.game-market-livebar[aria-label="市場事件預測"]');
    const rows = Array.from(document.querySelectorAll('[data-market-row]'));
    const userLoggedIn = listPanel?.dataset.marketUser === '1';
    const csrfToken = String(listPanel?.dataset.marketCsrf || '');

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

    let activeCategory = '';
    let activeQuickFilter = 'all';
    let quickFilterHost = null;
    let refreshTimer = null;
    let lastUpdatedAt = updatedNode?.getAttribute('datetime') || '';

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

        if (updatedNode) updatedNode.textContent = formatter.format(updatedAt) + '（台灣時間）';
        if (!ageNode) return;

        const ageMinutes = Math.max(0, Math.floor((Date.now() - updatedAt.getTime()) / 60000));
        if (ageMinutes < 1) ageNode.textContent = '剛剛更新';
        else if (ageMinutes < 60) ageNode.textContent = `${ageMinutes} 分鐘前更新`;
        else ageNode.textContent = `${Math.floor(ageMinutes / 60)} 小時前更新`;
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
        return row.dataset.marketWatched === '1';
    }

    function predictionState(row) {
        return Boolean(String(row.dataset.marketRestockAt || '').trim());
    }

    function visibleRows() {
        return rows.filter((row) => !row.hidden);
    }

    function rowMatchesQuickFilter(row) {
        const signals = signalState(row);
        if (activeQuickFilter === 'favorites') return favoriteState(row);
        if (activeQuickFilter === 'prediction') return predictionState(row);
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
        if (activeQuickFilter === 'prediction') suffixes.push('有補貨預測');
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

    function applySmartPinning() {
        if (!rowContainer) return;
        const sortKey = String(pageParams.get('sort') || 'name');
        if (sortKey !== 'name') return;

        const priority = (row) => {
            const signals = signalState(row);
            const watched = favoriteState(row);
            let group = 3;
            if (watched && signals.hasSignal) group = 0;
            else if (watched) group = 1;
            else if (signals.hasSignal) group = 2;

            let signal = 3;
            if (signals.abnormalDown) signal = 0;
            else if (signals.restock) signal = 1;
            else if (signals.abnormalUp) signal = 2;
            return [group, signal];
        };

        const ordered = [...rows].sort((left, right) => {
            const [leftGroup, leftSignal] = priority(left);
            const [rightGroup, rightSignal] = priority(right);
            return leftGroup - rightGroup || leftSignal - rightSignal;
        });
        ordered.forEach((row) => rowContainer.appendChild(row));
    }

    function applyClientSort() {
        if (!rowContainer || pageParams.get('sort') !== 'restock_asc') return;

        const ordered = [...rows].sort((left, right) => {
            const leftAt = Date.parse(left.dataset.marketRestockAt || '');
            const rightAt = Date.parse(right.dataset.marketRestockAt || '');
            const leftMissing = Number.isNaN(leftAt);
            const rightMissing = Number.isNaN(rightAt);

            if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
            if (!leftMissing && leftAt !== rightAt) return leftAt - rightAt;

            const leftConfidence = Number.parseInt(left.dataset.marketRestockConfidence || '0', 10) || 0;
            const rightConfidence = Number.parseInt(right.dataset.marketRestockConfidence || '0', 10) || 0;
            return rightConfidence - leftConfidence;
        });

        ordered.forEach((row) => rowContainer.appendChild(row));
    }

    function installRowNavigation() {
        rows.forEach((row) => {
            const href = String(row.dataset.marketHref || '');
            if (!href) return;
            row.addEventListener('click', (event) => {
                if (event.target.closest('a, button, input, select, textarea, form')) return;
                window.location.href = href;
            });
            row.addEventListener('keydown', (event) => {
                if (event.target !== row || event.key !== 'Enter') return;
                event.preventDefault();
                window.location.href = href;
            });
        });
    }

    function updateWatchButton(row, watched) {
        const button = row.querySelector('[data-market-watch-toggle]');
        if (!button) return;
        button.classList.toggle('is-watched', watched);
        button.setAttribute('aria-pressed', watched ? 'true' : 'false');
        button.title = watched ? '取消收藏' : '收藏這顆子彈';
        button.textContent = watched ? '★ 收藏' : '☆ 收藏';
    }

    function installWatchToggles() {
        if (!userLoggedIn || !csrfToken) return;
        rows.forEach((row) => {
            const button = row.querySelector('[data-market-watch-toggle]');
            const watchUrl = String(row.dataset.marketWatchUrl || '');
            if (!button || !watchUrl) return;

            button.addEventListener('click', async (event) => {
                event.preventDefault();
                event.stopPropagation();
                if (button.disabled) return;

                const nextWatched = !favoriteState(row);
                button.disabled = true;
                try {
                    const body = new URLSearchParams();
                    body.set('csrf_token', csrfToken);
                    body.set('watched', nextWatched ? '1' : '0');
                    body.set('return_to', window.location.pathname + window.location.search);
                    const response = await fetch(watchUrl, {
                        method: 'POST',
                        credentials: 'same-origin',
                        cache: 'no-store',
                        body,
                    });
                    if (!response.ok) throw new Error(`watch update failed: ${response.status}`);

                    row.dataset.marketWatched = nextWatched ? '1' : '0';
                    updateWatchButton(row, nextWatched);
                    applySmartPinning();
                    applyFilters();
                } catch (_error) {
                    button.title = '收藏更新失敗，請重新整理後再試';
                } finally {
                    button.disabled = false;
                }
            });
        });
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
        categories.forEach((category) => filterHost.appendChild(makeButton(category, category)));
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
        if (userLoggedIn) options.push(['★ 只看收藏', 'favorites']);
        options.push(['⏱ 有補貨預測', 'prediction']);
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
                    .filter((tier) => Number.isInteger(tier) && tier >= 4 && tier <= 5)
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
            // Keep the server-rendered 4/5 fallback filters when discovery is unavailable.
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
        if (pageParams.get('sort') === 'restock_asc') sortSelect.value = 'restock_asc';
    }

    removeStandaloneAnomalyBar();
    applySmartPinning();
    applyClientSort();
    installRowNavigation();
    installWatchToggles();
    installCategoryFilters();
    installQuickFilters();
    applyFilters();
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