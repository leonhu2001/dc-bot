// MAWAN_R13_FINAL_DATE_AUTOFILL + ADMIN_OPS_EXPERIENCE_PHASE1
(function () {
    "use strict";

    const STYLE_HREF = "/static/css/pages/admin_ops_experience.css?v=20261020_1";

    function ensureStyles() {
        if (document.querySelector('link[href^="/static/css/pages/admin_ops_experience.css"]')) {
            return;
        }

        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = STYLE_HREF;
        document.head.appendChild(link);
    }

    function taipeiDate() {
        const parts = new Intl.DateTimeFormat("en-US", {
            timeZone: "Asia/Taipei",
            year: "numeric",
            month: "2-digit",
            day: "2-digit"
        }).formatToParts(new Date());
        const values = {};
        parts.forEach(function (part) {
            values[part.type] = part.value;
        });
        return values.year + "-" + values.month + "-" + values.day;
    }

    function setupFinalDate() {
        const statusSelect = document.querySelector('select[name="status"]');
        const dateInput = document.querySelector('input[name="closed_date"]');
        const autoInput = document.querySelector('input[name="closed_date_auto"]');
        const touchedInput = document.querySelector('input[name="closed_date_touched"]');
        const cancellationFields = document.getElementById("mw-cancellation-reason-fields");

        if (!statusSelect || !dateInput || !autoInput || !touchedInput) {
            return;
        }

        function syncFinalDate() {
            const isFinal = statusSelect.value === "closed" || statusSelect.value === "cancelled";
            if (cancellationFields) {
                cancellationFields.hidden = statusSelect.value !== "cancelled";
            }
            if (isFinal && !dateInput.value) {
                dateInput.value = taipeiDate();
                autoInput.value = "1";
            } else if (!isFinal && autoInput.value === "1") {
                dateInput.value = "";
                autoInput.value = "";
            }
        }

        statusSelect.addEventListener("change", syncFinalDate);
        dateInput.addEventListener("input", function () {
            autoInput.value = "";
            touchedInput.value = "1";
        });
        syncFinalDate();
    }

    function normalizedText(node) {
        return node ? String(node.textContent || "").replace(/\s+/g, " ").trim() : "";
    }

    function findCellValue(label) {
        const cells = Array.from(document.querySelectorAll(".cell"));
        const cell = cells.find(function (candidate) {
            return normalizedText(candidate.querySelector(".label")) === label;
        });
        return cell ? normalizedText(cell.querySelector(".value")) : "";
    }

    function findEditorCard(headingText) {
        const cards = Array.from(document.querySelectorAll(".mw-r8-editor-card"));
        return cards.find(function (card) {
            const heading = card.querySelector("h2, h3");
            return normalizedText(heading).indexOf(headingText) !== -1;
        }) || null;
    }

    function setupAnchors() {
        const targets = [
            ["訂單資料編輯", "mw-ops-order-edit"],
            ["需注意訂單", "mw-ops-attention"],
            ["接單人員與分潤", "mw-ops-assignments"],
            ["內部備註", "mw-ops-note"]
        ];

        targets.forEach(function (item) {
            const card = findEditorCard(item[0]);
            if (card) {
                card.id = item[1];
                card.classList.add("mw-ops-anchor-target");
            }
        });
    }

    function safeReturnTo() {
        const value = new URLSearchParams(window.location.search).get("return_to") || "";
        if (value === "/admin" || value.startsWith("/admin?") || value.startsWith("/admin/")) {
            return value;
        }
        return "/admin";
    }

    function orderIdFromPath() {
        const match = window.location.pathname.match(/^\/admin\/order-workspace\/(\d+)\/?$/);
        return match ? match[1] : "";
    }

    function makeAction(label, href, primary) {
        const link = document.createElement("a");
        link.className = "mw-ops-action" + (primary ? " primary" : "");
        link.href = href;
        link.textContent = label;
        return link;
    }

    function setupStickyBar(orderId) {
        const main = document.querySelector("main.page");
        const layout = main ? main.querySelector(".layout") : null;
        if (!main || !layout || document.querySelector(".mw-ops-sticky-bar")) {
            return;
        }

        const bar = document.createElement("nav");
        bar.className = "mw-ops-sticky-bar";
        bar.setAttribute("aria-label", "訂單快速操作");

        const left = document.createElement("div");
        left.className = "mw-ops-sticky-actions";
        left.appendChild(makeAction("← 返回原列表", safeReturnTo(), false));
        bar.appendChild(left);

        const actions = document.createElement("div");
        actions.className = "mw-ops-sticky-actions";

        if (document.getElementById("mw-ops-order-edit")) {
            actions.appendChild(makeAction("訂單資料", "#mw-ops-order-edit", false));
        }
        if (document.getElementById("mw-ops-attention")) {
            actions.appendChild(makeAction("注意標記", "#mw-ops-attention", false));
        }
        if (document.getElementById("mw-ops-assignments")) {
            actions.appendChild(makeAction("接單／分潤", "#mw-ops-assignments", false));
        }
        if (orderId) {
            actions.appendChild(makeAction("完整操作紀錄", "/admin/audit?target=" + encodeURIComponent(orderId), false));
        }

        bar.appendChild(actions);
        main.insertBefore(bar, layout);
    }

    function resolveNextStep() {
        const status = findCellValue("狀態");
        const attentionNotice = Array.from(document.querySelectorAll(".notice.error")).find(function (notice) {
            return normalizedText(notice).indexOf("此訂單已標記為需注意") !== -1;
        });
        const acceptanceLine = Array.from(document.querySelectorAll(".mw-r8-meta")).find(function (node) {
            return normalizedText(node).indexOf("付款前接單進度") !== -1;
        });
        const acceptanceText = normalizedText(acceptanceLine);

        if (attentionNotice) {
            const reason = normalizedText(attentionNotice).replace(/^此訂單已標記為需注意\s*[·・]?\s*/, "");
            return {
                tone: "danger",
                title: "需要客服注意",
                description: reason || "這張訂單已被標記為需注意，請確認原因並完成後續處理。",
                actionLabel: "處理注意事項",
                actionHref: "#mw-ops-attention"
            };
        }

        if (status === "待客服確認" || status === "已建立") {
            return {
                tone: "warning",
                title: "需要客服處理",
                description: "此訂單目前等待客服確認。先確認訂單資料、客服與狀態，再進入後續流程。",
                actionLabel: "前往處理",
                actionHref: "#mw-ops-order-edit"
            };
        }

        if (status === "等待接單") {
            if (acceptanceText.indexOf("已滿員") !== -1) {
                return {
                    tone: "active",
                    title: "接單人員已到齊",
                    description: acceptanceText + "。請依既有流程確認下一個狀態，不會由前端自動改單。",
                    actionLabel: "查看接單人員",
                    actionHref: "#mw-ops-assignments"
                };
            }
            return {
                tone: "warning",
                title: "等待陪玩接單",
                description: acceptanceText || "目前正在等待接單；若沒有異常，客服不需要手動改動訂單。",
                actionLabel: "查看接單進度",
                actionHref: "#mw-ops-assignments"
            };
        }

        if (status === "等待付款") {
            return {
                tone: "warning",
                title: "等待付款",
                description: "接單階段已完成，目前等待既有付款流程確認；前端不會預先顯示付款成功。",
                actionLabel: "查看訂單資料",
                actionHref: "#mw-ops-order-edit"
            };
        }

        if (status === "進行中" || status === "已付款") {
            return {
                tone: "active",
                title: "服務進行中",
                description: "目前沒有系統要求的客服動作；需要調整時再使用下方訂單與接單工具。",
                actionLabel: "查看接單／分潤",
                actionHref: "#mw-ops-assignments"
            };
        }

        if (status === "已暫存" || status === "存單") {
            return {
                tone: "warning",
                title: "訂單已暫存",
                description: "這張單目前維持暫存狀態；需要恢復處理時，再從訂單資料調整。",
                actionLabel: "查看訂單資料",
                actionHref: "#mw-ops-order-edit"
            };
        }

        if (status === "已完成" || status === "已結單") {
            return {
                tone: "success",
                title: "服務已完成",
                description: "訂單已進入完成／結案狀態，可直接查看接單與分潤紀錄，不需要再次變更狀態。",
                actionLabel: "查看分潤明細",
                actionHref: "#mw-ops-assignments"
            };
        }

        if (status === "已取消") {
            return {
                tone: "success",
                title: "訂單已取消",
                description: "這張單已結束。需要追查原因或修改紀錄時，請使用操作紀錄。",
                actionLabel: "查看訂單資料",
                actionHref: "#mw-ops-order-edit"
            };
        }

        return {
            tone: "active",
            title: status ? "目前狀態：" + status : "訂單狀態待確認",
            description: "依下方既有工具處理；這個提示只整理現有狀態，不會新增或自動變更店內規則。",
            actionLabel: "查看訂單資料",
            actionHref: "#mw-ops-order-edit"
        };
    }

    function setupNextStepCard() {
        const main = document.querySelector("main.page");
        const layout = main ? main.querySelector(".layout") : null;
        if (!main || !layout || document.querySelector(".mw-ops-next-step")) {
            return;
        }

        const state = resolveNextStep();
        const card = document.createElement("section");
        card.className = "mw-ops-next-step";
        card.dataset.tone = state.tone;

        const content = document.createElement("div");
        const kicker = document.createElement("div");
        kicker.className = "mw-ops-center-kicker";
        kicker.textContent = "NEXT ACTION";

        const titleRow = document.createElement("div");
        titleRow.className = "mw-ops-next-step-title";
        const dot = document.createElement("span");
        dot.className = "mw-ops-next-step-dot";
        const title = document.createElement("h2");
        title.textContent = state.title;
        titleRow.appendChild(dot);
        titleRow.appendChild(title);

        const description = document.createElement("p");
        description.textContent = state.description;

        content.appendChild(kicker);
        content.appendChild(titleRow);
        content.appendChild(description);
        card.appendChild(content);

        const actions = document.createElement("div");
        actions.className = "mw-ops-next-step-actions";
        if (document.querySelector(state.actionHref)) {
            actions.appendChild(makeAction(state.actionLabel, state.actionHref, true));
        }
        card.appendChild(actions);

        main.insertBefore(card, layout);
    }

    function setNoticeRoles() {
        document.querySelectorAll(".notice").forEach(function (notice) {
            const isError = notice.classList.contains("error");
            notice.setAttribute("role", isError ? "alert" : "status");
            notice.setAttribute("aria-live", isError ? "assertive" : "polite");
        });
    }

    function resetSubmittingForms() {
        document.querySelectorAll("form.mw-ops-submitting").forEach(function (form) {
            form.classList.remove("mw-ops-submitting");
            form.removeAttribute("aria-busy");
            form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (button) {
                button.disabled = false;
                button.classList.remove("mw-ops-loading");
                if (button.dataset.mwOpsOriginalText) {
                    if (button.tagName === "INPUT") {
                        button.value = button.dataset.mwOpsOriginalText;
                    } else {
                        button.textContent = button.dataset.mwOpsOriginalText;
                    }
                    delete button.dataset.mwOpsOriginalText;
                }
            });
        });
    }

    function setupSubmitFeedback() {
        document.querySelectorAll('form[action^="/admin/order-workspace/"]').forEach(function (form) {
            if (form.dataset.mwOpsSubmitBound === "1") {
                return;
            }
            form.dataset.mwOpsSubmitBound = "1";

            form.addEventListener("submit", function (event) {
                if (event.defaultPrevented) {
                    return;
                }

                const submitter = event.submitter || form.querySelector('button[type="submit"], input[type="submit"]');
                form.classList.add("mw-ops-submitting");
                form.setAttribute("aria-busy", "true");

                form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (button) {
                    if (!button.dataset.mwOpsOriginalText) {
                        button.dataset.mwOpsOriginalText = button.tagName === "INPUT"
                            ? String(button.value || "")
                            : normalizedText(button);
                    }
                    button.disabled = true;
                });

                if (submitter) {
                    submitter.classList.add("mw-ops-loading");
                    if (submitter.tagName === "INPUT") {
                        submitter.value = "處理中…";
                    } else {
                        submitter.textContent = "處理中…";
                    }
                }
            });
        });

        window.addEventListener("pageshow", function (event) {
            if (event.persisted) {
                resetSubmittingForms();
            }
        });
    }

    function makeTimelineItem(time, title, detail) {
        const item = document.createElement("div");
        item.className = "mw-ops-timeline-item";

        const timeNode = document.createElement("div");
        timeNode.className = "mw-ops-timeline-time";
        timeNode.textContent = time || "—";

        const marker = document.createElement("span");
        marker.className = "mw-ops-timeline-node";

        const body = document.createElement("div");
        body.className = "mw-ops-timeline-body";
        const strong = document.createElement("strong");
        strong.textContent = title || "操作紀錄";
        body.appendChild(strong);
        if (detail) {
            const small = document.createElement("small");
            small.textContent = detail;
            body.appendChild(small);
        }

        item.appendChild(timeNode);
        item.appendChild(marker);
        item.appendChild(body);
        return item;
    }

    function auditCardValue(card, label) {
        const groups = Array.from(card.querySelectorAll(".order-meta > div"));
        const group = groups.find(function (node) {
            const span = node.querySelector(":scope > span");
            return normalizedText(span) === label;
        });
        return group ? normalizedText(group.querySelector("strong")) : "";
    }

    async function loadAuditTimeline(orderId, list, loading) {
        try {
            const response = await fetch("/admin/audit?target=" + encodeURIComponent(orderId), {
                credentials: "same-origin",
                headers: { "X-Requested-With": "admin-order-timeline" }
            });

            if (!response.ok) {
                throw new Error("audit request failed");
            }

            const html = await response.text();
            const parsed = new DOMParser().parseFromString(html, "text/html");
            const cards = Array.from(parsed.querySelectorAll(".compact-order-card"));
            const matched = cards.filter(function (card) {
                const type = normalizedText(card.querySelector(".badge"));
                const target = auditCardValue(card, "操作對象");
                return type === "訂單" && target.indexOf("#" + orderId) !== -1;
            }).slice(0, 12);

            loading.remove();

            matched.forEach(function (card) {
                const headerText = normalizedText(card.querySelector(".order-no"));
                const time = headerText.indexOf("｜") !== -1
                    ? headerText.split("｜").slice(1).join("｜").trim()
                    : auditCardValue(card, "時間");
                const action = normalizedText(card.querySelector("h3")) || auditCardValue(card, "操作內容");
                const operator = auditCardValue(card, "操作人員");
                const change = normalizedText(card.querySelector("pre"));
                const details = [];
                if (operator) {
                    details.push("操作人員：" + operator);
                }
                if (change && change !== "沒有欄位變更") {
                    details.push(change);
                }
                list.appendChild(makeTimelineItem(time, action, details.join("｜")));
            });

            const created = findCellValue("建立時間");
            const updated = findCellValue("最近更新");

            if (matched.length === 0 && updated && updated !== "—" && updated !== created) {
                list.appendChild(makeTimelineItem(updated, "訂單最近更新", "目前沒有可直接對應到這張訂單的客服後台 audit 紀錄。"));
            }

            if (created && created !== "—") {
                list.appendChild(makeTimelineItem(created, "訂單建立", "訂單原始建立時間。"));
            }

            if (!list.children.length) {
                const empty = document.createElement("div");
                empty.className = "mw-ops-timeline-empty";
                empty.textContent = "目前沒有可顯示的時間紀錄。";
                list.appendChild(empty);
            }
        } catch (_error) {
            loading.className = "mw-ops-timeline-empty";
            loading.textContent = "操作紀錄暫時無法載入；訂單本身仍可正常處理。";
            const created = findCellValue("建立時間");
            if (created && created !== "—") {
                list.appendChild(makeTimelineItem(created, "訂單建立", "訂單原始建立時間。"));
            }
        }
    }

    function setupTimeline(orderId) {
        const layout = document.querySelector("main.page .layout");
        if (!layout || !orderId || document.querySelector(".mw-ops-timeline")) {
            return;
        }

        const section = document.createElement("section");
        section.className = "mw-ops-timeline";

        const kicker = document.createElement("div");
        kicker.className = "mw-ops-center-kicker";
        kicker.textContent = "ORDER TIMELINE";
        const title = document.createElement("h2");
        title.textContent = "訂單時間軸";
        const description = document.createElement("p");
        description.textContent = "直接讀取既有客服後台操作紀錄；只做呈現，不另外建立第二套 audit 資料。";

        const list = document.createElement("div");
        list.className = "mw-ops-timeline-list";
        const loading = document.createElement("div");
        loading.className = "mw-ops-timeline-loading";
        loading.textContent = "正在載入操作紀錄…";
        list.appendChild(loading);

        const foot = document.createElement("div");
        foot.className = "mw-ops-timeline-foot";
        foot.appendChild(makeAction("查看完整操作紀錄 →", "/admin/audit?target=" + encodeURIComponent(orderId), false));

        section.appendChild(kicker);
        section.appendChild(title);
        section.appendChild(description);
        section.appendChild(list);
        section.appendChild(foot);
        layout.insertAdjacentElement("afterend", section);

        loadAuditTimeline(orderId, list, loading);
    }

    document.addEventListener("DOMContentLoaded", function () {
        ensureStyles();
        setupFinalDate();
        setupAnchors();
        const orderId = orderIdFromPath();
        setupStickyBar(orderId);
        setupNextStepCard();
        setNoticeRoles();
        setupSubmitFeedback();
        setupTimeline(orderId);
    });
})();
