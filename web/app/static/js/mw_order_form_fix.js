(() => {
    "use strict";

    if (window.__MAWAN_ORDER_FORM_CLEAN_3211R__) {
        return;
    }

    window.__MAWAN_ORDER_FORM_CLEAN_3211R__ = true;


    const EXTRA_KEY =
        "mawan_order_extra_requirements";


    const ruleCache =
        new Map();


    let ruleRequest =
        0;


    let backgroundLocked =
        false;


    // ========================================================
    // Style
    // ========================================================

    const style =
        document.createElement(
            "style"
        );


    style.textContent = `
        html.mw-order-open,
        body.mw-order-open {
            overflow: hidden !important;
            overscroll-behavior: none !important;
        }

        #mw-adjustments-field {
            cursor: text;
        }

        #mw-extra-requirements {
            display: block;

            width: 100%;
            min-height: 82px;

            box-sizing: border-box;

            margin-top: 8px;
            padding: 8px 0 0;

            border: 0;
            outline: 0;

            background: transparent;

            color: inherit;

            font: inherit;
            line-height: 1.65;

            resize: vertical;
        }

        #mw-extra-requirements::placeholder {
            opacity: .36;
        }

        #mw-player-field.mw-fixed-player-count button {
            opacity: .38;
            cursor: not-allowed;
        }

        .mw-fixed-player-note {
            margin-left: 7px;

            opacity: .52;

            font-size: 11px;
        }
    `;


    document.head.appendChild(
        style
    );


    // ========================================================
    // Basic helpers
    // ========================================================

    function byId(
        id
    ) {

        return document.getElementById(
            id
        );
    }


    function clean(
        value
    ) {

        return String(
            value
            || ""
        ).trim();
    }


    function visible(
        element
    ) {

        if (!element) {
            return false;
        }


        if (element.hidden) {
            return false;
        }


        const rect =
            element.getBoundingClientRect();


        if (
            rect.width <= 0
            || rect.height <= 0
        ) {
            return false;
        }


        const computed =
            window.getComputedStyle(
                element
            );


        return (
            computed.display !== "none"
            && computed.visibility !== "hidden"
        );
    }


    // ========================================================
    // Background scroll lock
    // ========================================================

    function orderWindowOpen() {

        const select =
            byId(
                "mw-variant"
            );


        return visible(
            select
        );
    }


    function lockBackground() {

        if (backgroundLocked) {
            return;
        }


        backgroundLocked =
            true;


        document.documentElement
            .classList
            .add(
                "mw-order-open"
            );


        document.body
            .classList
            .add(
                "mw-order-open"
            );
    }


    function unlockBackground() {

        if (!backgroundLocked) {
            return;
        }


        backgroundLocked =
            false;


        document.documentElement
            .classList
            .remove(
                "mw-order-open"
            );


        document.body
            .classList
            .remove(
                "mw-order-open"
            );
    }


    function syncBackgroundLock() {

        if (orderWindowOpen()) {

            lockBackground();

        } else {

            unlockBackground();
        }
    }


    // ========================================================
    // Extra requirements
    // ========================================================

    function setupExtraRequirements() {

        const field =
            byId(
                "mw-adjustments-field"
            );


        const adjustments =
            byId(
                "mw-adjustments"
            );


        if (
            !field
            || !adjustments
        ) {
            return;
        }


        field.hidden =
            false;


        let textarea =
            byId(
                "mw-extra-requirements"
            );


        if (!textarea) {

            textarea =
                document.createElement(
                    "textarea"
                );


            textarea.id =
                "mw-extra-requirements";


            textarea.name =
                "extra_requirements";


            textarea.rows =
                4;


            textarea.maxLength =
                500;


            textarea.autocomplete =
                "off";


            textarea.placeholder =
                "可填寫稱呼、語音、打法或其他需求（選填）";


            textarea.value =
                sessionStorage.getItem(
                    EXTRA_KEY
                )
                || "";


            adjustments.insertAdjacentElement(
                "afterend",
                textarea
            );
        }


        textarea.disabled =
            false;


        textarea.readOnly =
            false;


        if (
            textarea.dataset
                .mwBound
            !== "1"
        ) {

            textarea.dataset
                .mwBound =
                    "1";


            textarea.addEventListener(
                "input",
                () => {

                    sessionStorage.setItem(
                        EXTRA_KEY,
                        textarea.value
                    );
                }
            );
        }
    }


    function clearExtraRequirements() {

        sessionStorage.removeItem(
            EXTRA_KEY
        );


        const textarea =
            byId(
                "mw-extra-requirements"
            );


        if (textarea) {

            textarea.value =
                "";
        }
    }


    // ========================================================
    // Rule key
    // ========================================================

    function currentRuleKey() {

        const direct =
            byId(
                "mw-rule-key"
            );


        if (direct) {

            const directValue =
                clean(
                    direct.value
                    || direct.dataset?.ruleKey
                    || direct.textContent
                );


            if (directValue) {

                return directValue;
            }
        }


        const select =
            byId(
                "mw-variant"
            );


        if (
            select
            && select.selectedIndex >= 0
        ) {

            const option =
                select.options[
                    select.selectedIndex
                ];


            return clean(
                option?.dataset?.ruleKey
                || option?.getAttribute(
                    "data-rule-key"
                )
                || option?.value
            );
        }


        return "";
    }


    async function loadRuleMeta(
        ruleKey
    ) {

        if (
            ruleCache.has(
                ruleKey
            )
        ) {

            return ruleCache.get(
                ruleKey
            );
        }


        const response =
            await fetch(
                "/order/rule-ui-meta"
                + "?rule_key="
                + encodeURIComponent(
                    ruleKey
                ),
                {
                    cache:
                        "no-store",
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
                || "rule meta failed"
            );
        }


        ruleCache.set(
            ruleKey,
            result.data
        );


        return result.data;
    }


    // ========================================================
    // Player count
    // ========================================================

    function playerUI() {

        const field =
            byId(
                "mw-player-field"
            );


        if (!field) {

            return null;
        }


        const minus =
            byId(
                "mw-player-minus"
            );


        const plus =
            byId(
                "mw-player-plus"
            );


        let value =
            byId(
                "mw-player-value"
            )
            || byId(
                "mw-player-count"
            )
            || field.querySelector(
                "input[name='player_count']"
            );


        if (!value) {

            const stepper =
                field.querySelector(
                    ".order3-stepper"
                );


            if (stepper) {

                value =
                    Array.from(
                        stepper.children
                    )
                    .find(
                        element => {

                            if (
                                element === minus
                                || element === plus
                            ) {

                                return false;
                            }


                            return /^\d+$/.test(
                                clean(
                                    element.textContent
                                )
                            );
                        }
                    )
                    || null;
            }
        }


        return {
            field,
            minus,
            plus,
            value,
        };
    }


    function writePlayerCount(
        ui,
        value
    ) {

        const count =
            Math.max(
                1,
                Number.parseInt(
                    value,
                    10
                )
                || 1
            );


        if (
            ui
            && ui.value
        ) {

            if (
                "value"
                in ui.value
            ) {

                ui.value.value =
                    String(
                        count
                    );

            } else {

                ui.value.textContent =
                    String(
                        count
                    );
            }
        }


        document
            .querySelectorAll(
                "input[name='player_count']"
            )
            .forEach(
                input => {

                    input.value =
                        String(
                            count
                        );
                }
            );
    }


    function setDisabled(
        button,
        disabled
    ) {

        if (!button) {
            return;
        }


        button.disabled =
            Boolean(
                disabled
            );


        button.setAttribute(
            "aria-disabled",
            disabled
                ? "true"
                : "false"
        );
    }


    async function refreshPlayerRule() {

        const ruleKey =
            currentRuleKey();


        if (!ruleKey) {

            return;
        }


        const serial =
            ++ruleRequest;


        try {

            const meta =
                await loadRuleMeta(
                    ruleKey
                );


            if (
                serial
                !== ruleRequest
            ) {

                return;
            }


            const ui =
                playerUI();


            if (!ui) {

                return;
            }


            const editable =
                Boolean(
                    meta
                        .player_count_enabled
                );


            if (!editable) {

                const fixed =
                    Math.max(
                        1,
                        Number.parseInt(
                            meta
                                .fixed_player_count,
                            10
                        )
                        || 1
                    );


                writePlayerCount(
                    ui,
                    fixed
                );


                setDisabled(
                    ui.minus,
                    true
                );


                setDisabled(
                    ui.plus,
                    true
                );


                ui.field
                    .classList
                    .add(
                        "mw-fixed-player-count"
                    );


                const label =
                    ui.field
                    .querySelector(
                        "span"
                    );


                if (
                    label
                    && !label.querySelector(
                        ".mw-fixed-player-note"
                    )
                ) {

                    const note =
                        document.createElement(
                            "small"
                        );


                    note.className =
                        "mw-fixed-player-note";


                    note.textContent =
                        "固定";


                    label.appendChild(
                        note
                    );
                }


            } else {

                setDisabled(
                    ui.minus,
                    false
                );


                setDisabled(
                    ui.plus,
                    false
                );


                ui.field
                    .classList
                    .remove(
                        "mw-fixed-player-count"
                    );


                ui.field
                    .querySelector(
                        ".mw-fixed-player-note"
                    )
                    ?.remove();
            }


        } catch (error) {

            console.error(
                "[MAWAN PLAYER RULE]",
                error
            );
        }
    }


    // ========================================================
    // Modal refresh
    // ========================================================

    function refreshModal() {

        setupExtraRequirements();

        refreshPlayerRule();

        syncBackgroundLock();
    }


    // ========================================================
    // Events
    // ========================================================

    document.addEventListener(
        "click",
        event => {

            const open =
                event.target.closest(
                    ".order3-open"
                );


            if (open) {

                clearExtraRequirements();


                requestAnimationFrame(
                    refreshModal
                );


                return;
            }


            if (backgroundLocked) {

                requestAnimationFrame(
                    syncBackgroundLock
                );
            }
        }
    );


    document.addEventListener(
        "change",
        event => {

            if (
                event.target?.id
                !== "mw-variant"
            ) {

                return;
            }


            requestAnimationFrame(
                () => {

                    setupExtraRequirements();

                    refreshPlayerRule();
                }
            );
        }
    );


    document.addEventListener(
        "keydown",
        event => {

            if (
                event.key
                !== "Escape"
            ) {

                return;
            }


            requestAnimationFrame(
                syncBackgroundLock
            );
        }
    );


    requestAnimationFrame(
        () => {

            setupExtraRequirements();

            syncBackgroundLock();
        }
    );

})();
