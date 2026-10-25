(() => {
  'use strict';

  const MOBILE_QUERY = '(max-width: 767px)';
  const mobileMedia = window.matchMedia(MOBILE_QUERY);
  const SHEET_SELECTOR = 'details.employee-app-more, details.admin-app-more';
  const INTERACTIVE_SELECTOR = 'a,button,input,select,textarea,label,summary,[role="button"]';
  const NAV_TARGET_KEY = 'mw_mobile_nav_target_v1';
  const MOBILE_NAV_LINKS = [
    '.employee-app-bottom-nav a[href]',
    '.admin-app-bottom-nav a[href]',
    '.customer-app-bottom-nav a[href]',
    '.mobile-app-context-switch a[href]',
  ].join(',');

  function allSheets() { return Array.from(document.querySelectorAll(SHEET_SELECTOR)); }

  function closeSheet(details) {
    if (!details || !details.open) return;
    details.open = false;
    const summary = details.querySelector(':scope > summary');
    if (summary) summary.setAttribute('aria-expanded', 'false');
  }

  function closeAllSheets(except = null) {
    allSheets().forEach((details) => { if (details !== except) closeSheet(details); });
  }

  function bindSheets() {
    allSheets().forEach((details) => {
      const summary = details.querySelector(':scope > summary');
      if (summary) summary.setAttribute('aria-expanded', details.open ? 'true' : 'false');
      details.addEventListener('toggle', () => {
        if (summary) summary.setAttribute('aria-expanded', details.open ? 'true' : 'false');
        if (details.open) closeAllSheets(details);
      });
      details.querySelectorAll('[data-mobile-sheet-close]').forEach((control) => {
        control.addEventListener('click', (event) => {
          event.preventDefault(); event.stopPropagation(); closeSheet(details);
          summary?.focus({ preventScroll: true });
        });
      });
      details.querySelectorAll('.employee-app-more-panel a, .admin-app-more-panel a').forEach((link) => {
        link.addEventListener('click', () => closeSheet(details));
      });
    });
  }

  function consumeExplicitNavTarget() {
    if (!mobileMedia.matches) return;
    let target = '';
    try { target = sessionStorage.getItem(NAV_TARGET_KEY) || ''; } catch (_) {}
    if (!target) return;
    const current = `${location.pathname}${location.search}`;
    if (target !== current && target !== location.pathname) return;
    try { sessionStorage.removeItem(NAV_TARGET_KEY); } catch (_) {}
    requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo(0, 0)));
  }

  function bindExplicitMobileNavigation() {
    document.querySelectorAll(MOBILE_NAV_LINKS).forEach((link) => {
      if (link.dataset.mobileNavResetBound === '1') return;
      link.dataset.mobileNavResetBound = '1';
      link.addEventListener('click', () => {
        if (!mobileMedia.matches) return;
        try {
          const url = new URL(link.href, location.href);
          if (url.origin !== location.origin) return;
          sessionStorage.setItem(NAV_TARGET_KEY, `${url.pathname}${url.search}`);
        } catch (_) {}
        closeAllSheets();
      });
    });
  }

  function bindEscapeAndPageRestore() {
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const openSheet = allSheets().find((details) => details.open);
      if (!openSheet) return;
      event.preventDefault(); closeSheet(openSheet);
      openSheet.querySelector(':scope > summary')?.focus({ preventScroll: true });
    });
    window.addEventListener('pageshow', () => { closeAllSheets(); consumeExplicitNavTarget(); });
  }

  function bindAdminOrderCards() {
    document.querySelectorAll('body.mw-r5-admin .mw-r5-legacy-body .order-row').forEach((row) => {
      const link = row.querySelector('a.workspace[href]');
      if (!link || row.dataset.mobileOrderBound === '1') return;
      row.dataset.mobileOrderBound = '1';
      const syncSemantics = () => {
        if (mobileMedia.matches) {
          row.classList.add('is-mobile-clickable'); row.setAttribute('role', 'link');
          row.setAttribute('tabindex', '0'); row.setAttribute('aria-label', link.title || '開啟訂單工作區');
        } else {
          row.classList.remove('is-mobile-clickable'); row.removeAttribute('role');
          row.removeAttribute('tabindex'); row.removeAttribute('aria-label');
        }
      };
      const open = () => { if (mobileMedia.matches && link.href) window.location.assign(link.href); };
      row.addEventListener('click', (event) => {
        if (!mobileMedia.matches || event.target.closest(INTERACTIVE_SELECTOR)) return; open();
      });
      row.addEventListener('keydown', (event) => {
        if (!mobileMedia.matches || event.target !== row || (event.key !== 'Enter' && event.key !== ' ')) return;
        event.preventDefault(); open();
      });
      mobileMedia.addEventListener?.('change', syncSemantics); syncSemantics();
    });
  }

  function syncHistoryWorkspaceLinks() {
    document.querySelectorAll('.history-workspace-mobile-link').forEach((link) => link.remove());
    document.querySelectorAll('.history-ledger-action[data-mobile-action-grid="1"]').forEach((cell) => {
      cell.style.removeProperty('display'); cell.style.removeProperty('grid-template-columns');
      cell.style.removeProperty('gap'); delete cell.dataset.mobileActionGrid;
    });
    if (!mobileMedia.matches) return;
    document.querySelectorAll('body.mw-r5-admin .history-ledger-table tr:not(.history-dossier-detail-row)').forEach((row) => {
      const orderId = row.querySelector('input[type="hidden"][name="order_id"]')?.value;
      const actionCell = row.querySelector('.history-ledger-action');
      if (!orderId || !actionCell) return;
      const link = document.createElement('a');
      link.className = 'button secondary history-workspace-mobile-link';
      link.href = `/admin/order-workspace/${encodeURIComponent(orderId)}`; link.textContent = '開啟訂單';
      link.style.display = 'flex'; link.style.width = '100%'; link.style.minHeight = '44px';
      link.style.alignItems = 'center'; link.style.justifyContent = 'center'; link.style.textDecoration = 'none';
      actionCell.dataset.mobileActionGrid = '1'; actionCell.style.display = 'grid';
      actionCell.style.gridTemplateColumns = '1fr 1fr'; actionCell.style.gap = '7px'; actionCell.appendChild(link);
    });
  }

  function bindResponsiveEnhancements() {
    syncHistoryWorkspaceLinks();
    mobileMedia.addEventListener?.('change', () => { closeAllSheets(); syncHistoryWorkspaceLinks(); });
  }

  function bindPressedStateCleanup() {
    document.addEventListener('pointercancel', () => { document.activeElement?.blur?.(); }, { passive: true });
  }

  function init() {
    bindSheets(); bindExplicitMobileNavigation(); consumeExplicitNavTarget();
    bindEscapeAndPageRestore(); bindAdminOrderCards(); bindResponsiveEnhancements(); bindPressedStateCleanup();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
