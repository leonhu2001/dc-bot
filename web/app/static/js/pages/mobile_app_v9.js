/*
 * Mobile V9 — interaction and information architecture only.
 * No checkout, payment, salary, approval or mutation request is intercepted.
 * Native forms, CSRF, server validation and original JS event handlers own
 * all business actions. V9 only improves navigation, tables and focus.
 */
(() => {
  'use strict';
  const media = window.matchMedia('(max-width: 767px)');
  const NAV_KEY = 'mw_mobile_v9_nav_target';
  const EDITABLE = 'input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), textarea, select, [contenteditable="true"]';
  const SHEETS = 'details.m9-more';
  const FILTERS = '.m9-category-rail, .report-filter-bar, .order3-categories, .member-filters';
  const CARD_TABLE_EXCLUSIONS = '.order3-dialog-panel, .modal-content, .history-ledger-table-wrap, .data-table-virtual, [data-m9-no-cards]';
  const FORM_CONTROLS = 'input,select,textarea';
  const navSelector = '.m9-dock a[href], .m9-workspace-switch a[href], .m9-category-rail a[href]';

  function active() { return media.matches && document.body?.classList.contains('m9-mobile'); }

  function currentNav() {
    document.querySelectorAll('.m9-dock a[href]').forEach((link) => {
      if (link.classList.contains('is-active')) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function closeSheet(sheet) {
    if (!sheet) return;
    sheet.open = false;
    sheet.querySelector(':scope > summary')?.setAttribute('aria-expanded', 'false');
  }

  function markKeyboard() {
    if (!active()) return;
    const editing = !!document.activeElement?.matches?.(EDITABLE);
    document.body.classList.toggle('m9-input-active', editing);
  }

  function scrollActiveFilter() {
    if (!active()) return;
    document.querySelectorAll(FILTERS).forEach((rail) => {
      const selected = rail.querySelector('.is-active, [aria-current="page"]');
      if (!selected || rail.scrollWidth <= rail.clientWidth) return;
      const target = selected.offsetLeft - (rail.clientWidth - selected.clientWidth) / 2;
      rail.scrollLeft = Math.max(0, target);
    });
  }

  function enhanceTable(table) {
    if (!active() || table.dataset.m9Processed === '1') return;
    table.dataset.m9Processed = '1';
    const root = table.closest('main');
    if (!root || table.closest(CARD_TABLE_EXCLUSIONS)) return;
    const headerRow = table.querySelector('thead tr');
    const bodyRows = Array.from(table.querySelectorAll(':scope > tbody > tr'));
    if (!headerRow || !bodyRows.length) return;
    const headings = Array.from(headerRow.querySelectorAll('th')).map((cell) =>
      (cell.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60)
    );
    const complicated = headings.length < 2 || headings.length > 7 ||
      table.querySelector('th[rowspan],th[colspan],td[rowspan],td[colspan]') ||
      bodyRows.some((row) => row.classList.contains('history-dossier-detail-row') ||
        row.querySelectorAll(':scope > td').length !== headings.length);
    if (complicated || table.querySelector('form') ||
        table.matches('.history-ledger-table, .data-table, .order3-products-table')) {
      if (table.scrollWidth > root.clientWidth + 8 && !table.closest(
        '.table-wrap,.table-responsive,.m9-table-scroller,.history-ledger-table-wrap'
      )) {
        const wrapper = document.createElement('div');
        wrapper.className = 'm9-table-scroller'; wrapper.tabIndex = 0;
        wrapper.setAttribute('role', 'region');
        wrapper.setAttribute('aria-label', '表格可以左右滑動');
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);
      }
      return;
    }
    bodyRows.forEach((row) => {
      Array.from(row.querySelectorAll(':scope > td')).forEach((cell, index) => {
        cell.dataset.m9Label = headings[index] || '資訊';
      });
    });
    table.classList.add('m9-card-table');
  }

  function enhanceTables() {
    if (!active()) return;
    document.querySelectorAll('main table:not([data-m9-processed="1"])').forEach(enhanceTable);
  }

  function decorateControls() {
    if (!active()) return;
    const selector = '.report-filter-bar,.center-filter-form,.history-ledger-toolbar,.dispatch-toolbar,.order3-filters,.member-filters';
    document.querySelectorAll(selector).forEach((control) => {
      if (!control.hasAttribute('aria-label')) {
        control.setAttribute('aria-label', '篩選與查詢');
      }
    });
    document.querySelectorAll('main form').forEach((form) => {
      if (form.dataset.m9Decorated) return;
      form.dataset.m9Decorated = '1';
      form.querySelectorAll(FORM_CONTROLS).forEach((field) => {
        if (field instanceof HTMLInputElement && ['hidden','checkbox','radio'].includes(field.type)) return;
        const required = field.required;
        if (required && field.getAttribute('aria-required') !== 'true') field.setAttribute('aria-required', 'true');
        if (!field.id || !field.labels?.length) return;
        field.setAttribute('data-m9-labelled', 'true');
      });
    });
  }

  function noteNavigation(event) {
    if (!active() || event.defaultPrevented || event.button !== 0 ||
        event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('download') || link.target && link.target !== '_self') return;
    if (link.getAttribute('href').startsWith('#')) return;
    let dest;
    try { dest = new URL(link.href, location.href); } catch (_) { return; }
    if (dest.origin !== location.origin ||
        dest.pathname + dest.search === location.pathname + location.search) return;
    if (link.matches(navSelector)) {
      try { sessionStorage.setItem(NAV_KEY, dest.pathname + dest.search); } catch (_) {}
    }
    document.body.classList.add('m9-navigating');
  }

  function restoreExplicitNav() {
    if (!active()) return;
    let dest = '';
    try { dest = sessionStorage.getItem(NAV_KEY) || ''; } catch (_) { return; }
    if (!dest || (dest !== location.pathname && dest !== location.pathname + location.search)) return;
    try { sessionStorage.removeItem(NAV_KEY); } catch (_) {}
    requestAnimationFrame(() => requestAnimationFrame(() => scrollTo({ top: 0, behavior: 'instant' })));
  }

  function invalidField(event) {
    if (!active()) return;
    const field = event.target;
    if (!(field instanceof HTMLElement)) return;
    field.setAttribute('aria-invalid', 'true');
    field.scrollIntoView({
      block: 'center', inline: 'nearest',
      behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'
    });
  }

  function clearField(event) {
    const field = event.target;
    if (field instanceof HTMLElement && field.validity?.valid) field.removeAttribute('aria-invalid');
  }

  function enhanceAll() {
    if (!active()) return;
    currentNav(); scrollActiveFilter(); enhanceTables(); decorateControls();
  }

  function init() {
    if (!active()) return;
    enhanceAll(); restoreExplicitNav(); markKeyboard();
    document.addEventListener('click', (event) => queueMicrotask(() => noteNavigation(event)));
    document.addEventListener('focusin', markKeyboard);
    document.addEventListener('focusout', () => queueMicrotask(markKeyboard));
    document.addEventListener('invalid', invalidField, true);
    document.addEventListener('input', clearField, true);
    document.addEventListener('change', clearField, true);
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const openSheet = document.querySelector(SHEETS + '[open]');
      if (openSheet) {
        event.preventDefault(); closeSheet(openSheet);
        openSheet.querySelector('summary')?.focus({ preventScroll: true });
      }
    });
    document.querySelectorAll(SHEETS).forEach((sheet) => {
      sheet.addEventListener('toggle', () => {
        sheet.querySelector(':scope > summary')?.setAttribute('aria-expanded', sheet.open ? 'true' : 'false');
        if (sheet.open) document.querySelectorAll(SHEETS).forEach(other => {
          if (other !== sheet) closeSheet(other);
        });
      });
    });
    // AJAX-managed lists and tabs are enhanced only after content changes.
    let pending = false;
    const observer = new MutationObserver(() => {
      if (pending || !active()) return;
      pending = true;
      requestAnimationFrame(() => { pending = false; enhanceAll(); });
    });
    for (const main of document.querySelectorAll('main#m8-main')) {
      observer.observe(main, { childList: true, subtree: true });
    }
    window.addEventListener('pageshow', () => {
      document.body.classList.remove('m9-navigating', 'm9-input-active');
      document.querySelectorAll(SHEETS).forEach(closeSheet);
      enhanceAll(); restoreExplicitNav();
    });
    media.addEventListener?.('change', () => {
      document.body.classList.remove('m9-navigating', 'm9-input-active');
      if (active()) enhanceAll();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else init();
})();
