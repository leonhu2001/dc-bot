(() => {
  if (window.__mwDispatchHeroControlsStarted) return;
  if (window.location.pathname !== '/dispatch') return;
  window.__mwDispatchHeroControlsStarted = true;

  let syncQueued = false;

  function pulse(button) {
    if (!button) return;
    button.classList.remove('dispatch-control-tap');
    void button.offsetWidth;
    button.classList.add('dispatch-control-tap');
    window.setTimeout(() => button.classList.remove('dispatch-control-tap'), 190);
  }

  function arrangeHero() {
    const hero = document.querySelector('.dispatch-shell .dispatch-hero-main');
    if (!hero) return;

    const top = hero.querySelector(':scope > .dispatch-order-top');
    const statusRow = hero.querySelector(':scope > .dispatch-tags');
    const bell = hero.querySelector('.dispatch-alert-toggle');
    const desktop = hero.querySelector('[data-dispatch-notification-toggle]');

    if (!top || !statusRow || !bell || !desktop) return;

    let actions = top.querySelector(':scope > .dispatch-hero-actions');
    if (!actions) {
      actions = document.createElement('div');
      actions.className = 'dispatch-hero-actions';
      top.appendChild(actions);
    }

    desktop.classList.add('dispatch-primary-control');
    bell.classList.add('dispatch-primary-control');

    // Do not append already-positioned controls again. append() on an existing
    // child still removes/reinserts the node, which used to trigger the
    // MutationObserver every animation frame and could cancel native clicks.
    if (desktop.parentElement !== actions) {
      actions.appendChild(desktop);
    }
    if (bell.parentElement !== actions) {
      actions.appendChild(bell);
    }

    // Keep a stable order without touching the DOM when it is already correct.
    if (actions.firstElementChild !== desktop) {
      actions.insertBefore(desktop, actions.firstElementChild);
    }
    if (desktop.nextElementSibling !== bell) {
      actions.insertBefore(bell, desktop.nextElementSibling);
    }

    statusRow.classList.add('dispatch-status-row');
  }

  function queueArrangeHero() {
    if (syncQueued) return;
    syncQueued = true;
    window.requestAnimationFrame(() => {
      syncQueued = false;
      arrangeHero();
    });
  }

  function mutationNeedsArrange(records) {
    return records.some((record) => Array.from(record.addedNodes || []).some((node) => {
      if (!(node instanceof Element)) return false;

      if (node.matches(
        '.dispatch-shell, .dispatch-hero-main, .dispatch-alert-toggle, [data-dispatch-notification-toggle]'
      )) {
        return true;
      }

      return Boolean(node.querySelector?.(
        '.dispatch-shell, .dispatch-hero-main, .dispatch-alert-toggle, [data-dispatch-notification-toggle]'
      ));
    }));
  }

  document.addEventListener('pointerdown', (event) => {
    const target = event.target;
    if (!target || typeof target.closest !== 'function') return;

    const button = target.closest(
      '.dispatch-hero-actions .dispatch-alert-toggle, .dispatch-hero-actions [data-dispatch-notification-toggle]'
    );
    if (!button || button.disabled) return;
    pulse(button);
  }, true);

  arrangeHero();

  // The dispatch runtime replaces the entire .dispatch-shell after SSE/form
  // refreshes. Watch only for newly inserted dispatch UI, not every text-node
  // update inside the page.
  const observer = new MutationObserver((records) => {
    if (mutationNeedsArrange(records)) {
      queueArrangeHero();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();
