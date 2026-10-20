(function () {
    "use strict";

    function ensureToolbarStyles() {
        if (document.querySelector('link[href^="/static/css/pages/admin_order_workspace_toolbar.css"]')) {
            return;
        }

        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "/static/css/pages/admin_order_workspace_toolbar.css?v=20261020_1";
        document.head.appendChild(link);
    }

    function polishToolbar() {
        const bar = document.querySelector(".mw-ops-sticky-bar");
        if (!bar) {
            return;
        }

        const groups = bar.querySelectorAll(":scope > .mw-ops-sticky-actions");
        const left = groups[0];
        const right = groups[1];

        if (left) {
            const copy = left.querySelector("[data-copy]");
            if (copy) {
                copy.classList.add("mw-ops-copy-action");
                copy.title = "複製票口 Channel ID";
            }
        }

        if (right) {
            const finance = right.querySelector('a[href="#mw-ops-finance"]');
            const audit = right.querySelector('a[href^="/admin/audit?target="]');
            if (finance) {
                if (audit) {
                    right.insertBefore(finance, audit);
                } else {
                    right.appendChild(finance);
                }
            }
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        ensureToolbarStyles();
        polishToolbar();
    });
})();
