(() => {
  const nextPath = `${window.location.pathname}${window.location.search}`;
  window.location.replace(`/auth/discord/login?next=${encodeURIComponent(nextPath)}`);
})();
