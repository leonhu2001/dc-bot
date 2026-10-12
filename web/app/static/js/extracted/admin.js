(function () {
    "use strict";

    if (window.location.pathname !== "/admin") {
        return;
    }

    const resolveWorkspaceHref = (trigger) => {
        if (!trigger) {
            return "";
        }

        const direct = trigger.closest('a[href^="/admin/order-workspace/"]');

        if (direct) {
            return direct.getAttribute("href") || "";
        }

        const orderRow = trigger.closest('.order[id^="order-"]');

        if (orderRow) {
            const id = String(orderRow.id || "").replace(/^order-/, "").trim();

            if (/^\d+$/.test(id)) {
                return "/admin/order-workspace/" + id;
            }

            const nested = orderRow.querySelector('a[href^="/admin/order-workspace/"]');

            if (nested) {
                return nested.getAttribute("href") || "";
            }
        }

        const holder = trigger.closest("[data-order-id]");

        if (holder) {
            const id = String(holder.dataset.orderId || "").trim();

            if (/^\d+$/.test(id)) {
                return "/admin/order-workspace/" + id;
            }
        }

        return "";
    };

    document.addEventListener(
        "click",
        function (event) {
            const trigger = event.target.closest(
                '[data-order-toggle], a[href^="/admin/order-workspace/"]'
            );

            if (!trigger) {
                return;
            }

            const href = resolveWorkspaceHref(trigger);

            if (!href) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            window.location.assign(href);
        },
        true
    );
})();
