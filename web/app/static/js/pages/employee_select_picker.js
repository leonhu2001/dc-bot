(() => {
  if (window.__mwEmployeeSelectPickerStarted) return;
  window.__mwEmployeeSelectPickerStarted = true;

  let activePicker = null;
  let enhanceQueued = false;

  function inEmployeeWorkspace() {
    return document.body.classList.contains('employee-workspace-site');
  }

  function closePicker(picker, restoreFocus = false) {
    if (!picker) return;
    picker.root.classList.remove('is-open');
    picker.trigger.setAttribute('aria-expanded', 'false');
    if (activePicker === picker) activePicker = null;
    if (restoreFocus && !picker.trigger.disabled) {
      picker.trigger.focus({ preventScroll: true });
    }
  }

  function filterOptions(picker, query) {
    const normalized = String(query || '').trim().toLocaleLowerCase('zh-Hant');
    let visibleCount = 0;

    picker.optionButtons.forEach((button) => {
      const matches = !normalized || button.dataset.searchText.includes(normalized);
      button.hidden = !matches;
      if (matches) visibleCount += 1;
    });

    picker.empty.classList.toggle('is-visible', visibleCount === 0);
  }

  function openPicker(picker) {
    if (!picker || picker.trigger.disabled) return;
    if (activePicker && activePicker !== picker) closePicker(activePicker);

    syncSelectedState(picker);
    activePicker = picker;
    picker.root.classList.add('is-open');
    picker.trigger.setAttribute('aria-expanded', 'true');

    if (!picker.searchWrap.hidden) {
      picker.search.value = '';
      filterOptions(picker, '');
      window.requestAnimationFrame(() => {
        picker.search.focus({ preventScroll: true });
      });
    }
  }

  function syncSelectedState(picker) {
    const selected = picker.select.selectedOptions[0];
    const label = selected
      ? String(selected.textContent || '').trim()
      : picker.placeholder;

    picker.label.textContent = label || picker.placeholder;
    picker.trigger.classList.toggle('is-placeholder', !picker.select.value);
    picker.trigger.classList.toggle(
      'is-invalid',
      picker.originallyRequired && !picker.select.value
    );
    picker.trigger.disabled = picker.select.disabled;

    picker.optionButtons.forEach((button) => {
      const selectedNow = button.dataset.value === String(picker.select.value || '');
      button.classList.toggle('is-selected', selectedNow);
      button.setAttribute('aria-selected', selectedNow ? 'true' : 'false');
    });
  }

  function selectValue(picker, value) {
    picker.select.value = value;
    picker.select.dispatchEvent(new Event('input', { bubbles: true }));
    picker.select.dispatchEvent(new Event('change', { bubbles: true }));
    syncSelectedState(picker);
    closePicker(picker, true);
  }

  function makeOptionButton(picker, option) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'mw-employee-select-option';
    button.dataset.value = String(option.value || '');
    button.dataset.searchText = String(option.textContent || '')
      .trim()
      .toLocaleLowerCase('zh-Hant');
    button.setAttribute('role', 'option');
    button.disabled = Boolean(option.disabled);

    const text = document.createElement('span');
    text.textContent = String(option.textContent || '').trim();

    const check = document.createElement('span');
    check.className = 'mw-employee-select-option-check';
    check.setAttribute('aria-hidden', 'true');
    check.textContent = '✓';

    button.append(text, check);
    button.addEventListener('click', () => {
      if (!button.disabled) selectValue(picker, button.dataset.value);
    });

    return button;
  }

  function enhanceSelect(select) {
    if (!(select instanceof HTMLSelectElement)) return;
    if (select.multiple || Number(select.size || 0) > 1) return;
    if (select.dataset.mwEmployeeSelectPicker === '1') return;
    if (select.closest('.mw-employee-select')) return;

    select.dataset.mwEmployeeSelectPicker = '1';

    const originalRequired = select.required;
    select.required = false;
    select.classList.add('mw-employee-native-select');

    const root = document.createElement('div');
    root.className = 'mw-employee-select';

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'mw-employee-select-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');

    const label = document.createElement('span');
    label.className = 'mw-employee-select-label';

    const chevron = document.createElement('span');
    chevron.className = 'mw-employee-select-chevron';
    chevron.setAttribute('aria-hidden', 'true');
    chevron.textContent = '▾';

    trigger.append(label, chevron);

    const panel = document.createElement('div');
    panel.className = 'mw-employee-select-panel';

    const searchWrap = document.createElement('div');
    searchWrap.className = 'mw-employee-select-search-wrap';

    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'mw-employee-select-search';
    search.placeholder = '搜尋選項…';
    search.autocomplete = 'off';
    search.setAttribute('aria-label', '搜尋選項');
    searchWrap.appendChild(search);

    const options = document.createElement('div');
    options.className = 'mw-employee-select-options';
    options.setAttribute('role', 'listbox');

    const empty = document.createElement('div');
    empty.className = 'mw-employee-select-empty';
    empty.textContent = '找不到符合的選項';

    const picker = {
      select,
      root,
      trigger,
      label,
      panel,
      searchWrap,
      search,
      options,
      empty,
      optionButtons: [],
      originallyRequired: originalRequired,
      placeholder: '選擇項目'
    };

    const emptyOption = Array.from(select.options).find((option) => !option.value);
    if (emptyOption) {
      picker.placeholder = String(emptyOption.textContent || '').trim() || '選擇項目';
    }

    picker.optionButtons = Array.from(select.options).map((option) => {
      const button = makeOptionButton(picker, option);
      options.appendChild(button);
      return button;
    });

    searchWrap.hidden = picker.optionButtons.length <= 8;
    panel.append(searchWrap, options, empty);
    root.append(trigger, panel);
    select.insertAdjacentElement('afterend', root);

    trigger.addEventListener('click', () => {
      if (root.classList.contains('is-open')) closePicker(picker);
      else openPicker(picker);
    });

    search.addEventListener('input', () => filterOptions(picker, search.value));
    search.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closePicker(picker, true);
        return;
      }

      if (event.key === 'ArrowDown') {
        const first = picker.optionButtons.find(
          (button) => !button.hidden && !button.disabled
        );
        if (first) {
          event.preventDefault();
          first.focus();
        }
      }
    });

    picker.optionButtons.forEach((button) => {
      button.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          closePicker(picker, true);
          return;
        }

        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;

        const visible = picker.optionButtons.filter(
          (candidate) => !candidate.hidden && !candidate.disabled
        );
        const currentIndex = visible.indexOf(button);
        const nextIndex = event.key === 'ArrowDown'
          ? Math.min(visible.length - 1, currentIndex + 1)
          : Math.max(0, currentIndex - 1);

        if (visible[nextIndex]) {
          event.preventDefault();
          visible[nextIndex].focus();
        }
      });
    });

    select.addEventListener('change', () => syncSelectedState(picker));

    const form = select.closest('form');
    if (form && originalRequired) {
      form.addEventListener('submit', (event) => {
        if (select.value) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        trigger.classList.add('is-invalid');
        openPicker(picker);
      });
    }

    syncSelectedState(picker);
  }

  function enhanceAll() {
    if (!inEmployeeWorkspace()) return;

    document.body
      .querySelectorAll('select:not([multiple]):not([data-mw-native-select])')
      .forEach(enhanceSelect);
  }

  function queueEnhanceAll() {
    if (enhanceQueued) return;
    enhanceQueued = true;
    window.requestAnimationFrame(() => {
      enhanceQueued = false;
      enhanceAll();
    });
  }

  function init() {
    if (!inEmployeeWorkspace()) return;

    enhanceAll();

    document.addEventListener('pointerdown', (event) => {
      if (!activePicker) return;
      if (activePicker.root.contains(event.target)) return;
      closePicker(activePicker);
    }, true);

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && activePicker) {
        closePicker(activePicker, true);
      }
    });

    const observer = new MutationObserver(queueEnhanceAll);
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
