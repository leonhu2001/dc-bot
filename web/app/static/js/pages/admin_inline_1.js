(function () {
    "use strict";

    if (window.location.pathname !== "/admin") {
        return;
    }

    const STYLE_HREF = "/static/css/pages/admin_ops_experience.css?v=20261020_1";
    const SCROLL_PREFIX = "mw-admin-scroll:";
    const SCROLL_MAX_AGE = 30 * 60 * 1000;

    function ensureStyles() {
        if (document.querySelector('link[href^="/static/css/pages/admin_ops_experience.css"]')) {
            return;
        }

        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = STYLE_HREF;
        document.head.appendChild(link);
    }

    function currentListUrl() {
        return window.location.pathname + window.location.search;
    }

    function scrollKey() {
        return SCROLL_PREFIX + currentListUrl();
    }

    function saveListPosition() {
        try {
            sessionStorage.setItem(
                scrollKey(),
                JSON.stringify({
                    y: Math.max(0, Math.round(window.scrollY || 0)),
                    at: Date.now()
                })
            );
        } catch (_error) {
            // sessionStorage can be unavailable in strict/private browser modes.
        }
    }

    function restoreListPosition() {
        let stored = null;

        try {
            stored = sessionStorage.getItem(scrollKey());
        } catch (_error) {
            return;
        }

        if (!stored) {
            return;
        }

        try {
            const parsed = JSON.parse(stored);
            const age = Date.now() - Number(parsed.at || 0);
            const y = Number(parsed.y || 0);

            if (age < 0 || age > SCROLL_MAX_AGE || !Number.isFinite(y) || y < 0) {
                sessionStorage.removeItem(scrollKey());
                return;
            }

            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    window.scrollTo(0, y);
                });
            });
        } catch (_error) {
            try {
                sessionStorage.removeItem(scrollKey());
            } catch (_ignored) {
                // Ignore storage cleanup failures.
            }
        }
    }

    function withReturnTo(rawHref) {
        if (!rawHref) {
            return "";
        }

        let url = null;

        try {
            url = new URL(rawHref, window.location.origin);
        } catch (_error) {
            return rawHref;
        }

        if (url.origin !== window.location.origin || !url.pathname.startsWith("/admin/order-workspace/")) {
            return rawHref;
        }

        url.searchParams.set("return_to", currentListUrl());
        return url.pathname + url.search + url.hash;
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

    function enhanceWorkspaceLinks() {
        document.querySelectorAll('a[href^="/admin/order-workspace/"]').forEach(function (link) {
            const href = link.getAttribute("href") || "";
            const enhanced = withReturnTo(href);

            if (enhanced) {
                link.setAttribute("href", enhanced);
            }
        });
    }

    function enhanceWorkCenter() {
        const queues = document.querySelector(".queues");

        if (!queues || queues.dataset.mwOpsEnhanced === "1") {
            return;
        }

        queues.dataset.mwOpsEnhanced = "1";
        queues.classList.add("mw-ops-work-center");

        const panels = Array.from(queues.querySelectorAll(":scope > .panel"));
        const counts = panels.map(function (panel) {
            const title = panel.querySelector(".panel-head strong");
            const count = panel.querySelector(".panel-head .count");
            return {
                title: title ? title.textContent.trim() : "待處理",
                count: count ? count.textContent.trim() : "0"
            };
        });

        const header = document.createElement("div");
        header.className = "mw-ops-center-head";

        const text = document.createElement("div");
        const kicker = document.createElement("div");
        kicker.className = "mw-ops-center-kicker";
        kicker.textContent = "ACTION CENTER";

        const heading = document.createElement("h2");
        heading.textContent = "待處理中心";

        const description = document.createElement("p");
        description.textContent = "先看需要人工介入的訂單，再進工作區完成處理；不用把整份訂單列表當監控器。";

        text.appendChild(kicker);
        text.appendChild(heading);
        text.appendChild(description);
        header.appendChild(text);

        const summary = document.createElement("div");
        summary.className = "mw-ops-center-summary";

        counts.forEach(function (item) {
            const pill = document.createElement("span");
            pill.className = "mw-ops-count-pill";

            const label = document.createElement("span");
            label.textContent = item.title;
            const value = document.createElement("strong");
            value.textContent = item.count;

            pill.appendChild(label);
            pill.appendChild(value);
            summary.appendChild(pill);
        });

        header.appendChild(summary);
        queues.parentNode.insertBefore(header, queues);

        panels.forEach(function (panel) {
            const isAttention = /需注意/.test(panel.textContent || "");

            panel.querySelectorAll(".queue-row").forEach(function (row) {
                if (row.querySelector(".mw-ops-row-action")) {
                    return;
                }

                const action = document.createElement("span");
                action.className = "mw-ops-row-action";
                action.textContent = isAttention ? "查看處理 →" : "前往確認 →";
                row.appendChild(action);
            });
        });
    }

    ensureStyles();
    enhanceWorkspaceLinks();
    enhanceWorkCenter();
    restoreListPosition();

    document.addEventListener(
        "click",
        function (event) {
            const trigger = event.target.closest(
                '[data-order-toggle], a[href^="/admin/order-workspace/"]'
            );

            if (!trigger) {
                return;
            }

            const href = withReturnTo(resolveWorkspaceHref(trigger));

            if (!href) {
                return;
            }

            saveListPosition();
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            window.location.assign(href);
        },
        true
    );
})();
