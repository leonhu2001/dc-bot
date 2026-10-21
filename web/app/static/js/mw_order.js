(() => {
    "use strict";

    const dataNode =
        document.getElementById(
            "mw-order-groups-data"
        );

    const contextNode =
        document.getElementById(
            "mw-order-context-data"
        );

    if (!dataNode) {
        return;
    }

    let groups = [];

    try {
        groups = JSON.parse(
            dataNode.textContent || "[]"
        );
    } catch (error) {
        console.error(
            "order groups parse failed",
            error
        );
        return;
    }


    let context = {};

    try {
        context = JSON.parse(
            contextNode?.textContent
            || "{}"
        );
    } catch (_) {
        context = {};
    }


    const groupMap = new Map(
        groups.map(
            group => [
                group.key,
                group
            ]
        )
    );

    const pendingGroupLoads =
        new Map();


    const dialog =
        document.getElementById(
            "mw-order-dialog"
        );

    const closeButton =
        document.getElementById(
            "mw-dialog-close"
        );

    const categoryEl =
        document.getElementById(
            "mw-dialog-category"
        );

    const titleEl =
        document.getElementById(
            "mw-dialog-title"
        );

    const descriptionEl =
        document.getElementById(
            "mw-dialog-description"
        );

    const variantField =
        document.getElementById(
            "mw-variant-field"
        );

    const variantLabel =
        document.getElementById(
            "mw-variant-label"
        );

    const variantSelect =
        document.getElementById(
            "mw-variant"
        );

    const quantityField =
        document.getElementById(
            "mw-quantity-field"
        );

    const quantityLabel =
        document.getElementById(
            "mw-quantity-label"
        );

    const quantityValue =
        document.getElementById(
            "mw-quantity"
        );

    const quantityHelp =
        document.getElementById(
            "mw-quantity-help"
        );

    const quantityMinus =
        document.getElementById(
            "mw-quantity-minus"
        );

    const quantityPlus =
        document.getElementById(
            "mw-quantity-plus"
        );

    const playerField =
        document.getElementById(
            "mw-player-field"
        );

    const playerValue =
        document.getElementById(
            "mw-player-count"
        );

    const playerMinus =
        document.getElementById(
            "mw-player-minus"
        );

    const playerPlus =
        document.getElementById(
            "mw-player-plus"
        );

    const adjustmentsField =
        document.getElementById(
            "mw-adjustments-field"
        );

    const adjustmentsEl =
        document.getElementById(
            "mw-adjustments"
        );

    const totalEl =
        document.getElementById(
            "mw-total"
        );

    const detailEl =
        document.getElementById(
            "mw-total-detail"
        );

    const serviceBonusEl =
        document.getElementById(
            "mw-service-bonus"
        );

    const nextButton =
        document.getElementById(
            "mw-next-step"
        );

    const nextNotice =
        document.getElementById(
            "mw-next-notice"
        );

    const errorEl =
        document.getElementById(
            "mw-order-error"
        );


    let activeGroup = null;
    let activeVariant = null;

    let quantity = 1;
    let playerCount = 1;


    function money(value) {
        return (
            Number(value || 0)
            .toLocaleString("zh-TW")
            + "T"
        );
    }


    function clamp(
        value,
        min,
        max
    ) {
        return Math.max(
            min,
            Math.min(
                max,
                value
            )
        );
    }


    function getExactOverride(
        variant,
        qty
    ) {
        const overrides =
            variant.quantity_price_overrides
            || {};

        const key =
            String(qty);

        if (
            Object.prototype.hasOwnProperty.call(
                overrides,
                key
            )
        ) {
            return Number(
                overrides[key]
            );
        }

        return null;
    }


    function selectedAdjustmentAmount() {
        let total = 0;

        adjustmentsEl
            .querySelectorAll(
                "input[type=checkbox]:checked"
            )
            .forEach(
                input => {
                    let amount = Number(
                        input.dataset.amount
                        || 0
                    );

                    const mode =
                        input.dataset.amountMode
                        || "flat";

                    if (
                        mode
                        === "quantity_x_player_count"
                    ) {
                        amount *=
                            quantity
                            * playerCount;
                    } else if (
                        mode === "quantity"
                    ) {
                        amount *= quantity;
                    } else if (
                        mode === "player_count"
                    ) {
                        amount *= playerCount;
                    }

                    total += amount;
                }
            );

        return total;
    }


    function serviceQuantity(
        variant,
        qty
    ) {
        const buy = Number(
            variant.service_bonus_buy
            || 0
        );

        const gift = Number(
            variant.service_bonus_gift
            || 0
        );

        if (
            !buy
            || !gift
        ) {
            return qty;
        }

        return (
            qty
            + Math.floor(
                qty / buy
            ) * gift
        );
    }


    function calculate() {
        if (!activeVariant) {
            return;
        }


        const pricingType =
            activeVariant.pricing_type;

        if (
            pricingType === "manual"
        ) {
            totalEl.textContent =
                "客服報價";

            detailEl.textContent =
                "送出後由客服確認價格";

            return;
        }


        const override =
            getExactOverride(
                activeVariant,
                quantity
            );


        let base = 0;


        if (override !== null) {

            base = override;

        } else {

            base =
                Number(
                    activeVariant.price
                    || 0
                );


            if (
                activeVariant.quantity_enabled
            ) {
                base *= quantity;
            }


            if (
                activeVariant.player_count_enabled
                && activeVariant
                    .price_multiply_player_count
            ) {
                base *= playerCount;
            }
        }


        const adjustment =
            selectedAdjustmentAmount();


        const total =
            base + adjustment;


        totalEl.textContent =
            money(total);


        const parts = [];


        if (
            activeVariant.quantity_enabled
        ) {
            parts.push(
                `${quantity} ${activeVariant.unit_label}`
            );
        }


        if (
            activeVariant.player_count_enabled
        ) {
            parts.push(
                `${playerCount} 位`
            );
        }


        if (adjustment) {

            const sign =
                adjustment >= 0
                ? "+"
                : "";

            parts.push(
                `附加 ${sign}${money(adjustment)}`
            );
        }


        if (
            override !== null
        ) {
            parts.push(
                `${quantity} 個優惠價`
            );
        }


        detailEl.textContent =
            parts.length
                ? parts.join(" · ")
                : activeVariant.price_text;


        const delivered =
            serviceQuantity(
                activeVariant,
                quantity
            );


        if (
            delivered > quantity
        ) {

            serviceBonusEl.hidden =
                false;

            serviceBonusEl.textContent =
                `買 ${activeVariant.service_bonus_buy}`
                + ` 送 ${activeVariant.service_bonus_gift}`
                + `｜本次實際服務 ${delivered}`
                + ` ${activeVariant.unit_label}`;

        } else {

            serviceBonusEl.hidden =
                true;

            serviceBonusEl.textContent =
                "";
        }
    }


    function renderAdjustments() {
        adjustmentsEl.innerHTML =
            "";


        const adjustments =
            activeVariant
                ?.customer_adjustments
            || [];


        if (!adjustments.length) {

            adjustmentsField.hidden =
                true;

            return;
        }


        adjustmentsField.hidden =
            false;


        adjustments.forEach(
            adjustment => {

                const label =
                    document.createElement(
                        "label"
                    );

                label.className =
                    "order3-check";


                const input =
                    document.createElement(
                        "input"
                    );

                input.type =
                    "checkbox";

                input.value =
                    adjustment.key;

                input.dataset.amount =
                    String(
                        adjustment.amount
                        || 0
                    );

                input.dataset.amountMode =
                    String(
                        adjustment.amount_mode
                        || "flat"
                    );


                const text =
                    document.createElement(
                        "span"
                    );

                const amount =
                    Number(
                        adjustment.amount
                        || 0
                    );

                const sign =
                    amount >= 0
                        ? "+"
                        : "";

                text.textContent =
                    `${adjustment.label} `
                    + `${sign}${money(amount)}`;


                input.addEventListener(
                    "change",
                    calculate
                );


                label.append(
                    input,
                    text
                );


                adjustmentsEl.append(
                    label
                );
            }
        );
    }


    function renderVariant() {
        if (!activeGroup) {
            return;
        }


        const index =
            Math.max(
                0,
                variantSelect.selectedIndex
            );


        activeVariant =
            activeGroup.variants[
                index
            ];


        if (!activeVariant) {
            return;
        }


        quantity =
            Number(
                activeVariant.min_quantity
                || 1
            );


        playerCount =
            Number(
                activeVariant.min_player_count
                || 1
            );


        quantityValue.textContent =
            String(quantity);


        playerValue.textContent =
            String(playerCount);


        quantityField.hidden =
            !activeVariant.quantity_enabled;


        if (
            activeVariant.quantity_enabled
        ) {

            quantityLabel.textContent =
                activeVariant.unit_label === "H"
                    ? "時數"
                    : (
                        activeVariant.unit_label === "局"
                            ? "局數"
                            : "數量"
                    );


            quantityHelp.textContent =
                `可選 ${activeVariant.min_quantity}`
                + ` ～ ${activeVariant.max_quantity}`
                + ` ${activeVariant.unit_label}`;
        }


        playerField.hidden =
            !activeVariant
                .player_count_enabled;


        renderAdjustments();

        calculate();
    }


    async function loadGroup(
        groupKey
    ) {
        const key =
            String(
                groupKey || ""
            ).trim();

        if (!key) {
            throw new Error(
                "缺少商品資料。"
            );
        }

        const cached =
            groupMap.get(key);

        if (
            cached
            && Array.isArray(
                cached.variants
            )
        ) {
            return cached;
        }

        if (
            pendingGroupLoads.has(key)
        ) {
            return pendingGroupLoads.get(
                key
            );
        }

        const request = (
            async () => {
                const response =
                    await fetch(
                        `/order/group/${encodeURIComponent(key)}`,
                        {
                            headers: {
                                "Accept":
                                    "application/json",
                            },
                        }
                    );

                let result = null;

                try {
                    result =
                        await response.json();
                } catch (_) {
                    result = null;
                }

                if (
                    !response.ok
                    || !result?.ok
                    || !result?.group
                ) {
                    throw new Error(
                        result?.error
                        || "商品資料載入失敗，請稍後再試。"
                    );
                }

                groupMap.set(
                    key,
                    result.group
                );

                return result.group;
            }
        )();

        pendingGroupLoads.set(
            key,
            request
        );

        try {
            return await request;
        } finally {
            pendingGroupLoads.delete(
                key
            );
        }
    }


    async function openGroup(
        groupKey,
        button = null
    ) {
        const summary =
            groupMap.get(
                groupKey
            );


        if (!summary) {
            return;
        }

        const originalHtml =
            button?.innerHTML;

        if (button) {
            button.disabled = true;
            button.textContent =
                "載入中…";
        }

        let group = null;

        try {
            group = await loadGroup(
                groupKey
            );
        } catch (error) {
            console.error(
                "order group load failed",
                error
            );

            if (errorEl) {
                errorEl.textContent =
                    error?.message
                    || "商品資料載入失敗，請稍後再試。";
                errorEl.hidden = false;
            }

            return;
        } finally {
            if (button) {
                button.disabled = false;
                button.innerHTML =
                    originalHtml;
            }
        }

        if (errorEl) {
            errorEl.hidden = true;
            errorEl.textContent = "";
        }


        activeGroup =
            group;


        categoryEl.textContent =
            group.category_label
            || "ORDER";


        titleEl.textContent =
            group.label;


        descriptionEl.textContent =
            group.description
            || "";


        variantLabel.textContent =
            group.selector_label
            || "方案";


        variantSelect.innerHTML =
            "";


        group.variants.forEach(
            variant => {

                const option =
                    document.createElement(
                        "option"
                    );

                option.value =
                    variant.rule_key;

                option.dataset.ruleKey =
                    variant.rule_key;

                option.textContent =
                    (
                        group.variants.length > 1
                            ? `${variant.label}｜${variant.price_text}`
                            : variant.label
                    );


                variantSelect.append(
                    option
                );
            }
        );


        variantField.hidden =
            group.variants.length <= 1;


        variantSelect.selectedIndex =
            0;


        if (nextNotice) {
            nextNotice.hidden =
                true;
        }


        renderVariant();


        if (
            typeof dialog.showModal
            === "function"
        ) {
            dialog.showModal();
        } else {
            dialog.setAttribute(
                "open",
                ""
            );
        }

        // Lazy variants may arrive after the specified-staff guard's initial
        // pass. Re-dispatch change only after the options exist so the guard
        // can hide ineligible variants before the customer continues.
        variantSelect.dispatchEvent(
            new Event(
                "change",
                {
                    bubbles: true,
                }
            )
        );
    }


    document
        .querySelectorAll(
            "[data-order-group]"
        )
        .forEach(
            button => {

                const groupKey =
                    button.dataset
                        .orderGroup;

                button.addEventListener(
                    "click",
                    () => {
                        openGroup(
                            groupKey,
                            button
                        );
                    }
                );

                const preload =
                    () => {
                        loadGroup(
                            groupKey
                        ).catch(
                            () => {}
                        );
                    };

                button.addEventListener(
                    "pointerenter",
                    preload,
                    {
                        once: true,
                    }
                );

                button.addEventListener(
                    "focus",
                    preload,
                    {
                        once: true,
                    }
                );
            }
        );


    variantSelect.addEventListener(
        "change",
        renderVariant
    );


    quantityMinus.addEventListener(
        "click",
        () => {

            if (!activeVariant) {
                return;
            }

            quantity = clamp(
                quantity - 1,
                Number(
                    activeVariant.min_quantity
                    || 1
                ),
                Number(
                    activeVariant.max_quantity
                    || 24
                )
            );

            quantityValue.textContent =
                String(quantity);

            calculate();
        }
    );


    quantityPlus.addEventListener(
        "click",
        () => {

            if (!activeVariant) {
                return;
            }

            quantity = clamp(
                quantity + 1,
                Number(
                    activeVariant.min_quantity
                    || 1
                ),
                Number(
                    activeVariant.max_quantity
                    || 24
                )
            );

            quantityValue.textContent =
                String(quantity);

            calculate();
        }
    );


    playerMinus.addEventListener(
        "click",
        () => {

            if (!activeVariant) {
                return;
            }

            playerCount = clamp(
                playerCount - 1,
                Number(
                    activeVariant.min_player_count
                    || 1
                ),
                Number(
                    activeVariant.max_player_count
                    || 8
                )
            );

            playerValue.textContent =
                String(playerCount);

            calculate();
        }
    );


    playerPlus.addEventListener(
        "click",
        () => {

            if (!activeVariant) {
                return;
            }

            playerCount = clamp(
                playerCount + 1,
                Number(
                    activeVariant.min_player_count
                    || 1
                ),
                Number(
                    activeVariant.max_player_count
                    || 8
                )
            );

            playerValue.textContent =
                String(playerCount);

            calculate();
        }
    );


    closeButton.addEventListener(
        "click",
        () => {
            dialog.close();
        }
    );


    dialog.addEventListener(
        "click",
        event => {

            if (
                event.target
                === dialog
            ) {
                dialog.close();
            }
        }
    );


    if (nextButton) {

        nextButton.addEventListener(
            "click",
            () => {

                nextNotice.hidden =
                    false;


                nextNotice.scrollIntoView(
                    {
                        behavior:
                            "smooth",

                        block:
                            "nearest",
                    }
                );
            }
        );
    }
})();
