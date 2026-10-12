(() => {
    "use strict";

    // Compatibility sentinel only. The canonical order UI controller and
    // stylesheet are loaded by site_layout.html before page-specific scripts.
    // Keep this file temporarily so cached order pages can request it safely.
    window.__MAWAN_ORDER_UI_COMPAT_LOADER__ = true;
})();
