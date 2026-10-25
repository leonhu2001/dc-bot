(() => {
  const card = document.getElementById('storeBindingCard');
  if (!card) return;

  const statusEl = document.getElementById('bindingStatus');
  const descriptionEl = document.getElementById('bindingDescription');
  const metaEl = document.getElementById('bindingMeta');
  const applyForm = document.getElementById('bindingApplyForm');
  const withdrawForm = document.getElementById('bindingWithdrawForm');
  const hero = document.querySelector('.employee-workspace-hero');
  const employeeId = String(hero?.dataset.employeeUserId || 'self').trim() || 'self';
  const cacheKey = `mw_employee_binding_v2:${employeeId}`;
  const CACHE_MAX_AGE = 10 * 60 * 1000;
  const REQUEST_TIMEOUT = 6000;

  const formatDate = (value) => {
    if (!value) return '—';
    const raw = String(value).trim();
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
    const date = new Date(`${raw}${hasZone ? '' : 'Z'}`);
    if (Number.isNaN(date.getTime())) return raw.replace('T', ' ').slice(0, 16);

    const parts = new Intl.DateTimeFormat('zh-TW', {
      timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}`;
  };

  const setMeta = (label, value, detail, detailClass = '') => {
    metaEl.replaceChildren();
    const labelEl = document.createElement('span');
    labelEl.textContent = String(label || '');
    const valueEl = document.createElement('b');
    valueEl.textContent = String(value || '—');
    const detailEl = document.createElement('small');
    detailEl.textContent = String(detail || '');
    if (detailClass) detailEl.classList.add(detailClass);
    metaEl.append(labelEl, valueEl, detailEl);
  };

  const setState = (data) => {
    const status = String(data.status || 'none');
    card.classList.remove('loading', 'state-none', 'state-pending', 'state-active', 'state-ended');
    card.removeAttribute('aria-busy');
    applyForm.hidden = true;
    withdrawForm.hidden = true;

    if (!data.eligible && status !== 'active' && status !== 'pending') {
      card.classList.add('state-ended');
      statusEl.textContent = '目前不適用'; statusEl.dataset.state = 'ended';
      descriptionEl.textContent = '綁店申請只開放目前啟用中的接單人員。';
      setMeta('資格狀態', '無法申請', '如果你的接單身分剛更新，請重新登入或請客服同步人員資料。');
      return;
    }
    if (status === 'active') {
      card.classList.add('state-active');
      statusEl.textContent = '綁店中'; statusEl.dataset.state = 'active';
      descriptionEl.textContent = '你的綁店資格已生效。符合現行分潤規則的訂單會額外套用 +3% 綁店加成，最高 90%。';
      const syncError = data.discord_sync_status === 'error';
      setMeta('生效時間', formatDate(data.started_at), syncError ? 'Discord 身分組同步異常' : 'Discord 身分組已同步', syncError ? 'binding-sync-error' : 'binding-sync-ok');
      return;
    }
    if (status === 'pending') {
      card.classList.add('state-pending');
      statusEl.textContent = '審核中'; statusEl.dataset.state = 'pending';
      descriptionEl.textContent = '你的申請已送出，客服核准後才會正式取得綁店資格與 Discord 身分組。';
      setMeta('申請時間', formatDate(data.requested_at), '審核期間不會先套用 +3% 綁店加成。');
      withdrawForm.hidden = false;
      return;
    }
    if (status === 'rejected') {
      card.classList.add('state-ended');
      statusEl.textContent = '未通過'; statusEl.dataset.state = 'ended';
      descriptionEl.textContent = '上一筆綁店申請未通過；若目前條件已符合，可以重新提出申請。';
      setMeta('最近狀態', data.status_label || '未通過', data.note || '可重新提出申請。');
      applyForm.hidden = false;
      return;
    }
    if (status === 'ended' || status === 'withdrawn') {
      card.classList.add('state-ended');
      statusEl.textContent = status === 'ended' ? '已解除' : '已撤回'; statusEl.dataset.state = 'ended';
      descriptionEl.textContent = '目前沒有生效中的綁店資格，需要時可以重新提出申請。';
      setMeta('最近狀態', data.status_label || '已結束', data.ended_at ? `結束時間 ${formatDate(data.ended_at)}` : '目前可重新申請。');
      applyForm.hidden = false;
      return;
    }
    card.classList.add('state-none');
    statusEl.textContent = '未綁店'; statusEl.dataset.state = 'none';
    descriptionEl.textContent = '成為魔丸綁店人員後，可取得額外 +3% 綁店加成；一般最高 87%，綁店最高 90%。';
    setMeta('資格狀態', '尚未申請', '送出後由客服確認；客服也可以直接授予資格。');
    applyForm.hidden = false;
  };

  const readCache = () => {
    try {
      const cached = JSON.parse(sessionStorage.getItem(cacheKey) || 'null');
      if (!cached?.data || !cached.savedAt || Date.now() - Number(cached.savedAt) > CACHE_MAX_AGE) return null;
      return cached.data;
    } catch (_) { return null; }
  };

  const writeCache = (data) => {
    try { sessionStorage.setItem(cacheKey, JSON.stringify({ savedAt: Date.now(), data })); } catch (_) {}
  };

  const showFailure = (timedOut) => {
    card.classList.remove('loading');
    card.removeAttribute('aria-busy');
    card.classList.add('state-ended');
    statusEl.textContent = timedOut ? '讀取較慢' : '暫時無法讀取';
    statusEl.dataset.state = 'ended';
    descriptionEl.textContent = timedOut
      ? '綁店資料還沒回來，但不會鎖住其他功能。可以稍後重新讀取。'
      : '目前無法取得綁店狀態，不會因此變更任何既有資格。';
    setMeta('資格狀態', timedOut ? '稍後再試' : '讀取失敗', '你仍可使用上方與底部導覽切換其他功能。');
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'binding-action employee-load-retry';
    retry.textContent = '重新讀取';
    retry.addEventListener('click', () => loadState(true));
    metaEl.appendChild(retry);
  };

  async function loadState(showLoading = false) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    if (showLoading) {
      card.classList.add('loading');
      card.setAttribute('aria-busy', 'true');
      statusEl.textContent = '讀取中';
    }
    try {
      const response = await fetch('/employee/store-binding/status', {
        credentials: 'same-origin', cache: 'no-store',
        headers: { 'Accept': 'application/json' }, signal: controller.signal,
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || '讀取失敗');
      writeCache(payload.data || {});
      setState(payload.data || {});
    } catch (error) {
      if (!readCache()) showFailure(error?.name === 'AbortError');
    } finally {
      window.clearTimeout(timer);
    }
  }

  const cached = readCache();
  if (cached) {
    setState(cached);
    loadState(false);
  } else {
    card.setAttribute('aria-busy', 'true');
    loadState(true);
  }
})();