(() => {
    "use strict";


    const byId = id =>
        document.getElementById(
            id
        );


    const priceButton =
        byId(
            "mw-next-step"
        );


    const checkoutButton =
        byId(
            "mw-open-checkout"
        );


    if (!priceButton) {
        return;
    }


    let context = {};


    try {

        context = JSON.parse(
            byId(
                "mw-order-context-data"
            )?.textContent
            || "{}"
        );

    } catch (_) {

        context = {};
    }


    const resultBox =
        byId(
            "mw-server-result"
        );


    const baseEl =
        byId(
            "mw-server-base"
        );


    const extraEl =
        byId(
            "mw-server-extra"
        );


    const totalEl =
        byId(
            "mw-server-total"
        );


    const detailEl =
        byId(
            "mw-server-detail"
        );


    const errorEl =
        byId(
            "mw-order-error"
        );


    const checkoutPanel =
        byId(
            "mw-checkout-panel"
        );


    const checkoutVip =
        byId(
            "mw-checkout-vip"
        );


    const checkoutVipNote =
        byId(
            "mw-checkout-vip-note"
        );


    const checkoutPoints =
        byId(
            "mw-checkout-points"
        );


    const checkoutWalletBalance =
        byId(
            "mw-checkout-wallet-balance"
        );


    const checkoutStaffSection =
        byId(
            "mw-checkout-staff-section"
        );


    const checkoutStaffHelp =
        byId(
            "mw-checkout-staff-help"
        );


    const checkoutStaffGrid =
        byId(
            "mw-checkout-staff-grid"
        );


    const pointSelect =
        byId(
            "mw-checkout-point"
        );


    const pointNote =
        byId(
            "mw-checkout-point-note"
        );


    const useWallet =
        byId(
            "mw-checkout-use-wallet"
        );


    const paymentSelect =
        byId(
            "mw-checkout-payment"
        );


    const paymentInfo =
        byId(
            "mw-checkout-payment-info"
        );


    const checkoutError =
        byId(
            "mw-checkout-error"
        );


    const checkoutSummary =
        byId(
            "mw-checkout-summary"
        );


    const coService =
        byId(
            "mw-co-service"
        );


    const coVip =
        byId(
            "mw-co-vip-discount"
        );


    const coSpecify =
        byId(
            "mw-co-specify"
        );


    const coPoint =
        byId(
            "mw-co-point"
        );


    const coWallet =
        byId(
            "mw-co-wallet"
        );


    const coTotal =
        byId(
            "mw-co-total"
        );


    const coNotes =
        byId(
            "mw-co-notes"
        );


    let currentPayload = null;

    let checkoutOptions = null;

    let priceVerified = false;


    const money = value =>
        Number(
            value
            || 0
        ).toLocaleString(
            "zh-TW"
        ) + "T";


    function readNumber(
        id,
        fallback = 1
    ) {

        const value =
            Number(
                byId(
                    id
                )?.textContent
                || fallback
            );


        return Number.isFinite(
            value
        )
            ? value
            : fallback;
    }


    function readAdjustments() {

        const root =
            byId(
                "mw-adjustments"
            );


        if (!root) {
            return [];
        }


        return Array.from(
            root.querySelectorAll(
                "input[type=checkbox]:checked"
            )
        )
        .map(
            input =>
                String(
                    input.value
                    || ""
                )
        )
        .filter(
            Boolean
        );
    }


    function invalidatePrice() {

        priceVerified =
            false;


        currentPayload =
            null;

        if (
            typeof updateFinalButton
            === "function"
        ) {

            updateFinalButton();
        }



        checkoutOptions =
            null;


        if (resultBox) {
            resultBox.hidden =
                true;
        }


        if (checkoutButton) {
            checkoutButton.hidden =
                true;
        }


        if (checkoutPanel) {
            checkoutPanel.hidden =
                true;
        }


        if (checkoutSummary) {
            checkoutSummary.hidden =
                true;
        }
    }


    function selectedStaffIds() {

        const lockedId =
            String(
                checkoutOptions
                    ?.staff
                    ?.preselected_staff_id
                || ""
            ).trim();


        if (
            checkoutOptions
                ?.staff
                ?.preselected_locked
            && lockedId
        ) {

            return [
                lockedId
            ];
        }


        if (!checkoutStaffGrid) {
            return [];
        }


        return Array.from(
            checkoutStaffGrid.querySelectorAll(
                "input[type=checkbox]:checked"
            )
        )
        .map(
            input =>
                String(
                    input.value
                    || ""
                )
        );
    }


    function refreshFreeSpecifyOption() {

        if (!pointSelect) {
            return;
        }


        const count =
            selectedStaffIds()
                .length;


        Array.from(
            pointSelect.options
        ).forEach(
            option => {

                if (
                    option.dataset
                        .requiresSpecified
                    !== "1"
                ) {

                    return;
                }


                const affordable =
                    option.dataset
                        .affordable
                    === "1";


                const genericAllowed =
                    option.dataset
                        .genericAllowed
                    === "1";


                option.disabled =
                    !affordable
                    || !genericAllowed
                    || count <= 0;


                if (
                    option.disabled
                    && option.selected
                ) {

                    pointSelect.value =
                        "";
                }
            }
        );
    }


    function createLockedStaffCard(
        item
    ) {

        const card =
            document.createElement(
                "div"
            );


        card.className =
            "order-checkout-locked-staff";


        const avatar =
            document.createElement(
                "img"
            );


        avatar.src =
            item.avatar_url;


        avatar.alt =
            "";


        avatar.onerror =
            function () {

                this.onerror =
                    null;

                this.src =
                    "/static/img/server_logo.gif";
            };


        const copy =
            document.createElement(
                "div"
            );


        const eyebrow =
            document.createElement(
                "small"
            );


        eyebrow.textContent =
            "已從陪玩陣容指定";


        const name =
            document.createElement(
                "strong"
            );


        name.textContent =
            item.display_name;


        const role =
            document.createElement(
                "span"
            );


        role.textContent =
            item.role_label;


        copy.append(
            eyebrow,
            name,
            role
        );


        const status =
            document.createElement(
                "b"
            );


        status.textContent =
            "已指定";


        card.append(
            avatar,
            copy,
            status
        );


        return card;
    }


    function renderStaff(
        staff
    ) {

        checkoutStaffGrid.innerHTML =
            "";


        checkoutStaffGrid.hidden =
            false;


        if (
            !staff.allow_specify
        ) {

            checkoutStaffHelp.textContent =
                "此方案不開放指定人員。";


            checkoutStaffSection.classList.add(
                "is-disabled"
            );


            return;
        }


        checkoutStaffSection.classList.remove(
            "is-disabled"
        );


        // ==================================================
        // From staff roster / profile.
        // Do NOT ask the customer to specify again.
        // ==================================================

        if (
            staff.preselected_locked
            && staff.preselected_staff
        ) {

            checkoutStaffHelp.textContent =
                "已從陪玩陣容指定，無需再次選擇。";


            checkoutStaffGrid.classList.add(
                "is-locked"
            );


            checkoutStaffGrid.append(
                createLockedStaffCard(
                    staff.preselected_staff
                )
            );


            refreshFreeSpecifyOption();

            return;
        }


        checkoutStaffGrid.classList.remove(
            "is-locked"
        );


        const maxCount =
            Number(
                staff.max_specified_count
                || 1
            );


        checkoutStaffHelp.textContent =
            `最多可指定 ${maxCount} 位`;


        if (
            !staff.items
            || !staff.items.length
        ) {

            checkoutStaffGrid.innerHTML =
                '<div class="order-checkout-empty">'
                + '目前沒有符合這個方案的指定人員。'
                + '</div>';


            return;
        }


        staff.items.forEach(
            item => {

                const label =
                    document.createElement(
                        "label"
                    );


                label.className =
                    "order-checkout-staff";


                const input =
                    document.createElement(
                        "input"
                    );


                input.type =
                    "checkbox";


                input.value =
                    item.staff_id;


                const avatar =
                    document.createElement(
                        "img"
                    );


                avatar.src =
                    item.avatar_url;


                avatar.alt =
                    "";


                avatar.onerror =
                    function () {

                        this.onerror =
                            null;

                        this.src =
                            "/static/img/server_logo.gif";
                    };


                const copy =
                    document.createElement(
                        "span"
                    );


                const name =
                    document.createElement(
                        "strong"
                    );


                name.textContent =
                    item.display_name;


                const role =
                    document.createElement(
                        "small"
                    );


                role.textContent =
                    item.role_label;


                copy.append(
                    name,
                    role
                );


                input.addEventListener(
                    "change",
                    async () => {

                        const selected =
                            selectedStaffIds();


                        if (
                            selected.length
                            > maxCount
                        ) {

                            input.checked =
                                false;


                            checkoutError.textContent =
                                `這個方案最多只能指定 ${maxCount} 位。`;


                            checkoutError.hidden =
                                false;


                            return;
                        }


                        checkoutError.hidden =
                            true;


                        refreshFreeSpecifyOption();


                        await refreshCheckoutPreview();
                    }
                );


                label.append(
                    input,
                    avatar,
                    copy
                );


                checkoutStaffGrid.append(
                    label
                );
            }
        );


        refreshFreeSpecifyOption();
    }


    function renderPointOptions(
        items
    ) {

        pointSelect.innerHTML =
            "";


        const empty =
            document.createElement(
                "option"
            );


        empty.value =
            "";


        empty.textContent =
            "不使用點數";


        pointSelect.append(
            empty
        );


        (
            items
            || []
        ).forEach(
            item => {

                const option =
                    document.createElement(
                        "option"
                    );


                option.value =
                    item.key;


                option.textContent =
                    `${item.cost} 點｜${item.name}`;


                const affordable =
                    Number(
                        item.cost
                        || 0
                    )
                    <= Number(
                        checkoutOptions
                            ?.customer
                            ?.points
                        || 0
                    );


                const requiresSpecified =
                    Boolean(
                        item.requires_specified
                    );


                const genericAllowed =
                    Boolean(
                        item.allowed
                    )
                    || requiresSpecified;


                option.dataset.affordable =
                    affordable
                    ? "1"
                    : "0";


                option.dataset.requiresSpecified =
                    requiresSpecified
                    ? "1"
                    : "0";


                option.dataset.genericAllowed =
                    genericAllowed
                    ? "1"
                    : "0";


                option.dataset.reason =
                    item.reason
                    || "";


                option.disabled =
                    !affordable
                    || !genericAllowed;


                if (
                    requiresSpecified
                    && selectedStaffIds()
                        .length <= 0
                ) {

                    option.disabled =
                        true;
                }


                pointSelect.append(
                    option
                );
            }
        );


        refreshFreeSpecifyOption();
    }


    function renderCheckoutOptions(
        data
    ) {

        checkoutOptions =
            data;


        checkoutVip.textContent =
            data.customer.vip_name;


        checkoutVipNote.textContent =
            data.vip.eligible
                ? `此方案自動套用 ${data.vip.pay_rate}% 應付比例`
                : data.vip.reason;


        checkoutPoints.textContent =
            `${Number(
                data.customer.points
                || 0
            ).toLocaleString(
                "zh-TW"
            )} 點`;


        checkoutWalletBalance.textContent =
            money(
                data.customer
                    .wallet_balance
            );


        renderStaff(
            data.staff
        );


        renderPointOptions(
            data.point_options
        );


        if (
            data.payment_methods
                ?.length
        ) {

            paymentSelect.innerHTML =
                "";


            data.payment_methods.forEach(
                method => {

                    const option =
                        document.createElement(
                            "option"
                        );


                    option.value =
                        method.key;


                    option.textContent =
                        method.label;


                    paymentSelect.append(
                        option
                    );
                }
            );
        }


        checkoutPanel.hidden =
            false;
    }


    function renderPaymentInfo(
        info
    ) {

        if (!info) {

            paymentInfo.hidden =
                true;

            paymentInfo.textContent =
                "";

            return;
        }


        paymentInfo.textContent =
            info;


        paymentInfo.hidden =
            false;
    }


    function renderCheckoutPreview(
        data
    ) {

        const finance =
            data.finance;


        coService.textContent =
            money(
                finance.service_amount
            );


        coVip.textContent =
            finance.vip_discount_amount
            > 0
                ? `-${money(
                    finance.vip_discount_amount
                )}`
                : "0T";


        coSpecify.textContent =
            finance.specify_fee
            > 0
                ? money(
                    finance.specify_fee
                )
                : "0T";


        const pointReduction =
            Number(
                finance.point_cash_discount
                || 0
            )
            + Number(
                finance.point_waived_specify_fee
                || 0
            );


        coPoint.textContent =
            pointReduction
            > 0
                ? `-${money(
                    pointReduction
                )}`
                : "0T";


        coWallet.textContent =
            finance.wallet_use_amount
            > 0
                ? `-${money(
                    finance.wallet_use_amount
                )}`
                : "0T";


        coTotal.textContent =
            money(
                finance.remaining_pay_amount
            );


        const notes = [];


        if (
            data.vip.eligible
            && finance.vip_discount_amount
            > 0
        ) {

            notes.push(
                `${data.customer.vip_name}：`
                + `${data.vip.pay_rate}% 應付比例`
            );
        }


        if (
            data.selected_staff
                ?.length
        ) {

            notes.push(
                "指定："
                + data.selected_staff
                    .map(
                        item =>
                            `${item.display_name}（${item.role_label}）`
                    )
                    .join(
                        "、"
                    )
            );
        }


        if (
            data.free_specify_by_rule
        ) {

            notes.push(
                "此單已符合原規則免指定費"
            );
        }


        if (
            data.point.name
        ) {

            notes.push(
                `${data.point.cost} 點｜${data.point.name}`
            );
        }


        if (
            finance.point_service_note
        ) {

            notes.push(
                finance.point_service_note
            );
        }


        if (
            finance.wallet_use_amount
            > 0
        ) {

            notes.push(
                `錢包預計使用 ${money(
                    finance.wallet_use_amount
                )}`
            );
        }


        notes.push(
            `付款：${data.payment.method}`
        );


        coNotes.innerHTML =
            "";


        notes.forEach(
            text => {

                const span =
                    document.createElement(
                        "span"
                    );


                span.textContent =
                    text;


                coNotes.append(
                    span
                );
            }
        );


        renderPaymentInfo(
            data.payment.info
        );


        checkoutSummary.hidden =
            false;

        if (
            typeof updateFinalButton
            === "function"
        ) {

            updateFinalButton();
        }



        sessionStorage.setItem(
            "mawan_checkout_preview",
            JSON.stringify(
                data
            )
        );
    }


    async function refreshCheckoutPreview() {

        if (
            !currentPayload
            || !checkoutOptions
        ) {

            return;
        }


        checkoutError.hidden =
            true;


        checkoutSummary.hidden =
            true;


        const payload = {
            ...currentPayload,

            specified_staff_ids:
                selectedStaffIds(),

            point_item_key:
                pointSelect.value
                || null,

            use_wallet: false,

            payment_method: null,
        };


        try {

            const response =
                await fetch(
                    "/order/checkout/preview",
                    {
                        method:
                            "POST",

                        headers: {
                            "Content-Type":
                                "application/json",

                            "Accept":
                                "application/json",
                        },

                        body:
                            JSON.stringify(
                                payload
                            ),
                    }
                );


            const result =
                await response.json();


            if (
                !response.ok
                || !result.ok
            ) {

                throw new Error(
                    result.error
                    || "結帳試算失敗。"
                );
            }


            renderCheckoutPreview(
                result.data
            );


        } catch (error) {

            checkoutError.textContent =
                error?.message
                || "結帳試算失敗。";


            checkoutError.hidden =
                false;
        }
    }


    async function loadCheckout() {

        if (
            !priceVerified
            || !currentPayload
        ) {

            return;
        }


        const oldHtml =
            checkoutButton
                ?.innerHTML;


        if (checkoutButton) {

            checkoutButton.disabled =
                true;

            checkoutButton.textContent =
                "載入中…";
        }


        try {

            const response =
                await fetch(
                    "/order/checkout/options",
                    {
                        method:
                            "POST",

                        headers: {
                            "Content-Type":
                                "application/json",

                            "Accept":
                                "application/json",
                        },

                        body:
                            JSON.stringify(
                                {
                                    ...currentPayload,

                                    preselected_staff_id:
                                        context
                                            .specified_staff_id
                                        || null,
                                }
                            ),
                    }
                );


            const result =
                await response.json();


            if (
                !response.ok
                || !result.ok
            ) {

                throw new Error(
                    result.error
                    || "載入結帳資料失敗。"
                );
            }


            renderCheckoutOptions(
                result.data
            );


            await refreshCheckoutPreview();


            checkoutPanel.scrollIntoView(
                {
                    behavior:
                        "smooth",

                    block:
                        "nearest",
                }
            );


        } catch (error) {

            if (checkoutError) {

                checkoutError.textContent =
                    error?.message
                    || "載入結帳資料失敗。";


                checkoutError.hidden =
                    false;


                checkoutPanel.hidden =
                    false;
            }


        } finally {

            if (checkoutButton) {

                checkoutButton.disabled =
                    false;

                checkoutButton.innerHTML =
                    oldHtml;
            }
        }
    }


    async function getPrice(
        event
    ) {

        event.preventDefault();

        event.stopImmediatePropagation();


        invalidatePrice();


        if (errorEl) {

            errorEl.hidden =
                true;

            errorEl.textContent =
                "";
        }


        const ruleKey =
            String(
                byId(
                    "mw-rule-key"
                )?.textContent
                || ""
            ).trim();


        if (!ruleKey) {

            errorEl.textContent =
                "請先選擇商品方案。";


            errorEl.hidden =
                false;


            return;
        }


        const payload = {
            rule_key:
                ruleKey,

            quantity:
                readNumber(
                    "mw-quantity",
                    1
                ),

            player_count:
                readNumber(
                    "mw-player-count",
                    1
                ),

            customer_adjustments:
                readAdjustments(),

            specified_staff_id:
                null,
        };


        const originalHtml =
            priceButton.innerHTML;


        priceButton.disabled =
            true;


        priceButton.textContent =
            "取得價格中…";


        try {

            const response =
                await fetch(
                    "/order/quote",
                    {
                        method:
                            "POST",

                        headers: {
                            "Content-Type":
                                "application/json",

                            "Accept":
                                "application/json",
                        },

                        body:
                            JSON.stringify(
                                payload
                            ),
                    }
                );


            const data =
                await response.json();


            if (
                !response.ok
                || !data.ok
            ) {

                throw new Error(
                    data.error
                    || "無法取得價格。"
                );
            }


            const quote =
                data.quote;


            if (
                quote.manual_quote
            ) {

                baseEl.textContent =
                    "客服報價";

                extraEl.textContent =
                    "—";

                totalEl.textContent =
                    "客服報價";

            } else {

                baseEl.textContent =
                    money(
                        quote.base_amount
                    );


                extraEl.textContent =
                    money(
                        quote.adjustment_amount
                    );


                totalEl.textContent =
                    money(
                        quote.customer_pay_amount
                    );
            }


            const details = [
                quote.item,
            ];


            if (
                quote.pricing_type
                !== "fixed"
                && quote.pricing_type
                !== "manual"
            ) {

                details.push(
                    `${quote.quantity} ${quote.unit_label}`
                );
            }


            if (
                quote.player_count
                > 1
            ) {

                details.push(
                    `${quote.player_count} 位`
                );
            }




            if (
                quote.customer_adjustments
                    ?.length
            ) {

                details.push(
                    quote.customer_adjustments
                        .map(
                            item =>
                                `${item.label} +${money(item.amount)}`
                        )
                        .join(
                            " / "
                        )
                );
            }


            detailEl.textContent =
                details.join(
                    " · "
                );


            resultBox.hidden =
                false;


            if (typeof resetFormalSubmission === "function") {
                resetFormalSubmission();
            }

            currentPayload = {
                rule_key:
                    ruleKey,

                quantity:
                    payload.quantity,

                player_count:
                    payload.player_count,

                customer_adjustments:
                    payload.customer_adjustments,
            };


            priceVerified =
                true;


            if (checkoutButton) {

                checkoutButton.hidden =
                    false;
            }


            sessionStorage.setItem(
                "mawan_order_draft",
                JSON.stringify(
                    {
                        saved_at:
                            new Date()
                                .toISOString(),

                        payload:
                            currentPayload,

                        quote:
                            quote,

                        specified_staff_id:
                            context
                                .specified_staff_id
                            || null,
                    }
                )
            );


            resultBox.scrollIntoView(
                {
                    behavior:
                        "smooth",

                    block:
                        "nearest",
                }
            );


        } catch (error) {

            errorEl.textContent =
                error?.message
                || "無法取得價格。";


            errorEl.hidden =
                false;


        } finally {

            priceButton.disabled =
                false;


            priceButton.innerHTML =
                originalHtml;
        }
    }


    priceButton.addEventListener(
        "click",
        getPrice,
        true
    );


    checkoutButton?.addEventListener(
        "click",
        loadCheckout
    );


    pointSelect?.addEventListener(
        "change",
        async () => {

            const option =
                pointSelect.options[
                    pointSelect.selectedIndex
                ];


            pointNote.textContent =
                option?.dataset?.reason
                || "選擇後由伺服器重新驗證資格";


            await refreshCheckoutPreview();
        }
    );


    useWallet?.addEventListener(
        "change",
        refreshCheckoutPreview
    );


    paymentSelect?.addEventListener(
        "change",
        refreshCheckoutPreview
    );


    // Any change to product configuration
    // invalidates the old server price.
    [
        "mw-variant",
        "mw-quantity-minus",
        "mw-quantity-plus",
        "mw-player-minus",
        "mw-player-plus",
    ].forEach(
        id => {

            const element =
                byId(
                    id
                );


            if (!element) {
                return;
            }


            element.addEventListener(
                (
                    id
                    === "mw-variant"
                    ? "change"
                    : "click"
                ),
                invalidatePrice
            );
        }
    );


    byId(
        "mw-adjustments"
    )?.addEventListener(
        "change",
        invalidatePrice
    );


    // === PHASE 3B-2.3 INTERNAL RESET ===

    window.addEventListener(
        "mawan:order-reset",
        () => {

            invalidatePrice();


            currentPayload =
                null;


            checkoutOptions =
                null;


            priceVerified =
                false;


            if (baseEl) {

                baseEl.textContent =
                    "—";
            }


            if (extraEl) {

                extraEl.textContent =
                    "—";
            }


            if (totalEl) {

                totalEl.textContent =
                    "—";
            }


            if (detailEl) {

                detailEl.textContent =
                    "";
            }


            if (pointSelect) {

                pointSelect.value =
                    "";
            }


            if (useWallet) {

                useWallet.checked =
                    false;
            }


            if (
                paymentSelect
                && paymentSelect.options.length
            ) {

                paymentSelect.selectedIndex =
                    0;
            }


            if (checkoutStaffGrid) {

                checkoutStaffGrid
                    .querySelectorAll(
                        "input[type=checkbox]"
                    )
                    .forEach(
                        input => {

                            input.checked =
                                false;
                        }
                    );
            }


            if (checkoutError) {

                checkoutError.hidden =
                    true;

                checkoutError.textContent =
                    "";
            }


            if (errorEl) {

                errorEl.hidden =
                    true;

                errorEl.textContent =
                    "";
            }


            if (paymentInfo) {

                paymentInfo.hidden =
                    true;

                paymentInfo.textContent =
                    "";
            }
        }
    );

    // === /PHASE 3B-2.3 INTERNAL RESET ===



    // === PHASE 3C-3A FORMAL SUBMIT ===

    const finalTerms =
        byId(
            "mw-checkout-terms"
        );


    const finalButton =
        byId(
            "mw-checkout-final"
        );


    const finalNote =
        byId(
            "mw-checkout-final-note"
        );


    const finalSuccess =
        byId(
            "mw-checkout-success"
        );


    let finalRequestKey =
        null;


    let finalSubmitting =
        false;


    let finalCreated =
        false;


    function createRequestKey() {

        if (
            window.crypto
            && typeof window.crypto.randomUUID
                === "function"
        ) {

            return (
                "web-"
                + window.crypto.randomUUID()
            );
        }


        return (
            "web-"
            + Date.now()
            + "-"
            + Math.random()
                .toString(36)
                .slice(2)
            + "-"
            + Math.random()
                .toString(36)
                .slice(2)
        );
    }


    function finalPreviewReady() {

        return Boolean(
            priceVerified
            && currentPayload
            && checkoutOptions
            && checkoutSummary
            && !checkoutSummary.hidden
        );
    }


    function updateFinalButton() {

        if (!finalButton) {
            return;
        }


        finalButton.disabled =
            Boolean(
                finalSubmitting
                || finalCreated
                || !finalPreviewReady()
                || !finalTerms?.checked
            );
    }


    function currentExtraRequirements() {

        return String(
            byId(
                "mw-extra-requirements"
            )?.value
            || ""
        )
        .trim()
        .slice(
            0,
            500
        );
    }


    function buildFormalPayload() {

        return {
            ...currentPayload,

            specified_staff_ids:
                selectedStaffIds(),

            point_item_key:
                pointSelect?.value
                || null,

            use_wallet: false,

            payment_method: null,

            extra_requirements:
                currentExtraRequirements(),

            terms_accepted:
                Boolean(
                    finalTerms?.checked
                ),

            terms_version:
                String(
                    finalTerms?.dataset
                        ?.termsVersion
                    || ""
                ),

            request_key:
                finalRequestKey
                || (
                    finalRequestKey =
                        createRequestKey()
                ),
        };
    }


    function resetFormalSubmission() {

        finalRequestKey =
            null;


        finalSubmitting =
            false;


        finalCreated =
            false;


        if (
            finalTerms
        ) {

            finalTerms.checked =
                false;
        }


        if (
            finalSuccess
        ) {

            finalSuccess.hidden =
                true;


            finalSuccess.textContent =
                "";
        }


        if (
            finalNote
        ) {

            finalNote.hidden =
                false;
        }


        updateFinalButton();
    }


    async function submitFormalOrder() {

        if (
            finalSubmitting
            || finalCreated
        ) {
            return;
        }


        if (
            !finalTerms?.checked
        ) {

            checkoutError.textContent =
                "請先閱讀並同意服務規章。";


            checkoutError.hidden =
                false;


            updateFinalButton();

            return;
        }


        if (
            !finalPreviewReady()
        ) {

            checkoutError.textContent =
                "結帳資料已失效，請重新取得價格。";


            checkoutError.hidden =
                false;

            return;
        }


        finalSubmitting =
            true;


        checkoutError.hidden =
            true;


        if (
            finalSuccess
        ) {

            finalSuccess.hidden =
                true;
        }


        const originalHtml =
            finalButton.innerHTML;


        finalButton.disabled =
            true;


        finalButton.textContent =
            "建立訂單中…";


        try {

            const payload =
                buildFormalPayload();


            const response =
                await fetch(
                    "/order/create",
                    {
                        method:
                            "POST",

                        headers: {
                            "Content-Type":
                                "application/json",
                        },

                        body:
                            JSON.stringify(
                                payload
                            ),
                    }
                );


            let result;


            try {

                result =
                    await response.json();

            } catch {

                throw new Error(
                    "伺服器回應格式錯誤。"
                );
            }


            if (
                !response.ok
                || !result.ok
            ) {

                throw new Error(
                    result.error
                    || "建立訂單失敗。"
                );
            }


            finalCreated =
                true;


            const data =
                result.data
                || {};


            if (
                finalSuccess
            ) {

                finalSuccess.innerHTML =
                    "";


                const title =
                    document.createElement(
                        "strong"
                    );


                title.textContent =
                    "訂單已建立";


                const detail =
                    document.createElement(
                        "div"
                    );


                detail.textContent =
                    "網站訂單編號：#"
                    + String(
                        data.order_id
                        || "—"
                    )
                    + "｜狀態：等待接單";


                const ticket =
                    document.createElement(
                        "small"
                    );


                ticket.textContent =
                    "Discord 票口建立後，將等待客服確認送單。";


                finalSuccess.append(
                    title,
                    detail,
                    ticket
                );


                finalSuccess.hidden =
                    false;
            }


            if (
                finalNote
            ) {

                finalNote.hidden =
                    true;
            }


            finalButton.textContent =
                "正式訂單已建立";


            finalButton.disabled =
                true;


            sessionStorage.removeItem(
                "mawan_checkout_preview"
            );


            sessionStorage.removeItem(
                "mawan_order_extra_requirements"
            );


        } catch (error) {

            checkoutError.textContent =
                error?.message
                || "建立訂單失敗。";


            checkoutError.hidden =
                false;


            // Keep finalRequestKey.
            // Retrying the exact same submission remains idempotent.

            finalButton.innerHTML =
                originalHtml;


        } finally {

            finalSubmitting =
                false;


            if (!finalCreated) {

                updateFinalButton();
            }
        }
    }


    if (
        finalTerms
    ) {

        finalTerms.addEventListener(
            "change",
            updateFinalButton
        );
    }


    if (
        finalButton
    ) {

        finalButton.addEventListener(
            "click",
            submitFormalOrder
        );
    }

    // === /PHASE 3C-3A FORMAL SUBMIT ===



    // MAWAN_3C3B2R_NO_WEB_PAYMENT
    //
    // 官網只負責下單。
    // 真正付款方式在人員接滿後，
    // 由 Discord PaymentMethodView 選擇。



    // MAWAN_3C3B2R3_NO_WEB_PAYMENT
    //
    // 官網只負責下單。
    // paymentSelect 保留在 JS 內僅為相容舊 preview，
    // 使用者不會在官網選擇付款方式。

    function enforceSimpleWebsiteCheckout() {

        const walletControl =
            document.getElementById(
                "mw-checkout-use-wallet"
            );


        if (walletControl) {

            walletControl.checked =
                false;


            walletControl.disabled =
                true;


            const walletBox =
                walletControl.closest(
                    ".order-checkout-control"
                )
                || walletControl.closest(
                    "label"
                );


            if (walletBox) {

                walletBox.style
                    .setProperty(
                        "display",
                        "none",
                        "important"
                    );


                walletBox.setAttribute(
                    "aria-hidden",
                    "true"
                );
            }
        }


        const paymentControl =
            document.getElementById(
                "mw-checkout-payment"
            );


        if (paymentControl) {

            const options =
                Array.from(
                    paymentControl.options
                    || []
                );


            const transferOption =
                options.find(
                    option =>
                        String(
                            option.value
                            || option.textContent
                            || ""
                        ).includes(
                            "轉帳"
                        )
                )
                || options.find(
                    option =>
                        String(
                            option.value
                            || ""
                        ).trim()
                );


            if (transferOption) {

                paymentControl.value =
                    transferOption.value;
            }


            const paymentBox =
                paymentControl.closest(
                    ".order-checkout-control"
                )
                || paymentControl.closest(
                    "label"
                );


            if (paymentBox) {

                paymentBox.style
                    .setProperty(
                        "display",
                        "none",
                        "important"
                    );


                paymentBox.setAttribute(
                    "aria-hidden",
                    "true"
                );
            }
        }
    }


    enforceSimpleWebsiteCheckout();


    document.addEventListener(
        "click",
        event => {

            if (
                event.target.closest(
                    "#mw-open-checkout"
                )
                || event.target.closest(
                    ".order3-open"
                )
            ) {

                requestAnimationFrame(
                    () => {

                        enforceSimpleWebsiteCheckout();


                        requestAnimationFrame(
                            enforceSimpleWebsiteCheckout
                        );
                    }
                );
            }
        }
    );

})();
