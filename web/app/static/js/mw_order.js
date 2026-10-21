(() => {
    "use strict";

    const byId = id => document.getElementById(id);
    const dataNode = byId("mw-order-groups-data");
    const contextNode = byId("mw-order-context-data");

    if (!dataNode) {
        return;
    }

    let groups = [];
    try {
        groups = JSON.parse(dataNode.textContent || "[]");
    } catch (error) {
        console.error("order groups parse failed", error);
        return;
    }

    let context = {};
    try {
        context = JSON.parse(contextNode?.textContent || "{}");
    } catch (_) {
        context = {};
    }

    const groupMap = new Map(
        groups.map(group => [String(group.key || ""), group])
    );
    const pendingGroupLoads = new Map();

    const dialog = byId("mw-order-dialog");
    const closeButton = byId("mw-dialog-close");
    const categoryEl = byId("mw-dialog-category");
    const titleEl = byId("mw-dialog-title");
    const descriptionEl = byId("mw-dialog-description");
    const variantField = byId("mw-variant-field");
    const variantLabel = byId("mw-variant-label");
    const variantSelect = byId("mw-variant");
    const quantityField = byId("mw-quantity-field");
    const quantityLabel = byId("mw-quantity-label");
    const quantityValue = byId("mw-quantity");
    const quantityHelp = byId("mw-quantity-help");
    const quantityMinus = byId("mw-quantity-minus");
    const quantityPlus = byId("mw-quantity-plus");
    const playerField = byId("mw-player-field");
    const playerValue = byId("mw-player-count");
    const playerMinus = byId("mw-player-minus");
    const playerPlus = byId("mw-player-plus");
    const adjustmentsField = byId("mw-adjustments-field");
    const adjustmentsEl = byId("mw-adjustments");
    const totalEl = byId("mw-total");
    const detailEl = byId("mw-total-detail");
    const serviceBonusEl = byId("mw-service-bonus");
    const nextButton = byId("mw-next-step");
    const nextNotice = byId("mw-next-notice");
    const errorEl = byId("mw-order-error");

    let activeGroup = null;
    let activeVariant = null;
    let quantity = 1;
    let playerCount = 1;

    function money(value) {
        return Number(value || 0).toLocaleString("zh-TW") + "T";
    }

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function showDialog() {
        if (!dialog) {
            return;
        }
        if (typeof dialog.showModal === "function") {
            if (!dialog.open) {
                dialog.showModal();
            }
        } else {
            dialog.setAttribute("open", "");
        }
    }

    function showLoadError(message, card) {
        categoryEl.textContent = card?.category_label || "ORDER";
        titleEl.textContent = card?.label || "商品設定";
        descriptionEl.textContent = "";
        variantField.hidden = true;
        quantityField.hidden = true;
        playerField.hidden = true;
        adjustmentsField.hidden = true;
        serviceBonusEl.hidden = true;
        if (errorEl) {
            errorEl.textContent = message || "商品資料載入失敗，請稍後再試。";
            errorEl.hidden = false;
        }
        showDialog();
    }

    async function loadGroup(groupKey) {
        const key = String(groupKey || "").trim();
        if (!key) {
            throw new Error("缺少商品資料。");
        }

        const current = groupMap.get(key);
        if (current && Array.isArray(current.variants)) {
            return current;
        }

        if (pendingGroupLoads.has(key)) {
            return pendingGroupLoads.get(key);
        }

        const promise = (async () => {
            const response = await fetch(
                `/order/group/${encodeURIComponent(key)}`,
                {
                    method: "GET",
                    headers: {
                        "Accept": "application/json",
                    },
                }
            );

            let result = null;
            try {
                result = await response.json();
            } catch (_) {
                result = null;
            }

            if (!response.ok || !result?.ok || !result?.group) {
                throw new Error(
                    result?.error || "商品資料載入失敗，請稍後再試。"
                );
            }

            groupMap.set(key, result.group);
            return result.group;
        })();

        pendingGroupLoads.set(key, promise);
        try {
            return await promise;
        } finally {
            pendingGroupLoads.delete(key);
        }
    }

    function getExactOverride(variant, qty) {
        const overrides = variant.quantity_price_overrides || {};
        const key = String(qty);
        if (Object.prototype.hasOwnProperty.call(overrides, key)) {
            return Number(overrides[key]);
        }
        return null;
    }

    function selectedAdjustmentAmount() {
        let total = 0;
        adjustmentsEl
            .querySelectorAll("input[type=checkbox]:checked")
            .forEach(input => {
                let amount = Number(input.dataset.amount || 0);
                const mode = input.dataset.amountMode || "flat";

                if (mode === "quantity_x_player_count") {
                    amount *= quantity * playerCount;
                } else if (mode === "quantity") {
                    amount *= quantity;
                } else if (mode === "player_count") {
                    amount *= playerCount;
                }
                total += amount;
            });
        return total;
    }

    function serviceQuantity(variant, qty) {
        const buy = Number(variant.service_bonus_buy || 0);
        const gift = Number(variant.service_bonus_gift || 0);
        if (!buy || !gift) {
            return qty;
        }
        return qty + Math.floor(qty / buy) * gift;
    }

    function calculate() {
        if (!activeVariant) {
            return;
        }

        const pricingType = activeVariant.pricing_type;
        if (pricingType === "manual") {
            totalEl.textContent = "客服報價";
            detailEl.textContent = "送出後由客服確認價格";
            return;
        }

        const override = getExactOverride(activeVariant, quantity);
        let base = 0;

        if (override !== null) {
            base = override;
        } else {
            base = Number(activeVariant.price || 0);
            if (activeVariant.quantity_enabled) {
                base *= quantity;
            }
            if (
                activeVariant.player_count_enabled
                && activeVariant.price_multiply_player_count
            ) {
                base *= playerCount;
            }
        }

        const adjustment = selectedAdjustmentAmount();
        totalEl.textContent = money(base + adjustment);

        const parts = [];
        if (activeVariant.quantity_enabled) {
            parts.push(`${quantity} ${activeVariant.unit_label}`);
        }
        if (activeVariant.player_count_enabled) {
            parts.push(`${playerCount} 位`);
        }
        if (adjustment) {
            const sign = adjustment >= 0 ? "+" : "";
            parts.push(`附加 ${sign}${money(adjustment)}`);
        }
        if (override !== null) {
            parts.push(`${quantity} 個優惠價`);
        }

        detailEl.textContent = parts.length
            ? parts.join(" · ")
            : activeVariant.price_text;

        const delivered = serviceQuantity(activeVariant, quantity);
        if (delivered > quantity) {
            serviceBonusEl.hidden = false;
            serviceBonusEl.textContent =
                `買 ${activeVariant.service_bonus_buy}`
                + ` 送 ${activeVariant.service_bonus_gift}`
                + `｜本次實際服務 ${delivered}`
                + ` ${activeVariant.unit_label}`;
        } else {
            serviceBonusEl.hidden = true;
            serviceBonusEl.textContent = "";
        }
    }

    function renderAdjustments() {
        adjustmentsEl.innerHTML = "";
        const adjustments = activeVariant?.customer_adjustments || [];

        if (!adjustments.length) {
            adjustmentsField.hidden = true;
            return;
        }

        adjustmentsField.hidden = false;
        adjustments.forEach(adjustment => {
            const label = document.createElement("label");
            label.className = "order3-check";

            const input = document.createElement("input");
            input.type = "checkbox";
            input.value = adjustment.key;
            input.dataset.amount = String(adjustment.amount || 0);
            input.dataset.amountMode = String(
                adjustment.amount_mode || "flat"
            );

            const text = document.createElement("span");
            const amount = Number(adjustment.amount || 0);
            const sign = amount >= 0 ? "+" : "";
            text.textContent = `${adjustment.label} ${sign}${money(amount)}`;

            input.addEventListener("change", calculate);
            label.append(input, text);
            adjustmentsEl.append(label);
        });
    }

    function renderVariant() {
        if (!activeGroup) {
            return;
        }

        const index = Math.max(0, variantSelect.selectedIndex);
        activeVariant = activeGroup.variants[index];
        if (!activeVariant) {
            return;
        }

        quantity = Number(activeVariant.min_quantity || 1);
        playerCount = Number(activeVariant.min_player_count || 1);
        quantityValue.textContent = String(quantity);
        playerValue.textContent = String(playerCount);
        quantityField.hidden = !activeVariant.quantity_enabled;

        if (activeVariant.quantity_enabled) {
            quantityLabel.textContent = activeVariant.unit_label === "H"
                ? "時數"
                : (activeVariant.unit_label === "局" ? "局數" : "數量");
            quantityHelp.textContent =
                `可選 ${activeVariant.min_quantity}`
                + ` ～ ${activeVariant.max_quantity}`
                + ` ${activeVariant.unit_label}`;
        }

        playerField.hidden = !activeVariant.player_count_enabled;
        renderAdjustments();
        calculate();
    }

    function renderGroup(group) {
        activeGroup = group;
        activeVariant = null;

        if (errorEl) {
            errorEl.hidden = true;
            errorEl.textContent = "";
        }

        categoryEl.textContent = group.category_label || "ORDER";
        titleEl.textContent = group.label;
        descriptionEl.textContent = group.description || "";
        variantLabel.textContent = group.selector_label || "方案";
        variantSelect.innerHTML = "";

        group.variants.forEach(variant => {
            const option = document.createElement("option");
            option.value = variant.rule_key;
            option.textContent = group.variants.length > 1
                ? `${variant.label}｜${variant.price_text}`
                : variant.label;
            variantSelect.append(option);
        });

        variantField.hidden = group.variants.length <= 1;
        variantSelect.selectedIndex = 0;
        if (nextNotice) {
            nextNotice.hidden = true;
        }

        renderVariant();
        showDialog();
    }

    async function openGroup(groupKey, button = null) {
        const key = String(groupKey || "").trim();
        const card = groupMap.get(key);
        if (!card) {
            return;
        }

        const originalHtml = button?.innerHTML;
        if (button) {
            button.disabled = true;
            button.textContent = "載入中…";
        }

        try {
            const group = await loadGroup(key);
            renderGroup(group);
        } catch (error) {
            showLoadError(
                error?.message || "商品資料載入失敗，請稍後再試。",
                card
            );
        } finally {
            if (button) {
                button.disabled = false;
                button.innerHTML = originalHtml;
            }
        }
    }

    document
        .querySelectorAll("[data-order-group]")
        .forEach(button => {
            const key = String(button.dataset.orderGroup || "").trim();

            button.addEventListener("click", () => {
                openGroup(key, button);
            });

            const preload = () => {
                loadGroup(key).catch(() => {});
            };
            button.addEventListener("pointerenter", preload, { once: true });
            button.addEventListener("focus", preload, { once: true });
        });

    variantSelect.addEventListener("change", renderVariant);

    quantityMinus.addEventListener("click", () => {
        if (!activeVariant) {
            return;
        }
        quantity = clamp(
            quantity - 1,
            Number(activeVariant.min_quantity || 1),
            Number(activeVariant.max_quantity || 24)
        );
        quantityValue.textContent = String(quantity);
        calculate();
    });

    quantityPlus.addEventListener("click", () => {
        if (!activeVariant) {
            return;
        }
        quantity = clamp(
            quantity + 1,
            Number(activeVariant.min_quantity || 1),
            Number(activeVariant.max_quantity || 24)
        );
        quantityValue.textContent = String(quantity);
        calculate();
    });

    playerMinus.addEventListener("click", () => {
        if (!activeVariant) {
            return;
        }
        playerCount = clamp(
            playerCount - 1,
            Number(activeVariant.min_player_count || 1),
            Number(activeVariant.max_player_count || 8)
        );
        playerValue.textContent = String(playerCount);
        calculate();
    });

    playerPlus.addEventListener("click", () => {
        if (!activeVariant) {
            return;
        }
        playerCount = clamp(
            playerCount + 1,
            Number(activeVariant.min_player_count || 1),
            Number(activeVariant.max_player_count || 8)
        );
        playerValue.textContent = String(playerCount);
        calculate();
    });

    closeButton.addEventListener("click", () => {
        dialog.close();
    });

    dialog.addEventListener("click", event => {
        if (event.target === dialog) {
            dialog.close();
        }
    });

    if (nextButton) {
        nextButton.addEventListener("click", () => {
            nextNotice.hidden = false;
            nextNotice.scrollIntoView({
                behavior: "smooth",
                block: "nearest",
            });
        });
    }
})();
