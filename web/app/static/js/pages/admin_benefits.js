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

  const directChild = (branch, selector) =>
    Array.from(branch.children).find((child) => child.matches && child.matches(selector)) || null;

  const branchRow = (branch) => directChild(branch, '.benefit-tree-row');
  const branchParentCheckbox = (branch) => {
    const row = branchRow(branch);
    return row ? row.querySelector('[data-benefit-tree-parent]') : null;
  };
  const branchToggle = (branch) => {
    const row = branchRow(branch);
    return row ? row.querySelector('[data-benefit-tree-toggle]') : null;
  };
  const branchLeaves = (branch) => Array.from(branch.querySelectorAll('[data-benefit-tree-leaf-checkbox]'));

  const setBranchOpen = (branch, open) => {
    const toggle = branchToggle(branch);
    branch.classList.toggle('is-open', Boolean(open));
    if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  };

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
    const toggle = branchToggle(branch);

    if (toggle) {
      toggle.addEventListener('click', () => {
        setBranchOpen(branch, !branch.classList.contains('is-open'));
      });
    }

    if (parent) {
      parent.addEventListener('change', () => {
        const checked = parent.checked;
        branchLeaves(branch).forEach((checkbox) => {
          checkbox.checked = checked;
        });
        if (checked) setBranchOpen(branch, true);
        refreshTreeState();
      });
    }
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
        if (query && visibleLeaves.length) setBranchOpen(group, true);
      });

      Array.from(tree.querySelectorAll('[data-benefit-tree-game]')).forEach((game) => {
        const visibleGroups = Array.from(game.querySelectorAll('[data-benefit-tree-group]')).filter((group) => !group.hidden);
        game.hidden = Boolean(query) && visibleGroups.length === 0;
        if (query && visibleGroups.length) setBranchOpen(game, true);
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

  // Keep the tree collapsed on load even when an old all-store template maps to
  // every current product. The user can expand only the game/group they need.
  branches.forEach((branch) => setBranchOpen(branch, false));
  refreshTreeState();
})();
