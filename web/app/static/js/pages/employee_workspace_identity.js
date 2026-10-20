(() => {
  const hero = document.querySelector('.employee-workspace-hero');
  const nameNode = hero?.querySelector('[data-employee-workspace-name]');
  if (!hero || !nameNode) return;

  const userId = String(hero.dataset.employeeUserId || '').trim();
  const storeName = String(hero.dataset.employeeStoreName || '').trim();
  const storageKey = userId ? `mw_employee_store_name:${userId}` : '';

  if (storeName) {
    nameNode.textContent = storeName;
    if (storageKey) {
      try { localStorage.setItem(storageKey, storeName); } catch (_) {}
    }
    return;
  }

  if (!storageKey) return;
  try {
    const cached = String(localStorage.getItem(storageKey) || '').trim();
    if (cached) nameNode.textContent = cached;
  } catch (_) {}
})();
