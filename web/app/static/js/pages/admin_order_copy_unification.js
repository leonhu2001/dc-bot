// ADMIN_ORDER_COPY_UNIFICATION
(function () {
    "use strict";

    const STATUS_BY_VALUE = Object.freeze({
        pending_cs_dispatch: "待客服確認",
        waiting_acceptance: "等待接單",
        accepted_pending_pay: "等待付款",
        active: "進行中",
        stored: "已暫存",
        closed: "已結單",
        cancelled: "已取消",
        created: "待客服確認",
        paid: "進行中",
        completed: "已結單",
        done: "已結單",
        canceled: "已取消"
    });

    const STATUS_BY_TEXT = Object.freeze({
        "待確認": "待客服確認",
        "待客服確認": "待客服確認",
        "已建立": "待客服確認",
        "等待接單": "等待接單",
        "等待付款": "等待付款",
        "已滿員｜等待付款": "等待付款",
        "進行中": "進行中",
        "已付款": "進行中",
        "服務進行中": "進行中",
        "存單": "已暫存",
        "已存單": "已暫存",
        "已暫存": "已暫存",
        "stored": "已暫存",
        "已完成": "已結單",
        "已結單": "已結單",
        "已取消": "已取消",
        "cancelled": "已取消",
        "canceled": "已取消"
    });

    function isOrderSurface() {
        const path = String(window.location.pathname || "");
        return path === "/admin" || path.startsWith("/admin/order-workspace/");
    }

    function text(node) {
        return node ? String(node.textContent || "").replace(/\s+/g, " ").trim() : "";
    }

    function replaceNodeText(node, replacement) {
        if (!node || !replacement || text(node) === replacement) {
            return;
        }
        node.textContent = replacement;
    }

    function normalizeStatusSelects() {
        document.querySelectorAll('select[name="status"]').forEach(function (select) {
            Array.from(select.options || []).forEach(function (option) {
                const value = String(option.value || "").trim().toLowerCase();
                if (value !== "all" && STATUS_BY_VALUE[value]) {
                    option.textContent = STATUS_BY_VALUE[value];
                }
            });
        });
    }

    function normalizeOrderStatusCells() {
        document.querySelectorAll(".cell").forEach(function (cell) {
            const label = cell.querySelector(".label");
            if (text(label) !== "狀態") {
                return;
            }
            const value = cell.querySelector(".value");
            const normalized = STATUS_BY_TEXT[text(value)];
            if (normalized) {
                replaceNodeText(value, normalized);
            }
        });
    }

    function normalizeOrderBadges() {
        document.querySelectorAll(".admin-order-status-badge").forEach(function (badge) {
            const normalized = STATUS_BY_TEXT[text(badge)];
            if (normalized) {
                replaceNodeText(badge, normalized);
            }
        });
    }

    function apply() {
        if (!isOrderSurface()) {
            return;
        }
        normalizeStatusSelects();
        normalizeOrderStatusCells();
        normalizeOrderBadges();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", apply, { once: true });
    } else {
        apply();
    }
})();