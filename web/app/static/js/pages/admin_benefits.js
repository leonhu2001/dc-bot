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

  let scrollShell = tree.parentElement;
  if (!scrollShell || !scrollShell.classList.contains('benefit-product-scroll-shell')) {
    scrollShell = document.createElement('div');
    scrollShell.className = 'benefit-product-scroll-shell';
    tree.parentNode.insertBefore(scrollShell, tree);
    scrollShell.appendChild(tree);
  }

  let scrollTrack = scrollShell.querySelector('[data-benefit-scroll-track]');
  if (!scrollTrack) {
    scrollTrack = document.createElement('div');
    scrollTrack.className = 'benefit-product-scrollbar';
    scrollTrack.dataset.benefitScrollTrack = '';
    scrollTrack.setAttribute('aria-hidden', 'true');
    scrollShell.appendChild(scrollTrack);
  }

  let scrollThumb = scrollTrack.querySelector('[data-benefit-scroll-thumb]');
  if (!scrollThumb) {
    scrollThumb = document.createElement('div');
    scrollThumb.className = 'benefit-product-scrollbar-thumb';
    scrollThumb.dataset.benefitScrollThumb = '';
    scrollTrack.appendChild(scrollThumb);
  }

  let scrollbarFrame = 0;
  const updateProductScrollbar = () => {
    scrollbarFrame = 0;
    const viewportHeight = Math.max(0, tree.clientHeight);
    const contentHeight = Math.max(viewportHeight, tree.scrollHeight);
    const trackHeight = Math.max(0, scrollTrack.clientHeight);
    const maxScroll = Math.max(0, contentHeight - viewportHeight);

    if (!viewportHeight || !trackHeight || maxScroll <= 1) {
      scrollTrack.classList.add('is-disabled');
      scrollThumb.style.height = `${trackHeight}px`;
      scrollThumb.style.transform = 'translateY(0px)';
      return;
    }

    scrollTrack.classList.remove('is-disabled');
    const proportionalHeight = trackHeight * (viewportHeight / contentHeight);
    const thumbHeight = Math.min(trackHeight, Math.max(48, proportionalHeight));
    const travel = Math.max(0, trackHeight - thumbHeight);
    const offset = maxScroll > 0 ? (tree.scrollTop / maxScroll) * travel : 0;
    scrollThumb.style.height = `${thumbHeight}px`;
    scrollThumb.style.transform = `translateY(${Math.max(0, Math.min(travel, offset))}px)`;
  };

  const scheduleProductScrollbar = () => {
    if (scrollbarFrame) cancelAnimationFrame(scrollbarFrame);
    scrollbarFrame = requestAnimationFrame(updateProductScrollbar);
  };

  tree.addEventListener('scroll', scheduleProductScrollbar, { passive: true });
  tree.addEventListener('wheel', (event) => {
    if (scrollTrack.classList.contains('is-disabled')) return;
    const previous = tree.scrollTop;
    tree.scrollTop += event.deltaY;
    if (tree.scrollTop !== previous) event.preventDefault();
  }, { passive: false });

  let dragStartY = 0;
  let dragStartScrollTop = 0;
  let dragging = false;

  const stopThumbDrag = (event) => {
    if (!dragging) return;
    dragging = false;
    scrollThumb.classList.remove('is-dragging');
    if (event && scrollThumb.releasePointerCapture) {
      try {
        scrollThumb.releasePointerCapture(event.pointerId);
      } catch (_) {
        // Pointer capture may already have been released by the browser.
      }
    }
  };

  scrollThumb.addEventListener('pointerdown', (event) => {
    if (scrollTrack.classList.contains('is-disabled')) return;
    dragging = true;
    dragStartY = event.clientY;
    dragStartScrollTop = tree.scrollTop;
    scrollThumb.classList.add('is-dragging');
    if (scrollThumb.setPointerCapture) scrollThumb.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  scrollThumb.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const maxScroll = Math.max(0, tree.scrollHeight - tree.clientHeight);
    const travel = Math.max(1, scrollTrack.clientHeight - scrollThumb.offsetHeight);
    tree.scrollTop = dragStartScrollTop + ((event.clientY - dragStartY) / travel) * maxScroll;
    event.preventDefault();
  });

  scrollThumb.addEventListener('pointerup', stopThumbDrag);
  scrollThumb.addEventListener('pointercancel', stopThumbDrag);

  scrollTrack.addEventListener('pointerdown', (event) => {
    if (event.target === scrollThumb || scrollTrack.classList.contains('is-disabled')) return;
    const rect = scrollTrack.getBoundingClientRect();
    const maxScroll = Math.max(0, tree.scrollHeight - tree.clientHeight);
    const travel = Math.max(1, scrollTrack.clientHeight - scrollThumb.offsetHeight);
    const targetOffset = Math.max(0, Math.min(travel, event.clientY - rect.top - scrollThumb.offsetHeight / 2));
    tree.scrollTop = (targetOffset / travel) * maxScroll;
    event.preventDefault();
  });

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
  const branchChildren = (branch) => directChild(branch, '[data-benefit-tree-children]');
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
    const children = branchChildren(branch);
    const toggle = branchToggle(branch);
    const isOpen = Boolean(open);
    branch.classList.toggle('is-open', isOpen);
    if (children) {
      if (isOpen) children.removeAttribute('hidden');
      else children.setAttribute('hidden', '');
    }
    if (toggle) toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    scheduleProductScrollbar();
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
    scheduleProductScrollbar();
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

      tree.scrollTop = 0;
      scheduleProductScrollbar();
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

  if (window.ResizeObserver) {
    const resizeObserver = new ResizeObserver(scheduleProductScrollbar);
    resizeObserver.observe(tree);
    resizeObserver.observe(scrollTrack);
  } else {
    window.addEventListener('resize', scheduleProductScrollbar);
  }

  if (window.MutationObserver) {
    const mutationObserver = new MutationObserver(scheduleProductScrollbar);
    mutationObserver.observe(tree, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['hidden', 'class'],
    });
  }

  // Keep the tree collapsed on load even when an old all-store template maps to
  // every current product. The user can expand only the game/group they need.
  branches.forEach((branch) => setBranchOpen(branch, false));
  refreshTreeState();
  scheduleProductScrollbar();
})();
