(() => {
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

  const picker = document.querySelector('[data-benefit-product-picker]');
  if (!picker) return;

  const tree = picker.querySelector('[data-benefit-product-tree]');
  if (!tree) return;

  const leaves = Array.from(tree.querySelectorAll('[data-benefit-tree-leaf-checkbox]'));
  const branches = Array.from(tree.querySelectorAll('[data-benefit-tree-branch]'));
  const countLabel = picker.querySelector('[data-benefit-product-count]');
  const searchInput = picker.querySelector('[data-benefit-product-search]');
  const selectAllButton = picker.querySelector('[data-benefit-tree-select-all]');
  const clearButton = picker.querySelector('[data-benefit-tree-clear]');
  const templateForm = document.querySelector('[data-benefit-template-form]');

  const branchParentCheckbox = (branch) => {
    const summary = Array.from(branch.children).find((child) => child.tagName === 'SUMMARY');
    return summary ? summary.querySelector('[data-benefit-tree-parent]') : null;
  };

  const branchLeaves = (branch) => Array.from(branch.querySelectorAll('[data-benefit-tree-leaf-checkbox]'));

  const syncBranch = (branch) => {
    const parent = branchParentCheckbox(branch);
    if (!parent) return;
    const children = branchLeaves(branch);
    const checkedCount = children.filter((checkbox) => checkbox.checked).length;
    parent.checked = children.length > 0 && checkedCount === children.length;
    parent.indeterminate = checkedCount > 0 && checkedCount < children.length;
  };

  const refreshTreeState = () => {
    branches.slice().reverse().forEach(syncBranch);
    if (countLabel) {
      const count = leaves.filter((checkbox) => checkbox.checked).length;
      countLabel.textContent = `已選 ${count} 項`;
    }
  };

  branches.forEach((branch) => {
    const parent = branchParentCheckbox(branch);
    if (!parent) return;

    parent.addEventListener('click', (event) => {
      event.stopPropagation();
    });
    parent.addEventListener('change', () => {
      const checked = parent.checked;
      branchLeaves(branch).forEach((checkbox) => {
        checkbox.checked = checked;
      });
      refreshTreeState();
    });
  });

  leaves.forEach((checkbox) => checkbox.addEventListener('change', refreshTreeState));

  if (selectAllButton) {
    selectAllButton.addEventListener('click', () => {
      leaves.forEach((checkbox) => {
        checkbox.checked = true;
      });
      refreshTreeState();
    });
  }

  if (clearButton) {
    clearButton.addEventListener('click', () => {
      leaves.forEach((checkbox) => {
        checkbox.checked = false;
      });
      refreshTreeState();
    });
  }

  if (searchInput) {
    const applyProductFilter = () => {
      const query = String(searchInput.value || '').trim().toLowerCase();
      const leafRows = Array.from(tree.querySelectorAll('.benefit-tree-leaf'));
      leafRows.forEach((row) => {
        const haystack = String(row.dataset.benefitOption || '').toLowerCase();
        row.hidden = Boolean(query) && !haystack.includes(query);
      });

      Array.from(tree.querySelectorAll('[data-benefit-tree-group]')).forEach((group) => {
        const visibleLeaves = Array.from(group.querySelectorAll('.benefit-tree-leaf')).filter((row) => !row.hidden);
        group.hidden = Boolean(query) && visibleLeaves.length === 0;
        if (query && visibleLeaves.length) group.open = true;
      });

      Array.from(tree.querySelectorAll('[data-benefit-tree-game]')).forEach((game) => {
        const visibleGroups = Array.from(game.querySelectorAll('[data-benefit-tree-group]')).filter((group) => !group.hidden);
        game.hidden = Boolean(query) && visibleGroups.length === 0;
        if (query && visibleGroups.length) game.open = true;
      });
    };

    searchInput.addEventListener('input', applyProductFilter);
  }

  if (templateForm) {
    templateForm.addEventListener('submit', (event) => {
      if (leaves.some((checkbox) => checkbox.checked)) return;
      event.preventDefault();
      window.alert('請至少勾選一個適用商品。');
    });
  }

  refreshTreeState();
})();
