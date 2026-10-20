(() => {
  const forms = Array.from(document.querySelectorAll('.dispatch-support-form'));
  if (!forms.length) return;

  const pickers = [];

  function closePicker(picker) {
    if (!picker) return;
    const menu = picker.querySelector('.dispatch-companion-menu');
    const trigger = picker.querySelector('.dispatch-companion-trigger');
    if (menu) menu.hidden = true;
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    picker.classList.remove('is-open');
  }

  function closeAll(except = null) {
    pickers.forEach((picker) => {
      if (picker !== except) closePicker(picker);
    });
  }

  forms.forEach((form) => {
    const select = form.querySelector('select[name="companion_discord_id"]');
    if (!select || select.dataset.dispatchPickerEnhanced === '1') return;

    select.dataset.dispatchPickerEnhanced = '1';
    const wasRequired = select.required;
    select.required = false;

    const picker = document.createElement('div');
    picker.className = 'dispatch-companion-picker';

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'dispatch-companion-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');

    const triggerLabel = document.createElement('span');
    triggerLabel.className = 'dispatch-companion-trigger-label';
    triggerLabel.textContent = select.options[select.selectedIndex]?.textContent?.trim() || '選擇陪玩指派到此單';

    const triggerArrow = document.createElement('span');
    triggerArrow.className = 'dispatch-companion-trigger-arrow';
    triggerArrow.setAttribute('aria-hidden', 'true');
    triggerArrow.textContent = '▾';

    trigger.append(triggerLabel, triggerArrow);

    const menu = document.createElement('div');
    menu.className = 'dispatch-companion-menu';
    menu.hidden = true;

    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'dispatch-companion-search';
    search.placeholder = '搜尋陪玩';
    search.autocomplete = 'off';
    search.setAttribute('aria-label', '搜尋陪玩');

    const optionList = document.createElement('div');
    optionList.className = 'dispatch-companion-options';
    optionList.setAttribute('role', 'listbox');

    const optionButtons = [];
    Array.from(select.options).forEach((option) => {
      if (!option.value) return;

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'dispatch-companion-option';
      button.dataset.value = option.value;
      button.dataset.searchText = (option.textContent || '').trim().toLocaleLowerCase();
      button.setAttribute('role', 'option');
      button.setAttribute('aria-selected', option.selected ? 'true' : 'false');
      button.textContent = (option.textContent || option.value).trim();

      button.addEventListener('click', () => {
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        triggerLabel.textContent = button.textContent;
        optionButtons.forEach((item) => item.setAttribute('aria-selected', item === button ? 'true' : 'false'));
        picker.classList.remove('is-invalid');
        closePicker(picker);
        trigger.focus();
      });

      optionButtons.push(button);
      optionList.appendChild(button);
    });

    search.addEventListener('input', () => {
      const query = search.value.trim().toLocaleLowerCase();
      optionButtons.forEach((button) => {
        button.hidden = Boolean(query) && !button.dataset.searchText.includes(query);
      });
    });

    const openPicker = () => {
      closeAll(picker);
      menu.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      picker.classList.add('is-open');
      search.value = '';
      optionButtons.forEach((button) => { button.hidden = false; });
      requestAnimationFrame(() => search.focus());
    };

    trigger.addEventListener('click', () => {
      if (menu.hidden) openPicker();
      else closePicker(picker);
    });

    trigger.addEventListener('keydown', (event) => {
      if ((event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') && menu.hidden) {
        event.preventDefault();
        openPicker();
      }
    });

    menu.append(search, optionList);
    picker.append(trigger, menu);
    select.insertAdjacentElement('beforebegin', picker);
    form.classList.add('is-custom-picker');
    pickers.push(picker);

    form.addEventListener('submit', (event) => {
      if (!wasRequired || select.value) return;
      event.preventDefault();
      picker.classList.add('is-invalid');
      openPicker();
    });
  });

  document.addEventListener('click', (event) => {
    const target = event.target;
    pickers.forEach((picker) => {
      if (!picker.contains(target)) closePicker(picker);
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    pickers.forEach((picker) => {
      const trigger = picker.querySelector('.dispatch-companion-trigger');
      const wasOpen = picker.classList.contains('is-open');
      closePicker(picker);
      if (wasOpen && trigger) trigger.focus();
    });
  });
})();
