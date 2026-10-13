(() => {
    "use strict";

    const byId = id => document.getElementById(id);
    const groupsNode = byId("mw-order-groups-data");
    const contextNode = byId("mw-order-context-data");

    if (!groupsNode || !contextNode) {
        return;
    }

    function parseJson(node, fallback) {
        try {
            return JSON.parse(node?.textContent || "") || fallback;
        } catch (_) {
            return fallback;
        }
    }

    function clean(value) {
        return String(value || "").trim();
    }

    function isSnowflake(value) {
        return /^\d{15,22}$/.test(clean(value));
    }

    const groups = parseJson(groupsNode, []);
    const context = parseJson(contextNode, {});
    const specifiedStaffId = isSnowflake(context.specified_staff_id)
        ? clean(context.specified_staff_id)
        : "";
    const selectedStaffBanner = document.querySelector(".order3-specified");

    const groupRuleMap = new Map(
        groups.map(group => [
            clean(group.key),
            new Set(
                (group.variants || [])
                    .map(variant => clean(variant.rule_key))
                    .filter(Boolean),
            ),
        ]),
    );

    let eligibleRules = new Set();
    let filterReady = false;

    function resetOrderState() {
        window.dispatchEvent(new CustomEvent("mawan:order-reset"));
        sessionStorage.removeItem("mawan_order_draft");
        sessionStorage.removeItem("mawan_checkout_preview");
    }

    function cards() {
        return Array.from(
            document.querySelectorAll("[data-order-group-card]"),
        );
    }

    function setCardAllowed(card, allowed) {
        card.hidden = !allowed;
        card.dataset.mwRoleAllowed = allowed ? "1" : "0";
    }

    function rulesForCard(card) {
        return groupRuleMap.get(clean(card.dataset.orderGroupCard)) || new Set();
    }

    function filterCards() {
        if (!filterReady || !specifiedStaffId) {
            return;
        }

        for (const card of cards()) {
            const groupRules = rulesForCard(card);
            const allowed = Array.from(groupRules).some(ruleKey =>
                eligibleRules.has(ruleKey),
            );
            setCardAllowed(card, allowed);
        }
    }

    function ruleForOption(option) {
        return clean(
            option?.dataset?.ruleKey
            || option?.getAttribute("data-rule-key")
            || option?.value,
        );
    }

    function filterVariants() {
        if (!filterReady || !specifiedStaffId) {
            return;
        }

        const select = byId("mw-variant");
        if (!select) {
            return;
        }

        let firstAllowed = null;

        for (const option of Array.from(select.options)) {
            const ruleKey = ruleForOption(option);
            const allowed = Boolean(ruleKey && eligibleRules.has(ruleKey));

            option.hidden = !allowed;
            option.disabled = !allowed;

            if (allowed && !firstAllowed) {
                firstAllowed = option;
            }
        }

        const current = select.options[select.selectedIndex];
        const currentRule = ruleForOption(current);

        if (currentRule && eligibleRules.has(currentRule)) {
            return;
        }

        if (firstAllowed) {
            select.value = firstAllowed.value;
            select.dispatchEvent(new Event("change", {bubbles: true}));
        } else {
            select.selectedIndex = -1;
        }
    }

    function applyFilter() {
        filterCards();
        filterVariants();
    }

    function failClosed(message) {
        filterReady = true;
        eligibleRules = new Set();
        cards().forEach(card => setCardAllowed(card, false));
        filterVariants();
        console.error("[MAWAN STAFF FILTER]", message);
    }

    async function loadFilter() {
        if (!specifiedStaffId) {
            if (selectedStaffBanner) {
                failClosed(
                    "Selected staff is visible but specified_staff_id is missing from order context.",
                );
            }
            return;
        }

        try {
            const response = await fetch(
                "/order/staff-filter?staff_id="
                + encodeURIComponent(specifiedStaffId),
                {
                    cache: "no-store",
                    headers: {"Accept": "application/json"},
                },
            );
            const result = await response.json();

            if (!response.ok || !result.ok) {
                throw new Error(
                    result.error || "無法取得指定陪玩的接單資格。",
                );
            }

            eligibleRules = new Set(
                (result.data?.eligible_rule_keys || [])
                    .map(clean)
                    .filter(Boolean),
            );
            filterReady = true;
            applyFilter();

            console.info("[MAWAN STAFF FILTER READY]", {
                specified_staff_id: specifiedStaffId,
                eligible_rules: Array.from(eligibleRules),
            });
        } catch (error) {
            failClosed(error);
        }
    }

    document.addEventListener("pointerdown", event => {
        const open = event.target.closest("[data-order-group]");
        if (open) {
            resetOrderState();
            requestAnimationFrame(filterVariants);
            return;
        }

        const close = event.target.closest("#mw-dialog-close");
        if (close) {
            resetOrderState();
        }
    }, true);

    document.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            resetOrderState();
        }
    }, true);

    byId("mw-variant")?.addEventListener("change", () => {
        resetOrderState();
        requestAnimationFrame(filterVariants);
    });

    document.addEventListener("click", event => {
        if (!filterReady || !specifiedStaffId) {
            return;
        }

        const priceButton = event.target.closest("#mw-next-step");
        if (!priceButton) {
            return;
        }

        const ruleKey = clean(byId("mw-rule-key")?.textContent);
        if (!ruleKey || eligibleRules.has(ruleKey)) {
            return;
        }

        event.preventDefault();
        event.stopImmediatePropagation();

        const error = byId("mw-order-error");
        if (error) {
            error.textContent = "你指定的陪玩目前沒有這個方案的接單資格。";
            error.hidden = false;
        }
    }, true);

    resetOrderState();
    void loadFilter();
})();
