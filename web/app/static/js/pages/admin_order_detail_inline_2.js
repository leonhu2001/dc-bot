(function () {
    "use strict";

    function refreshOpsStyles() {
        const link = document.querySelector('link[href^="/static/css/pages/admin_ops_experience.css"]');
        if (link) {
            link.setAttribute("href", "/static/css/pages/admin_ops_experience.css?v=20261020_3");
        }
    }

    function normalizedText(node) {
        return node ? String(node.textContent || "").replace(/\s+/g, " ").trim() : "";
    }

    function moneyValue(value) {
        const match = String(value || "")
            .replace(/,/g, "")
            .match(/-?\d+(?:\.\d+)?/);

        if (!match) {
            return 0;
        }

        const parsed = Number(match[0]);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function moneyText(value) {
        const number = Number(value || 0);
        return Math.round(number).toLocaleString("zh-TW") + "T";
    }

    function findCellValue(label) {
        const cells = Array.from(document.querySelectorAll("main.page .cell"));
        const cell = cells.find(function (candidate) {
            return normalizedText(candidate.querySelector(".label")) === label;
        });
        return cell ? normalizedText(cell.querySelector(".value")) : "";
    }

    function payoutRows(label) {
        return Array.from(document.querySelectorAll(".mw-r8-person-row"))
            .map(function (row) {
                const moneyBox = row.querySelector(".mw-r8-person-money");
                if (!moneyBox || normalizedText(moneyBox).indexOf(label) === -1) {
                    return null;
                }

                const name = normalizedText(row.querySelector(".mw-r8-person-name strong")) || "未命名人員";
                const strong = moneyBox.querySelector("strong");

                return {
                    name: name,
                    amount: moneyValue(normalizedText(strong))
                };
            })
            .filter(Boolean);
    }

    function sumRows(rows) {
        return rows.reduce(function (total, row) {
            return total + Number(row.amount || 0);
        }, 0);
    }

    function metric(label, value, hint, tone) {
        const item = document.createElement("div");
        item.className = "mw-ops-finance-metric" + (tone ? " " + tone : "");

        const labelNode = document.createElement("span");
        labelNode.textContent = label;

        const valueNode = document.createElement("strong");
        valueNode.textContent = value;

        item.appendChild(labelNode);
        item.appendChild(valueNode);

        if (hint) {
            const small = document.createElement("small");
            small.textContent = hint;
            item.appendChild(small);
        }

        return item;
    }

    function notice(text, tone) {
        const item = document.createElement("div");
        item.className = "mw-ops-finance-notice " + (tone || "info");
        item.textContent = text;
        return item;
    }

    function personRow(label, rows) {
        if (!rows.length) {
            return null;
        }

        const block = document.createElement("div");
        block.className = "mw-ops-finance-people";

        const heading = document.createElement("strong");
        heading.textContent = label;
        block.appendChild(heading);

        const list = document.createElement("div");
        list.className = "mw-ops-finance-people-list";

        rows.forEach(function (row) {
            const item = document.createElement("div");

            const name = document.createElement("span");
            name.textContent = row.name;

            const amount = document.createElement("strong");
            amount.textContent = moneyText(row.amount);

            item.appendChild(name);
            item.appendChild(amount);
            list.appendChild(item);
        });

        block.appendChild(list);
        return block;
    }

    function setupFinanceBreakdown() {
        const layoutSection = document.querySelector("main.page .layout > section");
        const firstCard = layoutSection ? layoutSection.querySelector(":scope > .card") : null;

        if (!layoutSection || !firstCard || document.getElementById("mw-ops-finance")) {
            return;
        }

        const orderAmount = moneyValue(findCellValue("訂單金額"));
        const customerPay = moneyValue(findCellValue("顧客實付"));
        const storeAbsorbed = moneyValue(findCellValue("店家吸收"));
        const historicalDiscount = moneyValue(findCellValue("歷史折扣"));
        const payoutBase = moneyValue(findCellValue("分潤基礎"));
        const orderStatus = findCellValue("狀態");

        const workerRows = payoutRows("目前實拿");
        const customerServiceRows = payoutRows("客服分潤");
        const workerTotal = sumRows(workerRows);
        const customerServiceTotal = sumRows(customerServiceRows);
        const payoutTotal = workerTotal + customerServiceTotal;
        const shopRemainder = customerPay - payoutTotal;
        const payDifference = orderAmount - customerPay;
        const payoutGap = payoutBase - customerPay;

        const card = document.createElement("section");
        card.id = "mw-ops-finance";
        card.className = "card mw-ops-finance-card mw-ops-anchor-target";

        const head = document.createElement("div");
        head.className = "mw-ops-finance-head";

        const titleWrap = document.createElement("div");
        const kicker = document.createElement("div");
        kicker.className = "mw-ops-center-kicker";
        kicker.textContent = "MONEY EXPLAINER";
        const title = document.createElement("h2");
        title.textContent = "金額／薪資拆解";
        const subtitle = document.createElement("p");
        subtitle.textContent = "只讀取這張單目前已存在的金額與分潤紀錄，不重新計價、不重算薪資。";

        titleWrap.appendChild(kicker);
        titleWrap.appendChild(title);
        titleWrap.appendChild(subtitle);
        head.appendChild(titleWrap);
        card.appendChild(head);

        const grid = document.createElement("div");
        grid.className = "mw-ops-finance-grid";
        grid.appendChild(metric("訂單金額", moneyText(orderAmount), "現有訂單 amount", ""));
        grid.appendChild(metric("顧客實付", moneyText(customerPay), "目前 customer pay", ""));
        grid.appendChild(metric("實付差額", moneyText(payDifference), "訂單金額 − 顧客實付；不猜折扣來源", payDifference > 0 ? "warning" : ""));
        grid.appendChild(metric("店家吸收", moneyText(storeAbsorbed), "現有店家吸收欄位", storeAbsorbed > 0 ? "warning" : ""));
        grid.appendChild(metric("歷史折扣", moneyText(historicalDiscount), "歷史資料欄位", historicalDiscount > 0 ? "warning" : ""));
        grid.appendChild(metric("分潤基礎", moneyText(payoutBase), "陪玩分潤使用的現有基礎金額", payoutGap > 0 ? "warning" : ""));
        grid.appendChild(metric("陪玩實拿合計", moneyText(workerTotal), workerRows.length + " 位目前已產生分潤", ""));
        grid.appendChild(metric("客服分潤合計", moneyText(customerServiceTotal), customerServiceRows.length + " 筆目前已產生分潤", ""));
        grid.appendChild(metric(
            "店家帳面剩餘",
            moneyText(shopRemainder),
            "顧客實付 − 目前已產生陪玩分潤 − 目前已產生客服分潤",
            shopRemainder < 0 ? "danger" : "success"
        ));
        card.appendChild(grid);

        const notices = document.createElement("div");
        notices.className = "mw-ops-finance-notices";

        if (shopRemainder < 0) {
            notices.appendChild(notice(
                "⚠ 目前已產生的陪玩／客服分潤合計高於顧客實付 " + moneyText(Math.abs(shopRemainder)) + "。這只是警示，不會自動改任何分潤。",
                "danger"
            ));
        }

        if (payoutGap > 0) {
            notices.appendChild(notice(
                "分潤基礎比顧客實付高 " + moneyText(payoutGap) + "，會壓縮這張單的店家帳面剩餘；請核對既有折扣／補貼設定。",
                "warning"
            ));
        }

        if (payDifference !== 0) {
            notices.appendChild(notice(
                "訂單金額與顧客實付相差 " + moneyText(Math.abs(payDifference)) + "。目前頁面未直接提供所有折扣／券種細項，所以這裡不自行拆來源。",
                "info"
            ));
        }

        if (!workerRows.length && !customerServiceRows.length) {
            notices.appendChild(notice(
                "目前尚未產生陪玩或客服分潤紀錄；帳面剩餘會先等於顧客實付，不代表最終店家收入。",
                "info"
            ));
        }

        if (orderStatus === "已取消" && payoutTotal > 0) {
            notices.appendChild(notice(
                "此單已取消但頁面仍有分潤紀錄。這裡只顯示現況，是否作廢仍依既有帳務流程處理。",
                "warning"
            ));
        }

        if (notices.children.length) {
            card.appendChild(notices);
        }

        const people = document.createElement("div");
        people.className = "mw-ops-finance-people-grid";
        const workersBlock = personRow("陪玩目前實拿", workerRows);
        const csBlock = personRow("客服目前分潤", customerServiceRows);
        if (workersBlock) {
            people.appendChild(workersBlock);
        }
        if (csBlock) {
            people.appendChild(csBlock);
        }
        if (people.children.length) {
            card.appendChild(people);
        }

        firstCard.insertAdjacentElement("afterend", card);

        const stickyActions = document.querySelector(".mw-ops-sticky-bar .mw-ops-sticky-actions:last-child");
        if (stickyActions && !stickyActions.querySelector('a[href="#mw-ops-finance"]')) {
            const link = document.createElement("a");
            link.className = "mw-ops-action";
            link.href = "#mw-ops-finance";
            link.textContent = "金額拆解";
            stickyActions.insertBefore(link, stickyActions.firstChild);
        }
    }

    function setupUnifiedToolbar() {
        const oldCopy = document.querySelector(".mw-admin-inline-actions [data-copy]");
        const ticketId = oldCopy ? String(oldCopy.getAttribute("data-copy") || "").trim() : "";
        const leftActions = document.querySelector(".mw-ops-sticky-bar .mw-ops-sticky-actions:first-child");

        if (ticketId && leftActions && !leftActions.querySelector('[data-copy="' + CSS.escape(ticketId) + '"]')) {
            const copyButton = document.createElement("button");
            copyButton.type = "button";
            copyButton.className = "mw-ops-action";
            copyButton.setAttribute("data-copy", ticketId);
            copyButton.textContent = "複製票口 ID";
            leftActions.appendChild(copyButton);
        }

        document.querySelectorAll(".mw-admin-backbar, .mw-admin-inline-actions").forEach(function (node) {
            node.remove();
        });
    }

    function simplifyPayoutPolicyCopy() {
        const candidates = document.querySelectorAll("main.page p, main.page span, main.page small");
        candidates.forEach(function (node) {
            if (node.children.length) {
                return;
            }
            let text = normalizedText(node);
            if (!text) {
                return;
            }

            text = text
                .replace("管理端修正掛名（新制 +3%；舊單依原制度）", "管理端修正掛名（+3%）")
                .replace("管理端修正直播（新制 +2%）", "管理端修正直播（+2%）")
                .replace("需新制且報單審核通過", "需報單審核通過")
                .replace("新制為基礎 80%", "基礎 80%")
                .replace("；舊單保留原制度。", "。");

            if (text !== normalizedText(node)) {
                node.textContent = text;
            }
        });
    }

    const AUDIT_ACTION_LABELS = {
        order_report_submitted: "報單送審",
        order_report_approved: "報單審核通過",
        order_report_changes_requested: "報單退回補件",
        order_report_updated: "報單內容更新",
        order_updated: "訂單資料更新",
        order_status_updated: "訂單狀態更新",
        order_closed: "訂單結單",
        order_cancelled: "訂單取消",
        worker_payout_override: "陪玩分潤調整"
    };

    function friendlyAuditTitle(value) {
        const raw = String(value || "").trim();
        if (AUDIT_ACTION_LABELS[raw]) {
            return AUDIT_ACTION_LABELS[raw];
        }
        if (/^[a-z0-9_]+$/i.test(raw) && raw.indexOf("_") !== -1) {
            return "後台操作紀錄";
        }
        return raw || "操作紀錄";
    }

    function friendlyAuditDetail(action, value) {
        const raw = String(value || "").trim();
        if (!raw) {
            return "";
        }

        const parts = raw.split("｜");
        const operator = parts.length && parts[0].indexOf("操作人員：") === 0
            ? parts.shift()
            : "";
        const change = parts.join("｜").trim();
        let summary = change;

        if (action === "order_report_approved") {
            summary = "報單狀態：待審核 → 已通過；審核後的掛名／直播等分潤條件已套用。";
        } else if (action === "order_report_changes_requested") {
            summary = "報單已退回補件，等待陪玩修正後重新送審。";
        } else if (action === "order_report_submitted") {
            summary = "報單已送出，等待客服審核。";
        } else if (
            change.length > 180
            || change.indexOf("{'id':") !== -1
            || change.indexOf('{"id":') !== -1
            || (change.indexOf("{") !== -1 && change.indexOf("}") !== -1 && change.indexOf("->") !== -1)
        ) {
            summary = "欄位變更已記錄；詳細內容請至「完整操作紀錄」查看。";
        }

        return [operator, summary].filter(Boolean).join("｜");
    }

    function sanitizeTimelineItems() {
        document.querySelectorAll(".mw-ops-timeline-foot").forEach(function (node) {
            node.remove();
        });

        document.querySelectorAll(".mw-ops-timeline-item").forEach(function (item) {
            if (item.dataset.mwTimelineClean === "1") {
                return;
            }

            const title = item.querySelector(".mw-ops-timeline-body > strong");
            const detail = item.querySelector(".mw-ops-timeline-body > small");
            const rawAction = normalizedText(title);

            if (title) {
                title.textContent = friendlyAuditTitle(rawAction);
            }
            if (detail) {
                detail.textContent = friendlyAuditDetail(rawAction, detail.textContent);
            }
            item.dataset.mwTimelineClean = "1";
        });
    }

    function setupTimelineSanitizer() {
        sanitizeTimelineItems();
        const root = document.querySelector("main.page") || document.body;
        if (!root || root.dataset.mwTimelineObserver === "1") {
            return;
        }
        root.dataset.mwTimelineObserver = "1";

        const observer = new MutationObserver(function () {
            sanitizeTimelineItems();
        });
        observer.observe(root, { childList: true, subtree: true });
    }

    document.addEventListener("click", function (event) {
        const button = event.target.closest("[data-copy]");

        if (!button) {
            return;
        }

        const value = button.getAttribute("data-copy");

        if (!value || !navigator.clipboard) {
            return;
        }

        navigator.clipboard.writeText(value).then(function () {
            const oldText = button.textContent;
            button.textContent = "已複製";

            setTimeout(function () {
                button.textContent = oldText;
            }, 1200);
        });
    });

    document.addEventListener("DOMContentLoaded", function () {
        refreshOpsStyles();
        setupFinanceBreakdown();
        setupUnifiedToolbar();
        simplifyPayoutPolicyCopy();
        setupTimelineSanitizer();
    });
})();
