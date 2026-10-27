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

    function queueMeta(panel) {
        const titleNode = panel.querySelector(".panel-head strong");
        const rawTitle = titleNode ? titleNode.textContent.trim() : "待處理";
        const countNode = panel.querySelector(".panel-head .count");
        const count = countNode ? countNode.textContent.trim() : "0";

        if (/需注意/.test(rawTitle)) {
            return {
                priority: 0,
                priorityLabel: "P0",
                title: "需注意訂單",
                count: count,
                action: "立即處理 →"
            };
        }

        if (/待客服確認/.test(rawTitle)) {
            return {
                priority: 1,
                priorityLabel: "P1",
                title: "待客服確認",
                count: count,
                action: "前往確認 →"
            };
        }

        return {
            priority: 9,
            priorityLabel: "",
            title: rawTitle,
            count: count,
            action: "查看處理 →"
        };
    }

    function enhanceWorkCenter() {
        const queues = document.querySelector(".queues");

        if (!queues || queues.dataset.mwOpsEnhanced === "1") {
            return;
        }

        queues.dataset.mwOpsEnhanced = "1";
        queues.classList.add("mw-ops-work-center");

        const rankedPanels = Array.from(queues.querySelectorAll(":scope > .panel"))
            .map(function (panel) {
                return { panel: panel, meta: queueMeta(panel) };
            })
            .sort(function (left, right) {
                return left.meta.priority - right.meta.priority;
            });

        rankedPanels.forEach(function (entry) {
            queues.appendChild(entry.panel);
            const title = entry.panel.querySelector(".panel-head strong");
            if (title && entry.meta.priorityLabel) {
                title.textContent = entry.meta.priorityLabel + " · " + entry.meta.title;
            }
            entry.panel.dataset.mwOpsPriority = entry.meta.priorityLabel || "normal";
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
        description.textContent = "P0 是需要立即人工介入；P1 是待客服確認。等待接單、等待付款、進行中的訂單維持流程追蹤，不會因狀態本身被列成人工待辦。";

        text.appendChild(kicker);
        text.appendChild(heading);
        text.appendChild(description);
        header.appendChild(text);

        const summary = document.createElement("div");
        summary.className = "mw-ops-center-summary";

        rankedPanels.forEach(function (entry) {
            const pill = document.createElement("span");
            pill.className = "mw-ops-count-pill";

            const label = document.createElement("span");
            label.textContent = (
                entry.meta.priorityLabel
                    ? entry.meta.priorityLabel + " " + entry.meta.title
                    : entry.meta.title
            );
            const value = document.createElement("strong");
            value.textContent = entry.meta.count;

            pill.appendChild(label);
            pill.appendChild(value);
            summary.appendChild(pill);
        });

        header.appendChild(summary);
        queues.parentNode.insertBefore(header, queues);

        rankedPanels.forEach(function (entry) {
            entry.panel.querySelectorAll(".queue-row").forEach(function (row) {
                if (row.querySelector(".mw-ops-row-action")) {
                    return;
                }

                const action = document.createElement("span");
                action.className = "mw-ops-row-action";
                action.textContent = entry.meta.action;
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