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

  const memberCheckboxes = Array.from(document.querySelectorAll('[data-benefit-member-checkbox]'));
  const memberCount = document.querySelector('[data-benefit-member-count]');
  const issueForm = document.querySelector('[data-benefit-issue-form]');
  const refreshMemberCount = () => {
    if (!memberCount) return;
    const count = memberCheckboxes.filter((checkbox) => checkbox.checked).length;
    memberCount.textContent = `已選 ${count} 位`;
  };
  memberCheckboxes.forEach((checkbox) => checkbox.addEventListener('change', refreshMemberCount));
  refreshMemberCount();
  if (issueForm) {
    issueForm.addEventListener('submit', (event) => {
      if (memberCheckboxes.some((checkbox) => checkbox.checked)) return;
      event.preventDefault();
      window.alert('請至少選擇一位要發放的會員。');
    });
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
