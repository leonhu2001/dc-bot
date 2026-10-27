(function () {
    "use strict";

    if (window.location.pathname !== "/admin") {
        return;
    }

    const STATUS_UI = {
        missing: { label: "未報單", className: "unreported" },
        pending: { label: "待審核", className: "pending" },
        approved: { label: "已報單", className: "reported" },
        changes_requested: { label: "已退回", className: "pending" }
    };

    function applyStatus(badge, status) {
        const normalized = Object.prototype.hasOwnProperty.call(STATUS_UI, status)
            ? status
            : "missing";
        const ui = STATUS_UI[normalized];

        badge.dataset.reportStatus = normalized;
        badge.classList.remove("unreported", "pending", "reported", "rejected");
        badge.classList.add(ui.className);
        badge.textContent = ui.label;
    }

    async function syncStatuses() {
        const badges = Array.from(
            document.querySelectorAll("[data-admin-order-report-status][data-order-id]")
        );

        const targets = badges
            .map(function (badge) {
                return {
                    badge: badge,
                    id: String(badge.dataset.orderId || "").trim()
                };
            })
            .filter(function (target) {
                return /^\d+$/.test(target.id);
            });

        if (!targets.length) {
            return;
        }

        const ids = Array.from(new Set(targets.map(function (target) {
            return target.id;
        })));

        try {
            const response = await fetch(
                "/dispatch/reports/statuses.json?order_ids=" + encodeURIComponent(ids.join(",")),
                {
                    credentials: "same-origin",
                    headers: { "Accept": "application/json" },
                    cache: "no-store"
                }
            );

            if (!response.ok) {
                throw new Error("report status request failed: " + response.status);
            }

            const payload = await response.json();
            const statuses = payload && payload.statuses ? payload.statuses : {};

            targets.forEach(function (target) {
                applyStatus(target.badge, String(statuses[target.id] || "missing"));
            });
        } catch (error) {
            console.warn("[admin-dashboard-report-status] sync failed", error);
        }
    }

    syncStatuses();
})();
