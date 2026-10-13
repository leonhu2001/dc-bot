(() => {
    "use strict";

    // === PHASE 3B-2.11R LEAN GUARD ===
    //
    // Specified-staff filtering remains event-driven.
    // Continuous DOM watching is intentionally disabled.
    class MWGuardNoopObserver {
        constructor(callback) {
            this.callback = callback;
        }

        observe() {}

        disconnect() {}

        takeRecords() {
            return [];
        }
    }
    // === /PHASE 3B-2.11R LEAN GUARD ===




    const STYLE_ID =
        "mw-role-filter-style";


    if (
        !document.getElementById(
            STYLE_ID
        )
    ) {

        const style =
            document.createElement(
                "style"
            );


        style.id =
            STYLE_ID;


        style.textContent = `
            .mw-role-filter-hidden {
                display: none !important;
            }

            .mw-role-filter-loading {
                visibility: hidden !important;
            }
        `;


        document.head.append(
            style
        );
    }


    const byId = id =>
        document.getElementById(
            id
        );


    function normalize(
        value
    ) {

        return String(
            value
            || ""
        )
        .toLowerCase()
        .replace(
            /[\s｜|／/\\\-_:：·・()（）【】\[\]「」『』]+/g,
            ""
        )
        .trim();
    }


    function looksLikeSnowflake(
        value
    ) {

        return /^\d{15,22}$/.test(
            String(
                value
                || ""
            ).trim()
        );
    }


    function readOrderContext() {

        try {

            return JSON.parse(
                byId(
                    "mw-order-context-data"
                )?.textContent
                || "{}"
            );

        } catch (_) {

            return {};
        }
    }


    function staffIdFromHref(
        href
    ) {

        const match =
            String(
                href
                || ""
            ).match(
                /\/staff\/(\d{15,22})(?:[/?#]|$)/
            );


        return (
            match
            ? match[1]
            : ""
        );
    }


    function resolveSpecifiedStaffId() {

        const context =
            readOrderContext();


        const candidates = [
            context
                ?.specified_staff_id,

            context
                ?.preselected_staff_id,

            context
                ?.selected_staff_id,

            context
                ?.staff_id,

            context
                ?.specified_staff
                ?.staff_id,

            context
                ?.specified_staff
                ?.staff_discord_id,

            context
                ?.selected_staff
                ?.staff_id,

            context
                ?.selected_staff
                ?.staff_discord_id,
        ];


        for (
            const value
            of candidates
        ) {

            if (
                looksLikeSnowflake(
                    value
                )
            ) {

                return {
                    id:
                        String(
                            value
                        ),

                    source:
                        "context",
                };
            }
        }


        const params =
            new URLSearchParams(
                location.search
            );


        const preferredNames = [
            "specified_staff_id",
            "preselected_staff_id",
            "selected_staff_id",
            "staff_id",
            "staff",
            "specified",
            "member_id",
            "receiver_id",
        ];


        for (
            const name
            of preferredNames
        ) {

            const value =
                params.get(
                    name
                );


            if (
                looksLikeSnowflake(
                    value
                )
            ) {

                return {
                    id:
                        value,

                    source:
                        "query:"
                        + name,
                };
            }
        }


        for (
            const [
                name,
                value
            ]
            of params.entries()
        ) {

            if (
                /staff|specif|member|receiver|worker|crew/i
                    .test(
                        name
                    )
                && looksLikeSnowflake(
                    value
                )
            ) {

                return {
                    id:
                        value,

                    source:
                        "query-scan:"
                        + name,
                };
            }
        }


        // The selected-staff banner already has
        // "查看個人牆". This is the most useful fallback
        // if the JS context was never given the Discord ID.
        const profileLinks =
            Array.from(
                document.querySelectorAll(
                    'a[href*="/staff/"]'
                )
            );


        const preferredLink =
            profileLinks.find(
                link =>
                    String(
                        link.textContent
                        || ""
                    ).includes(
                        "查看個人牆"
                    )
            );


        if (preferredLink) {

            const id =
                staffIdFromHref(
                    preferredLink.href
                );


            if (id) {

                return {
                    id,
                    source:
                        "selected-banner-link",
                };
            }
        }


        // Last fallback: any staff profile link
        // near text saying the user selected a staff member.
        for (
            const link
            of profileLinks
        ) {

            let parent =
                link.parentElement;


            for (
                let i = 0;
                i < 5 && parent;
                i += 1
            ) {

                const text =
                    String(
                        parent.textContent
                        || ""
                    );


                if (
                    text.includes(
                        "已從個人牆選擇"
                    )
                    || text.includes(
                        "已從陪玩陣容"
                    )
                    || text.includes(
                        "指定"
                    )
                ) {

                    const id =
                        staffIdFromHref(
                            link.href
                        );


                    if (id) {

                        return {
                            id,
                            source:
                                "banner-parent-link",
                        };
                    }
                }


                parent =
                    parent.parentElement;
            }
        }


        return {
            id:
                "",

            source:
                "not-found",
        };
    }


    const selectedStaff =
        resolveSpecifiedStaffId();


    const specifiedStaffId =
        selectedStaff.id;


    const directSelectionVisible =
        document.body.textContent.includes(
            "已從個人牆選擇"
        )
        || document.body.textContent.includes(
            "已從陪玩陣容"
        );


    let filterData =
        null;


    let eligibleRules =
        new Set();


    let ruleMeta =
        {};


    let groupMeta =
        {};


    let ruleLabelIndex =
        [];


    let groupLabelIndex =
        [];


    function resetOrderState() {

        window.dispatchEvent(
            new CustomEvent(
                "mawan:order-reset"
            )
        );


        [
            "mw-server-result",
            "mw-open-checkout",
            "mw-checkout-panel",
            "mw-checkout-summary",
            "mw-order-error",
            "mw-checkout-error",
            "mw-checkout-payment-info",
        ].forEach(
            id => {

                const element =
                    byId(
                        id
                    );


                if (element) {

                    element.hidden =
                        true;
                }
            }
        );


        const point =
            byId(
                "mw-checkout-point"
            );


        if (point) {

            point.value =
                "";
        }


        const wallet =
            byId(
                "mw-checkout-use-wallet"
            );


        if (wallet) {

            wallet.checked =
                false;
        }


        const payment =
            byId(
                "mw-checkout-payment"
            );


        if (
            payment
            && payment.options.length
        ) {

            payment.selectedIndex =
                0;
        }


        sessionStorage.removeItem(
            "mawan_order_draft"
        );


        sessionStorage.removeItem(
            "mawan_checkout_preview"
        );
    }


    function buildIndexes() {

        ruleLabelIndex =
            Object.values(
                ruleMeta
            )
            .map(
                rule => ({
                    key:
                        String(
                            rule.key
                            || ""
                        ),

                    text:
                        normalize(
                            rule.label
                        ),
                })
            )
            .filter(
                item =>
                    item.key
                    && item.text
            )
            .sort(
                (
                    a,
                    b
                ) =>
                    b.text.length
                    - a.text.length
            );


        groupLabelIndex =
            Object.entries(
                groupMeta
            )
            .map(
                (
                    [
                        label,
                        ruleKeys
                    ]
                ) => ({
                    label,
                    text:
                        normalize(
                            label
                        ),

                    rules:
                        Array.from(
                            ruleKeys
                            || []
                        ),
                })
            )
            .filter(
                item =>
                    item.text
                    && item.rules.length
            )
            .sort(
                (
                    a,
                    b
                ) =>
                    b.text.length
                    - a.text.length
            );
    }


    // ========================================================
    // Real card discovery
    //
    // Previous versions depended on
    // [data-order-group-card].
    // This page clearly does not reliably expose that selector.
    // ========================================================

    function cardAncestorFromAction(
        action
    ) {

        if (!action) {

            return null;
        }


        const explicit =
            action.closest(
                "[data-order-group-card],"
                + ".order3-card,"
                + ".order-card,"
                + ".order-product-card,"
                + "article"
            );


        if (explicit) {

            return explicit;
        }


        let current =
            action.parentElement;


        for (
            let depth = 0;
            depth < 9 && current;
            depth += 1
        ) {

            const text =
                String(
                    current.textContent
                    || ""
                );


            const startCount =
                Array.from(
                    current.querySelectorAll(
                        "button,a"
                    )
                )
                .filter(
                    node =>
                        String(
                            node.textContent
                            || ""
                        )
                        .trim()
                        .includes(
                            "開始設定"
                        )
                )
                .length;


            if (
                startCount === 1
                && (
                    text.includes(
                        "PRICE"
                    )
                    || text.includes(
                        "OPTIONS"
                    )
                    || text.includes(
                        "開始設定"
                    )
                )
            ) {

                return current;
            }


            current =
                current.parentElement;
        }


        return null;
    }


    function discoverCards() {

        const result =
            new Set();


        document
            .querySelectorAll(
                "[data-order-group-card],"
                + ".order3-card,"
                + ".order-card,"
                + ".order-product-card,"
                + "article"
            )
            .forEach(
                card => {

                    if (
                        String(
                            card.textContent
                            || ""
                        ).includes(
                            "開始設定"
                        )
                    ) {

                        result.add(
                            card
                        );
                    }
                }
            );


        const actions =
            Array.from(
                document.querySelectorAll(
                    "button,a"
                )
            )
            .filter(
                node =>
                    String(
                        node.textContent
                        || ""
                    )
                    .trim()
                    .includes(
                        "開始設定"
                    )
            );


        for (
            const action
            of actions
        ) {

            const card =
                cardAncestorFromAction(
                    action
                );


            if (card) {

                result.add(
                    card
                );
            }
        }


        return [
            ...result
        ];
    }


    function cardTitleTexts(
        card
    ) {

        const result =
            [];


        const selectors = [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "[class*=title]",
            "[class*=name]",
        ];


        for (
            const selector
            of selectors
        ) {

            card
                .querySelectorAll(
                    selector
                )
                .forEach(
                    element => {

                        const value =
                            String(
                                element.textContent
                                || ""
                            ).trim();


                        if (
                            value
                            && value.length <= 40
                        ) {

                            result.push(
                                value
                            );
                        }
                    }
                );
        }


        return [
            ...new Set(
                result
            )
        ];
    }


    function candidateRulesForCard(
        card
    ) {

        const result =
            new Set();


        const titles =
            cardTitleTexts(
                card
            );


        const normalizedTitles =
            titles.map(
                normalize
            );


        const cardText =
            normalize(
                card.textContent
            );


        // First match the public group title.
        for (
            const group
            of groupLabelIndex
        ) {

            const matchedTitle =
                normalizedTitles.some(
                    title =>
                        title
                            === group.text
                        || title.includes(
                            group.text
                        )
                        || group.text.includes(
                            title
                        )
                );


            const matchedCardText =
                cardText.includes(
                    group.text
                );


            if (
                matchedTitle
                || matchedCardText
            ) {

                group.rules.forEach(
                    ruleKey =>
                        result.add(
                            ruleKey
                        )
                );
            }
        }


        // Also detect exact formal rule labels.
        for (
            const rule
            of ruleLabelIndex
        ) {

            if (
                cardText.includes(
                    rule.text
                )
            ) {

                result.add(
                    rule.key
                );
            }
        }


        return result;
    }


    function setCardVisible(
        card,
        visible
    ) {

        card.classList.toggle(
            "mw-role-filter-hidden",
            !visible
        );


        card.dataset
            .mwRoleAllowed =
                visible
                ? "1"
                : "0";
    }


    function filterCards() {

        if (
            !filterData
            || !specifiedStaffId
        ) {

            return;
        }


        const cards =
            discoverCards();


        let visibleCount =
            0;


        let hiddenCount =
            0;


        const unresolved = [];


        for (
            const card
            of cards
        ) {

            const candidateRules =
                candidateRulesForCard(
                    card
                );


            if (
                candidateRules.size === 0
            ) {

                // Direct-staff ordering fails closed.
                setCardVisible(
                    card,
                    false
                );


                unresolved.push(
                    cardTitleTexts(
                        card
                    )[0]
                    || "UNKNOWN"
                );


                hiddenCount += 1;

                continue;
            }


            const allowed =
                [
                    ...candidateRules
                ]
                .some(
                    ruleKey =>
                        eligibleRules.has(
                            ruleKey
                        )
                );


            setCardVisible(
                card,
                allowed
            );


            if (allowed) {

                visibleCount += 1;

            } else {

                hiddenCount += 1;
            }
        }


        console.info(
            "[MAWAN CARD FILTER]",
            {
                specified_staff_id:
                    specifiedStaffId,

                staff_id_source:
                    selectedStaff.source,

                roles:
                    filterData
                        .staff_role_keys,

                visible:
                    visibleCount,

                hidden:
                    hiddenCount,

                unresolved,
            }
        );
    }


    // ========================================================
    // Variant dropdown
    // ========================================================

    function currentDialogGroupRules() {

        const dialog =
            byId(
                "mw-order-dialog"
            )
            || document.querySelector(
                "[role=dialog]"
            )
            || document.querySelector(
                ".order3-dialog"
            );


        if (!dialog) {

            return null;
        }


        const text =
            normalize(
                dialog.textContent
            );


        for (
            const group
            of groupLabelIndex
        ) {

            if (
                text.includes(
                    group.text
                )
            ) {

                return new Set(
                    group.rules
                );
            }
        }


        return null;
    }


    function resolveRuleForOption(
        option
    ) {

        if (!option) {

            return null;
        }


        const direct = [
            option.dataset
                ?.ruleKey,

            option.dataset
                ?.rule,

            option.dataset
                ?.orderRule,

            option.getAttribute(
                "data-rule-key"
            ),

            option.value,
        ];


        for (
            const value
            of direct
        ) {

            const key =
                String(
                    value
                    || ""
                ).trim();


            if (
                key
                && Object.prototype
                    .hasOwnProperty.call(
                        ruleMeta,
                        key
                    )
            ) {

                return key;
            }
        }


        const optionText =
            normalize(
                option.textContent
            );


        if (!optionText) {

            return null;
        }


        const groupRules =
            currentDialogGroupRules();


        const candidates =
            ruleLabelIndex.filter(
                rule => {

                    if (
                        groupRules
                        && !groupRules.has(
                            rule.key
                        )
                    ) {

                        return false;
                    }


                    return (
                        rule.text
                            === optionText
                        || rule.text.endsWith(
                            optionText
                        )
                        || rule.text.includes(
                            optionText
                        )
                        || optionText.includes(
                            rule.text
                        )
                    );
                }
            );


        if (
            candidates.length === 1
        ) {

            return candidates[0].key;
        }


        return null;
    }


    function filterVariants() {

        if (
            !filterData
            || !specifiedStaffId
        ) {

            return;
        }


        const select =
            byId(
                "mw-variant"
            );


        if (!select) {

            return;
        }


        let firstAllowed =
            null;


        for (
            const option
            of Array.from(
                select.options
            )
        ) {

            const rawText =
                String(
                    option.textContent
                    || ""
                ).trim();


            const rawValue =
                String(
                    option.value
                    || ""
                ).trim();


            const placeholder =
                (
                    !rawValue
                    && (
                        rawText.includes(
                            "請選"
                        )
                        || rawText.includes(
                            "選擇"
                        )
                    )
                );


            const ruleKey =
                resolveRuleForOption(
                    option
                );


            const allowed =
                placeholder
                || (
                    ruleKey
                    && eligibleRules.has(
                        ruleKey
                    )
                );


            option.hidden =
                !allowed;


            option.disabled =
                !allowed;


            if (
                allowed
                && ruleKey
                && !firstAllowed
            ) {

                firstAllowed =
                    option;
            }
        }


        const current =
            select.options[
                select.selectedIndex
            ];


        const currentRule =
            resolveRuleForOption(
                current
            );


        if (
            currentRule
            && !eligibleRules.has(
                currentRule
            )
        ) {

            if (firstAllowed) {

                select.value =
                    firstAllowed.value;


                select.dispatchEvent(
                    new Event(
                        "change",
                        {
                            bubbles:
                                true,
                        }
                    )
                );


            } else {

                select.selectedIndex =
                    0;
            }
        }
    }


    function applyFilter() {

        filterCards();

        filterVariants();


        requestAnimationFrame(
            filterVariants
        );



        requestAnimationFrame(
            filterVariants
        );

    }


    function failClosed(
        message
    ) {

        discoverCards()
            .forEach(
                card => {

                    setCardVisible(
                        card,
                        false
                    );
                }
            );


        console.error(
            "[MAWAN STAFF FILTER]",
            message
        );
    }


    async function loadFilter() {

        if (
            !specifiedStaffId
        ) {

            if (
                directSelectionVisible
            ) {

                failClosed(
                    "Selected-staff banner exists "
                    + "but Discord staff ID could not be resolved."
                );
            }


            return;
        }


        try {

            const response =
                await fetch(
                    "/order/staff-filter"
                    + "?staff_id="
                    + encodeURIComponent(
                        specifiedStaffId
                    )
                    + "&_="
                    + Date.now(),
                    {
                        cache:
                            "no-store",

                        headers: {
                            "Accept":
                                "application/json",
                        },
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
                    || "無法取得指定陪玩的接單資格。"
                );
            }


            filterData =
                result.data;


            eligibleRules =
                new Set(
                    filterData
                        .eligible_rule_keys
                    || []
                );


            ruleMeta =
                filterData.rules
                || {};


            groupMeta =
                filterData
                    .group_meta
                || {};


            buildIndexes();


            // Hard invariant:
            // female companion alone can never obtain
            // protector-only EXBAR technical order.
            const roles =
                new Set(
                    filterData
                        .staff_role_keys
                    || []
                );


            const hasProtectorRole =
                roles.has(
                    "top_protector"
                )
                || roles.has(
                    "female_protector"
                )
                || roles.has(
                    "male_protector"
                );


            if (
                !hasProtectorRole
                && eligibleRules.has(
                    "basic_exbar_tech"
                )
            ) {

                throw new Error(
                    "資格資料異常："
                    + "非護航身分取得了絕巴技術陪。"
                );
            }


            applyFilter();


            console.info(
                "[MAWAN STAFF FILTER READY]",
                {
                    specified_staff_id:
                        specifiedStaffId,

                    id_source:
                        selectedStaff.source,

                    roles:
                        filterData
                            .staff_role_keys,

                    role_source:
                        filterData
                            .role_source,

                    can_exbar_tech:
                        eligibleRules.has(
                            "basic_exbar_tech"
                        ),

                    eligible_rules:
                        filterData
                            .eligible_rule_keys,
                }
            );


        } catch (error) {

            failClosed(
                error
            );
        }
    }


    // ========================================================
    // Reset stale quote when switching / closing an order
    // ========================================================

    document.addEventListener(
        "pointerdown",
        event => {

            const action =
                event.target.closest(
                    "button,a"
                );


            if (
                action
                && String(
                    action.textContent
                    || ""
                )
                .trim()
                .includes(
                    "開始設定"
                )
            ) {

                resetOrderState();


                setTimeout(
                    applyFilter,
                    0
                );


                setTimeout(
                    applyFilter,
                    120
                );
            }


            const close =
                event.target.closest(
                    "[data-order-close],"
                    + ".order3-close,"
                    + ".order3-dialog-close,"
                    + ".order3-modal-close"
                );


            if (close) {

                resetOrderState();
            }
        },
        true
    );


    document.addEventListener(
        "keydown",
        event => {

            if (
                event.key
                === "Escape"
            ) {

                resetOrderState();
            }
        },
        true
    );


    const variant =
        byId(
            "mw-variant"
        );


    if (variant) {

        new MWGuardNoopObserver(
            () => {

                filterVariants();
            }
        ).observe(
            variant,
            {
                childList:
                    true,

                subtree:
                    true,
            }
        );


        variant.addEventListener(
            "change",
            () => {

                resetOrderState();


                setTimeout(
                    filterVariants,
                    0
                );
            }
        );
    }


    // Final front-end protection before 取得價格.
    document.addEventListener(
        "click",
        event => {

            if (
                !filterData
                || !specifiedStaffId
            ) {

                return;
            }


            const priceButton =
                event.target.closest(
                    "#mw-next-step"
                );


            if (!priceButton) {

                return;
            }


            const ruleKey =
                String(
                    byId(
                        "mw-rule-key"
                    )?.textContent
                    || ""
                ).trim();


            if (
                ruleKey
                && !eligibleRules.has(
                    ruleKey
                )
            ) {

                event.preventDefault();

                event.stopImmediatePropagation();


                const error =
                    byId(
                        "mw-order-error"
                    );


                if (error) {

                    error.textContent =
                        "你指定的陪玩目前沒有這個方案的接單資格。";


                    error.hidden =
                        false;
                }
            }
        },
        true
    );


    resetOrderState();

    loadFilter();

})();
