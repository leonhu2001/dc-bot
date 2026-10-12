(() => {
    let ruleDirty = false;
    let activeFilter = 'all';
    let searchText = '';

    const parsePage = (html) => new DOMParser().parseFromString(html, 'text/html');

    function selectedKey() {
        return document.querySelector('#order-rule-workspace')?.dataset.ruleKey || '';
    }

    function setLoading(value) {
        document.querySelector('#order-rule-workspace')?.classList.toggle('is-loading', value);
    }

    function setDirty(value) {
        ruleDirty = Boolean(value);
        document.querySelector('.rule-editor-panel')?.classList.toggle('is-dirty', ruleDirty);
        const state = document.querySelector('[data-rule-save-state]');
        if (state) state.textContent = ruleDirty ? '有尚未發布的修改' : '修改後先預覽，再正式發布';
    }

    function applySidebarFilter() {
        const links = [...document.querySelectorAll('[data-rule-link][data-rule-status]')];
        let visible = 0;
        for (const link of links) {
            const matchesStatus = activeFilter === 'all' || link.dataset.ruleStatus === activeFilter;
            const haystack = (link.dataset.ruleSearchText || '').toLowerCase();
            const matchesSearch = !searchText || haystack.includes(searchText);
            const show = matchesStatus && matchesSearch;
            link.hidden = !show;
            if (show) visible += 1;
        }
        const empty = document.querySelector('[data-rule-empty-filter]');
        if (empty) empty.hidden = visible !== 0;
    }

    function snapshotSidebarState() {
        return {
            scrollTop: document.querySelector('[data-rule-list-scroll]')?.scrollTop || 0,
            filter: activeFilter,
            search: searchText,
        };
    }

    function restoreSidebarState(state) {
        activeFilter = state?.filter || 'all';
        searchText = state?.search || '';
        const input = document.querySelector('[data-rule-search]');
        if (input) input.value = searchText;
        document.querySelectorAll('[data-rule-filter]').forEach((button) => {
            button.classList.toggle('is-active', button.dataset.ruleFilter === activeFilter);
        });
        applySidebarFilter();
        const scroll = document.querySelector('[data-rule-list-scroll]');
        if (scroll) scroll.scrollTop = state?.scrollTop || 0;
    }

    function replaceFromDocument(doc, { replaceSidebar = false } = {}) {
        const currentAlerts = document.querySelector('#order-rule-alerts');
        const nextAlerts = doc.querySelector('#order-rule-alerts');
        if (currentAlerts && nextAlerts) currentAlerts.replaceWith(nextAlerts);

        const currentWorkspace = document.querySelector('#order-rule-workspace');
        const nextWorkspace = doc.querySelector('#order-rule-workspace');
        if (currentWorkspace && nextWorkspace) currentWorkspace.replaceWith(nextWorkspace);

        if (replaceSidebar) {
            const state = snapshotSidebarState();
            const currentSidebar = document.querySelector('#order-rule-sidebar');
            const nextSidebar = doc.querySelector('#order-rule-sidebar');
            if (currentSidebar && nextSidebar) currentSidebar.replaceWith(nextSidebar);
            restoreSidebarState(state);
        } else {
            const key = selectedKey();
            document.querySelectorAll('[data-rule-link][data-rule-status]').forEach((link) => {
                link.classList.toggle('is-selected', link.dataset.ruleKey === key);
            });
        }
    }

    async function fetchPage(url, options = {}) {
        const response = await fetch(url, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'order-rules-fetch', ...(options.headers || {}) },
            ...options,
        });
        const html = await response.text();
        return { response, doc: parsePage(html) };
    }

    async function openRule(url, { push = true } = {}) {
        setLoading(true);
        try {
            const { response, doc } = await fetchPage(url);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            replaceFromDocument(doc, { replaceSidebar: false });
            setDirty(false);
            if (push) history.pushState({ orderRules: true }, '', url);
            window.scrollTo({ top: Math.min(window.scrollY, document.querySelector('#order-rule-workspace')?.offsetTop || window.scrollY), behavior: 'instant' });
        } catch (error) {
            console.error('[order-rules] product switch failed', error);
            window.location.href = url;
        } finally {
            setLoading(false);
        }
    }

    document.addEventListener('click', (event) => {
        const filter = event.target.closest('[data-rule-filter]');
        if (filter) {
            activeFilter = filter.dataset.ruleFilter || 'all';
            document.querySelectorAll('[data-rule-filter]').forEach((button) => button.classList.toggle('is-active', button === filter));
            applySidebarFilter();
            return;
        }

        const link = event.target.closest('a[data-rule-link]');
        if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();

        const targetKey = link.dataset.ruleKey || '';
        if (ruleDirty && targetKey !== selectedKey()) {
            if (!window.confirm('這個商品還有尚未發布的修改。確定切換商品並放棄這些修改嗎？')) return;
        }
        openRule(link.href, { push: targetKey !== selectedKey() });
    });

    document.addEventListener('input', (event) => {
        if (event.target.matches('[data-rule-search]')) {
            searchText = String(event.target.value || '').trim().toLowerCase();
            applySidebarFilter();
            return;
        }
        if (event.target.closest('[data-rule-edit-form]')) setDirty(true);
    });

    document.addEventListener('change', (event) => {
        if (event.target.closest('[data-rule-edit-form]')) setDirty(true);
    });

    document.addEventListener('submit', async (event) => {
        const form = event.target.closest('form[data-async-form]');
        if (!form) return;
        event.preventDefault();

        const kind = form.dataset.formKind || '';
        if (ruleDirty && ['status', 'rollback', 'reset'].includes(kind)) {
            if (!window.confirm('目前表單還有尚未發布的修改。繼續操作會放棄這些修改，確定嗎？')) return;
        }

        const confirmation = form.dataset.confirm;
        if (confirmation && !window.confirm(confirmation)) return;

        const submitter = event.submitter;
        if (submitter) submitter.disabled = true;
        setLoading(true);

        try {
            const { response, doc } = await fetchPage(form.action, {
                method: (form.method || 'post').toUpperCase(),
                body: new FormData(form),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            replaceFromDocument(doc, { replaceSidebar: true });
            setDirty(kind === 'preview');

            const key = selectedKey();
            const cleanUrl = key
                ? `/admin/order-rules?edit=${encodeURIComponent(key)}`
                : '/admin/order-rules';
            history.replaceState({ orderRules: true }, '', cleanUrl);

            if (kind === 'create') {
                form.reset();
                const details = form.closest('details');
                if (details) details.open = false;
            }
        } catch (error) {
            console.error('[order-rules] async action failed', error);
            form.submit();
        } finally {
            if (submitter) submitter.disabled = false;
            setLoading(false);
        }
    });

    window.addEventListener('beforeunload', (event) => {
        if (!ruleDirty) return;
        event.preventDefault();
        event.returnValue = '';
    });

    window.addEventListener('popstate', () => {
        if (ruleDirty && !window.confirm('目前商品有尚未發布的修改。確定離開嗎？')) {
            history.forward();
            return;
        }
        openRule(window.location.href, { push: false });
    });

    applySidebarFilter();
})();
