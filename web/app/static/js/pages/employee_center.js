(function(){
    const money = value => `${new Intl.NumberFormat('zh-TW').format(Number(value || 0))}T`;
    const rowsHost = document.getElementById('salaryRows');
    if(!rowsHost) return;

    // Mobile home is task-first: the dedicated salary tab owns the full ledger.
    // Avoid starting the expensive ledger request when this section is hidden.
    if(window.matchMedia('(max-width: 767px)').matches && document.querySelector('.employee-mobile-task-hub')){
        return;
    }

    const tabs = Array.from(document.querySelectorAll('.salary-tab'));
    const csTab = document.getElementById('salaryCsTab');
    const hero = document.querySelector('.employee-workspace-hero');
    const employeeId = String(hero?.dataset.employeeUserId || 'self').trim() || 'self';
    const cacheKey = `mw_employee_salary_v2:${employeeId}`;
    const CACHE_MAX_AGE = 10 * 60 * 1000;
    const REQUEST_TIMEOUT = 7000;
    const PAGE_SIZE = 12;
    const pager = document.getElementById('salaryPagination');
    const pageInfo = document.getElementById('salaryPageInfo');
    const pageNumbers = document.getElementById('salaryPageNumbers');
    const pagePrevious = document.getElementById('salaryPagePrevious');
    const pageNext = document.getElementById('salaryPageNext');
    let salaryItems = [];
    let activeFilter = 'all';
    let currentPage = 1;
    let requestSerial = 0;

    function el(tag, className, text){
        const node = document.createElement(tag);
        if(className) node.className = className;
        if(text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function renderPagination(count){
        const totalPages = Math.max(1, Math.ceil(count / PAGE_SIZE));
        currentPage = Math.min(Math.max(currentPage, 1), totalPages);
        if(!pager) return;

        pager.hidden = count <= PAGE_SIZE;
        if(pager.hidden) return;

        const first = (currentPage - 1) * PAGE_SIZE + 1;
        const last = Math.min(currentPage * PAGE_SIZE, count);
        if(pageInfo) pageInfo.textContent = `顯示第 ${first}–${last} 筆，共 ${count} 筆｜第 ${currentPage}／${totalPages} 頁`;
        if(pagePrevious) pagePrevious.disabled = currentPage === 1;
        if(pageNext) pageNext.disabled = currentPage >= totalPages;
        if(pageNumbers){
            pageNumbers.replaceChildren();
            const start = Math.max(1, Math.min(currentPage - 2, totalPages - 4));
            const end = Math.min(totalPages, start + 4);
            for(let page = start; page <= end; page++){
                const button = el('button', 'salary-page-number', page);
                button.type = 'button';
                button.setAttribute('aria-label', `第 ${page} 頁`);
                if(page === currentPage){
                    button.classList.add('active');
                    button.setAttribute('aria-current', 'page');
                }
                button.addEventListener('click', () => goToPage(page));
                pageNumbers.appendChild(button);
            }
        }
    }

    function goToPage(page){
        const filteredCount = activeFilter === 'all'
            ? salaryItems.length
            : salaryItems.filter(item => item.category_key === activeFilter).length;
        const totalPages = Math.max(1, Math.ceil(filteredCount / PAGE_SIZE));
        if(!Number.isInteger(page) || page < 1 || page > totalPages || page === currentPage) return;
        currentPage = page;
        renderRows();
        const list = document.querySelector('.salary-list');
        if(list) list.scrollIntoView({
            behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
            block: 'start',
        });
    }

    function renderRows(){
        rowsHost.replaceChildren();
        const visible = activeFilter === 'all'
            ? salaryItems
            : salaryItems.filter(item => item.category_key === activeFilter);
        renderPagination(visible.length);

        if(!visible.length){
            rowsHost.appendChild(el('div','salary-empty','這個分類目前沒有薪資紀錄。'));
            return;
        }

        visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE).forEach(item => {
            const row = el('div','salary-row');
            row.appendChild(el('span','salary-date',item.closed_date || '未紀錄'));
            row.appendChild(el('span','salary-order',item.order_no || '未紀錄訂單'));

            const main = el('div','salary-main');
            main.appendChild(el('strong','',item.service_label || item.category_label || '薪資'));
            main.appendChild(el('span','salary-meta',item.category_label || '薪資'));
            row.appendChild(main);

            const financialState = item.financial_state || (item.payout_status === 'paid' ? 'paid' : 'unpaid');
            const statusClass = financialState === 'paid' ? 'paid' : 'unpaid';
            const status = el('span',`salary-status ${statusClass}`,item.status_label || '待發放');
            if(financialState === 'locked') status.dataset.state = 'locked';
            row.appendChild(status);
            row.appendChild(el('span','salary-amount',money(item.amount)));

            const kind = el('span',`salary-kind ${item.category_key || ''}`,item.category_label || '薪資');
            if(window.matchMedia('(max-width: 767px)').matches){
                row.appendChild(kind);
            }

            rowsHost.appendChild(row);
        });
    }

    function activate(filter){
        activeFilter = filter;
        currentPage = 1;
        tabs.forEach(tab => tab.classList.toggle('active',tab.dataset.filter === filter));
        renderRows();
    }

    function applyData(data){
        const summary = data?.summary || {};
        const categories = data?.categories || {};
        salaryItems = Array.isArray(data?.items) ? data.items : [];

        const pending = document.getElementById('salaryPending');
        const pendingSub = document.getElementById('salaryPendingSub');
        const monthPaid = document.getElementById('salaryMonthPaid');
        const monthPaidSub = document.getElementById('salaryMonthPaidSub');
        const lifetime = document.getElementById('salaryLifetime');
        const lifetimeSub = document.getElementById('salaryLifetimeSub');

        if(pending) pending.textContent = money(summary.pending);
        const pendingCount = Number(summary.pending_count || 0);
        const lockedCount = Number(summary.locked_count || 0);
        const pendingParts = [pendingCount > 0
            ? `${pendingCount} 筆薪資待發放`
            : '目前沒有可發放待領薪資'];
        if(lockedCount > 0) pendingParts.push(`${lockedCount} 筆報單鎖定 ${money(summary.locked)}`);
        if(pendingSub) pendingSub.textContent = pendingParts.join('・');

        if(monthPaid) monthPaid.textContent = money(summary.current_month_paid);
        if(monthPaidSub) monthPaidSub.textContent = `${summary.current_month_label || '本月'}已完成發放`;
        if(lifetime) lifetime.textContent = money(summary.lifetime);
        if(lifetimeSub) lifetimeSub.textContent = `其中已發放 ${money(summary.paid_total)}・共 ${summary.all_count || 0} 筆`;

        document.querySelectorAll('[data-count]').forEach(node => {
            const key = node.dataset.count;
            node.textContent = Number((categories[key] || {}).count || 0);
        });

        if(csTab) csTab.hidden = Number((categories.customer_service || {}).count || 0) === 0;
        renderRows();
    }

    function readCache(){
        try{
            const cached = JSON.parse(sessionStorage.getItem(cacheKey) || 'null');
            if(!cached || !cached.data || !cached.savedAt) return null;
            if(Date.now() - Number(cached.savedAt) > CACHE_MAX_AGE) return null;
            return cached.data;
        }catch(_){
            return null;
        }
    }

    function writeCache(data){
        try{
            sessionStorage.setItem(cacheKey, JSON.stringify({savedAt:Date.now(), data}));
        }catch(_){}
    }

    function renderLoadError(message){
        const box = el('div','salary-empty employee-load-state');
        box.appendChild(el('span','employee-load-message',message || '薪資資料暫時無法讀取。'));
        const retry = el('button','employee-load-retry','重新讀取');
        retry.type = 'button';
        retry.addEventListener('click',() => loadSalary({showLoader:true}));
        box.appendChild(retry);
        rowsHost.replaceChildren(box);
    }

    async function loadSalary({showLoader = false} = {}){
        const serial = ++requestSerial;
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

        if(showLoader || !salaryItems.length){
            const loading = el('div','salary-loading employee-load-state','薪資資料讀取中…');
            loading.setAttribute('role','status');
            rowsHost.replaceChildren(loading);
        }

        try{
            const response = await fetch('/employee/salary-data',{
                credentials:'same-origin',
                cache:'no-store',
                headers:{'Accept':'application/json'},
                signal:controller.signal,
            });
            const payload = await response.json();
            if(!response.ok || !payload.ok) throw new Error(payload.error || '薪資資料讀取失敗');
            if(serial !== requestSerial) return;
            writeCache(payload.data || {});
            applyData(payload.data || {});
        }catch(error){
            if(serial !== requestSerial) return;
            if(salaryItems.length) return;
            const timedOut = error?.name === 'AbortError';
            renderLoadError(timedOut ? '薪資資料回應較慢，你可以先操作其他功能，再按重新讀取。' : (error?.message || '薪資資料讀取失敗。'));
            ['salaryPendingSub','salaryMonthPaidSub','salaryLifetimeSub'].forEach(id => {
                const node = document.getElementById(id);
                if(node) node.textContent = timedOut ? '稍後可重新讀取' : '資料讀取失敗';
            });
        }finally{
            window.clearTimeout(timer);
        }
    }

    tabs.forEach(tab => tab.addEventListener('click',() => activate(tab.dataset.filter)));
    if(pagePrevious) pagePrevious.addEventListener('click', () => goToPage(currentPage - 1));
    if(pageNext) pageNext.addEventListener('click', () => goToPage(currentPage + 1));

    const cached = readCache();
    if(cached){
        applyData(cached);
    }else{
        loadSalary({showLoader:true});
    }
})();