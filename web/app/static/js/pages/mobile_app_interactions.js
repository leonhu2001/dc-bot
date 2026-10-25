(() => {
  'use strict';

  const SHEET_SELECTOR = 'details.employee-app-more, details.admin-app-more';
  const INTERACTIVE_SELECTOR = 'a,button,input,select,textarea,label,summary,[role="button"]';

  function allSheets() {
    return Array.from(document.querySelectorAll(SHEET_SELECTOR));
  }

  function closeSheet(details) {
    if (!details || !details.open) return;
    details.open = false;
    const summary = details.querySelector(':scope > summary');
    if (summary) summary.setAttribute('aria-expanded', 'false');
  }

  function closeAllSheets(except = null) {
    allSheets().forEach((details) => {
      if (details !== except) closeSheet(details);
    });
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
          event.preventDefault();
          event.stopPropagation();
          closeSheet(details);
          summary?.focus({ preventScroll: true });
        });
      });

      details.querySelectorAll('.employee-app-more-panel a, .admin-app-more-panel a').forEach((link) => {
        link.addEventListener('click', () => closeSheet(details));
      });
    });
  }

  function bindEscapeAndPageRestore() {
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const openSheet = allSheets().find((details) => details.open);
      if (!openSheet) return;
      event.preventDefault();
      closeSheet(openSheet);
      openSheet.querySelector(':scope > summary')?.focus({ preventScroll: true });
    });

    window.addEventListener('pageshow', () => closeAllSheets());
  }

  function bindAdminOrderCards() {
    document.querySelectorAll('body.mw-r5-admin .mw-r5-legacy-body .order-row').forEach((row) => {
      const link = row.querySelector('a.workspace[href]');
      if (!link) return;

      row.classList.add('is-mobile-clickable');
      row.setAttribute('role', 'link');
      row.setAttribute('tabindex', '0');
      row.setAttribute('aria-label', link.title || '開啟訂單工作區');

      const open = () => {
        if (link.href) window.location.assign(link.href);
      };

      row.addEventListener('click', (event) => {
        if (event.target.closest(INTERACTIVE_SELECTOR)) return;
        open();
      });

      row.addEventListener('keydown', (event) => {
        if (event.target !== row) return;
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        open();
      });
    });
  }

  function bindPressedStateCleanup() {
    document.addEventListener('pointercancel', () => {
      document.activeElement?.blur?.();
    }, { passive: true });
  }

  function init() {
    bindSheets();
    bindEscapeAndPageRestore();
    bindAdminOrderCards();
    bindPressedStateCleanup();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
