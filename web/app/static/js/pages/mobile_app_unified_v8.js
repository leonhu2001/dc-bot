/*
 * Mobile V8 navigation and usability layer.
 * Enhancement only: never intercept POST/checkout, alter prices or replace
 * the existing employee/admin sheet and submit guards.
 */
(() => {
  'use strict';

  const MEDIA = window.matchMedia('(max-width: 767px)');
  const BODY_CLASS = [
    'customer-mobile-app-site', 'employee-workspace-site', 'mw-mobile-ui',
  ];
  const NAV_LINKS = [
    '.customer-app-bottom-nav a[href]',
    '.employee-app-bottom-nav a[href]',
    '.admin-app-bottom-nav a[href]',
    '.mobile-app-context-switch a[href]',
  ].join(',');
  const NAV_KEY = 'mw_mobile_nav_target_v1';
  const EDITABLE = 'input:not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea, select, [contenteditable=true]';

  function active() {
    return MEDIA.matches && BODY_CLASS.some((name) => document.body.classList.contains(name));
  }

  function isCustomerShell() {
    return document.body.classList.contains('customer-mobile-app-site');
  }

  function syncCurrentNav() {
    document.querySelectorAll(NAV_LINKS).forEach((link) => {
      if (link.classList.contains('is-active')) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    document.querySelectorAll('details.admin-app-more, details.employee-app-more').forEach((sheet) => {
      const summary = sheet.querySelector(':scope > summary');
      if (summary) {
        summary.setAttribute('aria-expanded', sheet.open ? 'true' : 'false');
        summary.setAttribute('aria-haspopup', 'dialog');
      }
    });
  }

  function markPageMovement(event) {
    if (!active() || event.defaultPrevented || event.button !== 0 ||
        event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('download') ||
        (link.target && link.target !== '_self') ||
        link.getAttribute('href').startsWith('#')) return;
    let next;
    try { next = new URL(link.href, window.location.href); } catch (_) { return; }
    if (next.origin !== window.location.origin) return;
    const current = window.location.pathname + window.location.search;
    const destination = next.pathname + next.search;
    if (destination === current) return;
    // The old admin/employee navigation helper already resets the explicit
    // bottom-nav destination. Add the missing customer variant only.
    if (isCustomerShell() && link.matches(NAV_LINKS)) {
      try { sessionStorage.setItem(NAV_KEY, destination); } catch (_) {}
    }
    document.body.classList.add('m8-navigating');
  }

  function restoreCustomerTopOnExplicitNavigation() {
    if (!active() || !isCustomerShell()) return;
    let target = '';
    try { target = sessionStorage.getItem(NAV_KEY) || ''; } catch (_) { return; }
    const current = window.location.pathname + window.location.search;
    if (target !== current && target !== window.location.pathname) return;
    try { sessionStorage.removeItem(NAV_KEY); } catch (_) {}
    requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo(0, 0)));
  }

  function focusEditingState() {
    if (!active()) return;
    document.body.classList.toggle(
      'm8-editing', !!document.activeElement?.matches?.(EDITABLE)
    );
  }

  function revealActiveFilter() {
    if (!active()) return;
    document.querySelectorAll(
      '.mobile-v6-category-strip, .report-filter-bar, .order3-categories'
    ).forEach((rail) => {
      const activeOption = rail.querySelector('.is-active, [aria-current="page"]');
      if (!activeOption) return;
      const desired = activeOption.offsetLeft - (rail.clientWidth - activeOption.clientWidth) / 2;
      if (rail.scrollWidth > rail.clientWidth) rail.scrollLeft = Math.max(0, desired);
    });
  }

  function containLargeTables() {
    if (!active()) return;
    const main = document.querySelector('main.site-main, main.mw-mobile-main-host');
    if (!main) return;
    main.querySelectorAll('table').forEach((table) => {
      if (table.closest(
        '.table-wrap, .table-responsive, .m8-table-scroll, .history-ledger-table-wrap, [data-m8-table-scroll]'
      )) return;
      // Preserve native responsive card tables. Only truly wider tables
      // get their own lateral scroll surface.
      if (table.scrollWidth <= main.clientWidth + 8) return;
      const shell = document.createElement('div');
      shell.className = 'm8-table-scroll';
      shell.tabIndex = 0;
      shell.setAttribute('role', 'region');
      shell.setAttribute('aria-label', '表格內容，可左右滑動');
      table.parentNode.insertBefore(shell, table);
      shell.appendChild(table);
    });
  }

  function showInvalidField(event) {
    if (!active()) return;
    const field = event.target;
    if (!(field instanceof HTMLElement)) return;
    field.setAttribute('aria-invalid', 'true');
    field.scrollIntoView({
      block: 'center', inline: 'nearest',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    });
  }

  function clearInvalidField(event) {
    const field = event.target;
    if (field instanceof HTMLElement && field.validity?.valid) {
      field.removeAttribute('aria-invalid');
    }
  }

  function init() {
    if (!active()) return;
    syncCurrentNav();
    restoreCustomerTopOnExplicitNavigation();
    revealActiveFilter();
    containLargeTables();
    document.addEventListener('click', (event) => {
      // Wait for another listener to cancel SPA/modal clicks.
      queueMicrotask(() => markPageMovement(event));
    });
    document.addEventListener('focusin', focusEditingState);
    document.addEventListener('focusout', () => queueMicrotask(focusEditingState));
    document.addEventListener('invalid', showInvalidField, true);
    document.addEventListener('input', clearInvalidField, true);
    document.addEventListener('change', clearInvalidField, true);
    window.addEventListener('pageshow', () => {
      document.body.classList.remove('m8-navigating', 'm8-editing');
      syncCurrentNav();
      restoreCustomerTopOnExplicitNavigation();
    });
    MEDIA.addEventListener?.('change', () => {
      document.body.classList.remove('m8-navigating', 'm8-editing');
      if (active()) { syncCurrentNav(); containLargeTables(); }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else init();
})();
