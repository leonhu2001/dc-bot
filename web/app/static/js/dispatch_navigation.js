(function () {
  "use strict";

  const selector = '.dispatch-support-duty a[href="/admin"]';

  function prepareLinks() {
    document.querySelectorAll(selector).forEach((link) => {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    });
  }

  document.addEventListener(
    "click",
    function (event) {
      const target = event.target instanceof Element ? event.target : null;
      const link = target?.closest(selector);

      if (!link) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();

      window.open(link.href, "_blank", "noopener,noreferrer");
    },
    true
  );

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", prepareLinks, { once: true });
  } else {
    prepareLinks();
  }
})();
