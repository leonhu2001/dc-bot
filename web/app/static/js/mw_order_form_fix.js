(() => {
    "use strict";

    if (window.__MAWAN_ORDER_UI_COMPAT_LOADER__) {
        return;
    }
    window.__MAWAN_ORDER_UI_COMPAT_LOADER__ = true;

    // mw_order_guard.js checks this id before injecting its historical inline
    // style block. The canonical stylesheet now contains those rules, so using
    // the shared id retires that runtime CSP dependency without changing the
    // eligibility logic itself.
    const cssId = "mw-role-filter-style";
    if (!document.getElementById(cssId)) {
        const link = document.createElement("link");
        link.id = cssId;
        link.rel = "stylesheet";
        link.href = "/static/css/order_ui.css?v=20261013-2";
        document.head.appendChild(link);
    }

    if (!window.__MAWAN_ORDER_UI__) {
        const script = document.createElement("script");
        script.src = "/static/js/mw_order_ui.js?v=20261013";
        script.async = false;
        document.head.appendChild(script);
    }
})();
