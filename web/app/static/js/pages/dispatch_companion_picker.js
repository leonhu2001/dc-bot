(() => {
  if (window.__mwDispatchCompanionPickerStarted) return;
  if (window.location.pathname !== '/dispatch') return;
  window.__mwDispatchCompanionPickerStarted = true;

  const STYLE_ID = 'mw-dispatch-companion-picker-style';
  let activePicker = null;
  let refreshQueued = false;

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .dispatch-support-form.mw-picker-ready{position:relative;align-items:start}
      .dispatch-support-form .mw-companion-native{position:absolute!important;width:1px!important;height:1px!important;opacity:0!important;pointer-events:none!important;overflow:hidden!important;clip:rect(0 0 0 0)!important;white-space:nowrap!important}
      .dispatch-support-form .mw-companion-picker{position:relative;min-width:0;width:100%}
      .dispatch-support-tools .mw-companion-trigger{width:100%;min-height:40px;display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid rgba(255,255,255,.13)!important;border-radius:12px!important;padding:10px 12px!important;background:#11161a!important;color:#eef2f6!important;box-shadow:none!important;font:inherit!important;font-weight:800!important;text-align:left;cursor:pointer;transform:none!important;filter:none!important;transition:border-color .14s ease,background .14s ease!important}
      .dispatch-support-tools .mw-companion-trigger:hover{border-color:rgba(245,198,107,.45)!important;background:#151b20!important;box-shadow:none!important;transform:none!important;filter:none!important}
      .dispatch-support-tools .mw-companion-trigger:focus-visible{outline:2px solid rgba(245,198,107,.9);outline-offset:2px}
      .dispatch-support-tools .mw-companion-trigger.is-invalid{border-color:rgba(255,107,138,.72)!important}
      .mw-companion-trigger-label{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .mw-companion-trigger-chevron{flex:0 0 auto;color:#aeb7bf;font-size:12px;transition:transform .14s ease}
      .mw-companion-picker.is-open .mw-companion-trigger-chevron{transform:rotate(180deg)}
      .mw-companion-panel{position:absolute;z-index:120;left:0;right:0;top:calc(100% + 7px);display:none;border:1px solid rgba(245,198,107,.22);border-radius:14px;background:#0d1216;box-shadow:0 18px 48px rgba(0,0,0,.52);overflow:hidden}
      .mw-companion-picker.is-open .mw-companion-panel{display:block}
      .mw-companion-search-wrap{padding:10px;border-bottom:1px solid rgba(255,255,255,.08);background:#10161a}
      .dispatch-support-tools .mw-companion-search{width:100%;box-sizing:border-box;border:1px solid rgba(255,255,255,.12);border-radius:10px;background:#171d22;color:#f4f6f8;padding:9px 11px;font:inherit;outline:none}
      .dispatch-support-tools .mw-companion-search::placeholder{color:#78838d}
      .dispatch-support-tools .mw-companion-search:focus{border-color:rgba(245,198,107,.55);box-shadow:0 0 0 2px rgba(245,198,107,.08)}
      .mw-companion-options{max-height:min(360px,52vh);overflow:auto;padding:6px;scrollbar-color:#59626a #11161a;scrollbar-width:thin}
      .dispatch-support-tools button.mw-companion-option{width:100%;min-height:0!important;display:flex;align-items:center;justify-content:space-between;border:0!important;border-radius:9px!important;padding:9px 10px!important;background:transparent!important;color:#dfe5ea!important;box-shadow:none!important;font:inherit!important;font-weight:700!important;text-align:left;cursor:pointer;transform:none!important;filter:none!important;transition:background .12s ease,color .12s ease!important}
      .dispatch-support-tools button.mw-companion-option:hover,.dispatch-support-tools button.mw-companion-option:focus-visible{background:rgba(245,198,107,.10)!important;color:#fff4d2!important;outline:none;box-shadow:none!important;transform:none!important;filter:none!important}
      .dispatch-support-tools button.mw-companion-option.is-selected{background:rgba(245,198,107,.16)!important;color:#ffe6aa!important}
      .mw-companion-option-check{opacity:0;color:#f5c66b;font-weight:900}
      .mw-companion-option.is-selected .mw-companion-option-check{opacity:1}
      .mw-companion-empty{display:none;padding:16px 12px;color:#8c969f;font-size:13px;text-align:center}
      .mw-companion-empty.is-visible{display:block}
      @media(max-width:760px){.mw-companion-panel{position:fixed;left:12px;right:12px;top:auto;bottom:12px;max-height:70vh}.mw-companion-options{max-height:52vh}}
    `;
    document.head.appendChild(style);
  }

  function closePicker(picker, restoreFocus = false) {
    if (!picker) return;
    picker.root.classList.remove('is-open');
    picker.trigger.setAttribute('aria-expanded', 'false');
    if (activePicker === picker) activePicker = null;
    if (restoreFocus) picker.trigger.focus({ preventScroll: true });
  }

  function openPicker(picker) {
    if (activePicker && activePicker !== picker) closePicker(activePicker);
    activePicker = picker;
    picker.root.classList.add('is-open');
    picker.trigger.setAttribute('aria-expanded', 'true');
    picker.search.value = '';
    filterOptions(picker, '');
    window.requestAnimationFrame(() => picker.search.focus({ preventScroll: true }));
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

  function selectValue(picker, value, label) {
    picker.select.value = value;
    picker.select.dispatchEvent(new Event('change', { bubbles: true }));
    picker.label.textContent = label;
    picker.trigger.classList.remove('is-invalid');

    picker.optionButtons.forEach((button) => {
      const selected = button.dataset.value === value;
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-selected', selected ? 'true' : 'false');
    });

    closePicker(picker, true);
  }

  function enhanceSelect(select) {
    if (!(select instanceof HTMLSelectElement)) return;
    if (select.dataset.mwCompanionPicker === '1') return;

    const form = select.closest('.dispatch-support-form');
    if (!form) return;

    select.dataset.mwCompanionPicker = '1';
    const originallyRequired = select.required;
    select.required = false;
    select.classList.add('mw-companion-native');
    form.classList.add('mw-picker-ready');

    const root = document.createElement('div');
    root.className = 'mw-companion-picker';

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'mw-companion-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');

    const label = document.createElement('span');
    label.className = 'mw-companion-trigger-label';
    label.textContent = select.selectedOptions[0]?.textContent?.trim() || '選擇陪玩指派到此單';

    const chevron = document.createElement('span');
    chevron.className = 'mw-companion-trigger-chevron';
    chevron.setAttribute('aria-hidden', 'true');
    chevron.textContent = '▾';

    trigger.append(label, chevron);

    const panel = document.createElement('div');
    panel.className = 'mw-companion-panel';

    const searchWrap = document.createElement('div');
    searchWrap.className = 'mw-companion-search-wrap';

    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'mw-companion-search';
    search.placeholder = '搜尋陪玩名稱…';
    search.autocomplete = 'off';
    search.setAttribute('aria-label', '搜尋陪玩');
    searchWrap.appendChild(search);

    const options = document.createElement('div');
    options.className = 'mw-companion-options';
    options.setAttribute('role', 'listbox');

    const empty = document.createElement('div');
    empty.className = 'mw-companion-empty';
    empty.textContent = '找不到符合的陪玩';

    const optionButtons = [];
    Array.from(select.options).forEach((option) => {
      if (!option.value) return;

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'mw-companion-option';
      button.dataset.value = option.value;
      button.dataset.searchText = String(option.textContent || '').trim().toLocaleLowerCase('zh-Hant');
      button.setAttribute('role', 'option');

      const text = document.createElement('span');
      text.textContent = String(option.textContent || '').trim();

      const check = document.createElement('span');
      check.className = 'mw-companion-option-check';
      check.setAttribute('aria-hidden', 'true');
      check.textContent = '✓';

      button.append(text, check);
      button.addEventListener('click', () => selectValue(picker, option.value, text.textContent));
      optionButtons.push(button);
      options.appendChild(button);
    });

    panel.append(searchWrap, options, empty);
    root.append(trigger, panel);
    select.insertAdjacentElement('afterend', root);

    const picker = { form, select, root, trigger, label, search, empty, optionButtons, originallyRequired };

    trigger.addEventListener('click', () => {
      if (root.classList.contains('is-open')) closePicker(picker);
      else openPicker(picker);
    });

    search.addEventListener('input', () => filterOptions(picker, search.value));
    search.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closePicker(picker, true);
      }
      if (event.key === 'ArrowDown') {
        const first = optionButtons.find((button) => !button.hidden);
        if (first) {
          event.preventDefault();
          first.focus();
        }
      }
    });

    optionButtons.forEach((button, index) => {
      button.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          closePicker(picker, true);
          return;
        }
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;

        const visible = optionButtons.filter((candidate) => !candidate.hidden);
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

    form.addEventListener('submit', (event) => {
      if (!originallyRequired || select.value) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      trigger.classList.add('is-invalid');
      openPicker(picker);
    });

    select.addEventListener('change', () => {
      const current = select.selectedOptions[0];
      label.textContent = current?.value
        ? String(current.textContent || '').trim()
        : '選擇陪玩指派到此單';
      trigger.classList.toggle('is-invalid', originallyRequired && !select.value);
    });

    if (select.value) {
      const current = select.selectedOptions[0];
      selectValue(picker, select.value, String(current?.textContent || '').trim());
    }
  }

  function enhanceAll() {
    document
      .querySelectorAll('.dispatch-support-form select[name="companion_discord_id"]')
      .forEach(enhanceSelect);
  }

  function queueEnhanceAll() {
    if (refreshQueued) return;
    refreshQueued = true;
    window.requestAnimationFrame(() => {
      refreshQueued = false;
      enhanceAll();
    });
  }

  injectStyles();
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
})();
