(() => {
  const scopeSelect = document.querySelector('[data-benefit-scope-select]');
  const scopePanels = Array.from(document.querySelectorAll('[data-scope-panel]'));

  const refreshScopePanels = () => {
    const value = scopeSelect ? scopeSelect.value : 'all';
    scopePanels.forEach((panel) => {
      panel.hidden = panel.dataset.scopePanel !== value;
    });
  };

  if (scopeSelect) {
    scopeSelect.addEventListener('change', refreshScopePanels);
    refreshScopePanels();
  }

  document.querySelectorAll('[data-benefit-filter]').forEach((input) => {
    const targetId = input.dataset.benefitFilter;
    const target = document.getElementById(targetId);
    if (!target) return;

    const rows = Array.from(target.querySelectorAll('[data-benefit-option]'));
    const applyFilter = () => {
      const query = String(input.value || '').trim().toLowerCase();
      rows.forEach((row) => {
        const haystack = String(row.dataset.benefitOption || '').toLowerCase();
        row.classList.toggle('is-filtered', Boolean(query) && !haystack.includes(query));
      });
    };

    input.addEventListener('input', applyFilter);
  });
})();
