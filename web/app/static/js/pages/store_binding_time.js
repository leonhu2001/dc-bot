(() => {
  const formatTaipei = (value) => {
    const raw = String(value || '').trim();
    if (!raw || raw === '—') return raw || '—';

    const normalized = raw.includes('T') ? raw : raw.replace(' ', 'T');
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
    const date = new Date(`${normalized}${hasZone ? '' : ':00Z'}`);
    if (Number.isNaN(date.getTime())) return raw;

    const parts = new Intl.DateTimeFormat('zh-TW', {
      timeZone: 'Asia/Taipei',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}`;
  };

  const selectors = [
    '.sbm-card.pending .sbm-facts > div:first-child b',
    '.sbm-card.active .sbm-facts > div:first-child b',
    '.sbm-history .history-row > span:nth-child(3)',
  ];

  document.querySelectorAll(selectors.join(',')).forEach((node) => {
    node.textContent = formatTaipei(node.textContent);
  });
})();