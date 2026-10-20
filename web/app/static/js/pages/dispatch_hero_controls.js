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

    actions.append(desktop, bell);
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

  const observer = new MutationObserver(queueArrangeHero);
  observer.observe(document.body, { childList: true, subtree: true });
})();
