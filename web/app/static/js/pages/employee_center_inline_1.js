(function(){
    const money = value => `${new Intl.NumberFormat('zh-TW').format(Number(value || 0))}T`;
    const rowsHost = document.getElementById('salaryRows');
    const tabs = Array.from(document.querySelectorAll('.salary-tab'));
    const csTab = document.getElementById('salaryCsTab');
    let salaryItems = [];
    let activeFilter = 'all';

    function el(tag, className, text){
        const node = document.createElement(tag);
        if(className) node.className = className;
        if(text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function renderRows(){
        rowsHost.replaceChildren();
        const visible = activeFilter === 'all'
            ? salaryItems
            : salaryItems.filter(item => item.category_key === activeFilter);

        if(!visible.length){
            rowsHost.appendChild(el('div','salary-empty','這個分類目前沒有薪資紀錄。'));
            return;
        }

        visible.forEach(item => {
            const row = el('div','salary-row');
            row.appendChild(el('span','salary-date',item.closed_date || '未紀錄'));
            row.appendChild(el('span','salary-order',item.order_no || '未紀錄訂單'));

            const main = el('div','salary-main');
            main.appendChild(el('strong','',item.service_label || item.category_label || '薪資'));
            main.appendChild(el('span','salary-meta',item.category_label || '薪資'));
            row.appendChild(main);

            const status = el('span',`salary-status ${item.payout_status === 'paid' ? 'paid' : 'unpaid'}`,item.status_label || '待發放');
            row.appendChild(status);
            row.appendChild(el('span','salary-amount',money(item.amount)));

            const kind = el('span',`salary-kind ${item.category_key || ''}`,item.category_label || '薪資');
            if(window.matchMedia('(max-width: 720px)').matches){
                row.appendChild(kind);
            }

            rowsHost.appendChild(row);
        });
    }

    function activate(filter){
        activeFilter = filter;
        tabs.forEach(tab => tab.classList.toggle('active',tab.dataset.filter === filter));
        renderRows();
    }

    tabs.forEach(tab => tab.addEventListener('click',() => activate(tab.dataset.filter)));

    fetch('/employee/salary-data',{
        credentials:'same-origin',
        headers:{'Accept':'application/json'}
    })
    .then(async response => {
        const payload = await response.json();
        if(!response.ok || !payload.ok) throw new Error(payload.error || '薪資資料讀取失敗');
        return payload.data;
    })
    .then(data => {
        const summary = data.summary || {};
        const categories = data.categories || {};
        salaryItems = Array.isArray(data.items) ? data.items : [];

        document.getElementById('salaryPending').textContent = money(summary.pending);
        document.getElementById('salaryPendingSub').textContent = Number(summary.pending_count || 0) > 0
            ? `${summary.pending_count} 筆薪資尚未發放`
            : '目前沒有待發放薪資';

        document.getElementById('salaryMonthPaid').textContent = money(summary.current_month_paid);
        document.getElementById('salaryMonthPaidSub').textContent = `${summary.current_month_label || '本月'}已完成發放`;

        document.getElementById('salaryLifetime').textContent = money(summary.lifetime);
        document.getElementById('salaryLifetimeSub').textContent = `其中已發放 ${money(summary.paid_total)}・共 ${summary.all_count || 0} 筆`;

        document.querySelectorAll('[data-count]').forEach(node => {
            const key = node.dataset.count;
            node.textContent = Number((categories[key] || {}).count || 0);
        });

        if(csTab){
            csTab.hidden = Number((categories.customer_service || {}).count || 0) === 0;
        }

        renderRows();
    })
    .catch(error => {
        rowsHost.replaceChildren(el('div','salary-empty',error.message || '薪資資料讀取失敗，請重新整理後再試。'));
        document.getElementById('salaryPendingSub').textContent = '資料讀取失敗';
        document.getElementById('salaryMonthPaidSub').textContent = '資料讀取失敗';
        document.getElementById('salaryLifetimeSub').textContent = '資料讀取失敗';
    });
})();
