(() => {
  const card = document.getElementById('storeBindingCard');
  if (!card) return;

  const statusEl = document.getElementById('bindingStatus');
  const descriptionEl = document.getElementById('bindingDescription');
  const metaEl = document.getElementById('bindingMeta');
  const applyForm = document.getElementById('bindingApplyForm');
  const withdrawForm = document.getElementById('bindingWithdrawForm');

  const formatDate = (value) => {
    if (!value) return '—';
    const text = String(value).replace('T', ' ');
    return text.slice(0, 16);
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
    applyForm.hidden = true;
    withdrawForm.hidden = true;

    if (!data.eligible && status !== 'active' && status !== 'pending') {
      card.classList.add('state-ended');
      statusEl.textContent = '目前不適用';
      statusEl.dataset.state = 'ended';
      descriptionEl.textContent = '綁店申請只開放目前啟用中的接單人員。';
      setMeta('資格狀態', '無法申請', '如果你的接單身分剛更新，請重新登入或請客服同步人員資料。');
      return;
    }

    if (status === 'active') {
      card.classList.add('state-active');
      statusEl.textContent = '綁店中';
      statusEl.dataset.state = 'active';
      descriptionEl.textContent = '你的綁店資格已生效。一般分潤制度完成後，綁店加成會額外 +3%，最高 90%。';
      const syncError = data.discord_sync_status === 'error';
      setMeta(
        '生效時間',
        formatDate(data.started_at),
        syncError ? 'Discord 身分組同步異常' : 'Discord 身分組已同步',
        syncError ? 'binding-sync-error' : 'binding-sync-ok',
      );
      return;
    }

    if (status === 'pending') {
      card.classList.add('state-pending');
      statusEl.textContent = '審核中';
      statusEl.dataset.state = 'pending';
      descriptionEl.textContent = '你的申請已送出，客服核准後才會正式取得綁店資格與 Discord 身分組。';
      setMeta('申請時間', formatDate(data.requested_at), '審核期間不會先套用 +3% 綁店加成。');
      withdrawForm.hidden = false;
      return;
    }

    if (status === 'rejected') {
      card.classList.add('state-ended');
      statusEl.textContent = '未通過';
      statusEl.dataset.state = 'ended';
      descriptionEl.textContent = '上一筆綁店申請未通過；若目前條件已符合，可以重新提出申請。';
      setMeta('最近狀態', data.status_label || '未通過', data.note || '可重新提出申請。');
      applyForm.hidden = false;
      return;
    }

    if (status === 'ended' || status === 'withdrawn') {
      card.classList.add('state-ended');
      statusEl.textContent = status === 'ended' ? '已解除' : '已撤回';
      statusEl.dataset.state = 'ended';
      descriptionEl.textContent = '目前沒有生效中的綁店資格，需要時可以重新提出申請。';
      setMeta(
        '最近狀態',
        data.status_label || '已結束',
        data.ended_at ? `結束時間 ${formatDate(data.ended_at)}` : '目前可重新申請。',
      );
      applyForm.hidden = false;
      return;
    }

    card.classList.add('state-none');
    statusEl.textContent = '未綁店';
    statusEl.dataset.state = 'none';
    descriptionEl.textContent = '成為魔丸綁店人員後，可取得額外 +3% 綁店加成；一般最高 87%，綁店最高 90%。';
    setMeta('資格狀態', '尚未申請', '送出後由客服確認；客服也可以直接授予資格。');
    applyForm.hidden = false;
  };

  fetch('/employee/store-binding/status', {
    credentials: 'same-origin',
    headers: { 'Accept': 'application/json' },
  })
    .then((response) => response.json().then((payload) => ({ response, payload })))
    .then(({ response, payload }) => {
      if (!response.ok || !payload.ok) throw new Error(payload.error || '讀取失敗');
      setState(payload.data || {});
    })
    .catch(() => {
      card.classList.remove('loading');
      card.classList.add('state-ended');
      statusEl.textContent = '暫時無法讀取';
      statusEl.dataset.state = 'ended';
      descriptionEl.textContent = '目前無法取得綁店狀態，重新整理後仍有問題請通知客服。';
      setMeta('資格狀態', '讀取失敗', '不會因此變更任何既有資格。');
    });
})();
