(() => {
    "use strict";

    if (window.__MAWAN_ORDER_UI__) {
        return;
    }
    window.__MAWAN_ORDER_UI__ = true;

    const EXTRA_KEY = "mawan_order_extra_requirements";
    const ruleCache = new Map();
    let ruleRequest = 0;
    let backgroundLocked = false;

    const byId = id => document.getElementById(id);
    const clean = value => String(value || "").trim();

    function visible(element) {
        if (!element || element.hidden) {
            return false;
        }
        const rect = element.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) {
            return false;
        }
        const computed = window.getComputedStyle(element);
        return computed.display !== "none" && computed.visibility !== "hidden";
    }

    function orderWindowOpen() {
        return visible(byId("mw-variant"));
    }

    function syncBackgroundLock() {
        const shouldLock = orderWindowOpen();
        if (shouldLock === backgroundLocked) {
            return;
        }
        backgroundLocked = shouldLock;
        document.documentElement.classList.toggle("mw-order-open", shouldLock);
        document.body.classList.toggle("mw-order-open", shouldLock);
    }

    function isRecordingKeeperText(value) {
        const text = clean(value);
        return text.includes("錄影") && text.includes("保留者");
    }

    function stripExampleSuffix(value) {
        return clean(value)
            .replace(
                /\s*(?:（|\()?(?:例|例如|範例)\s*[:：].*?(?:）|\))?\s*$/u,
                "",
            )
            .trim();
    }

    function hasRecordingKeeperContext(element) {
        let current = element;
        for (let depth = 0; depth < 4 && current; depth += 1) {
            if (isRecordingKeeperText(current.textContent)) {
                return true;
            }
            current = current.parentElement;
        }
        return false;
    }

    function sanitizeRecordingKeeperCopy(root = document) {
        root.querySelectorAll("input[placeholder], textarea[placeholder]").forEach(element => {
            const current = String(element.getAttribute("placeholder") || "");
            if (!isRecordingKeeperText(current) && !hasRecordingKeeperContext(element)) {
                return;
            }
            const next = stripExampleSuffix(current);
            if (next && !/^(?:例|例如|範例)\s*[:：]/u.test(next)) {
                element.setAttribute("placeholder", next);
            } else {
                element.removeAttribute("placeholder");
            }
        });

        root.querySelectorAll("label, span, small, p, strong").forEach(element => {
            if (element.children.length) {
                return;
            }
            const current = String(element.textContent || "");
            if (!isRecordingKeeperText(current)) {
                return;
            }
            const next = stripExampleSuffix(current);
            if (next && next !== current.trim()) {
                element.textContent = next;
            }
        });
    }

    function sanitizeDescriptionText(value) {
        const text = clean(value);
        if (!text) {
            return text;
        }

        const internalTerms = [
            "身分組",
            "智慧派單",
            "派單只通知",
            "派單通知",
            "可接人員",
            "required_staff",
            "rule key",
        ];

        const clauses = text
            .split(/[；;]/u)
            .map(part => clean(part))
            .filter(Boolean)
            .filter(part => !internalTerms.some(term => part.toLowerCase().includes(term.toLowerCase())));

        if (!clauses.length) {
            return "選擇適合你的方案。";
        }

        return clauses
            .join("；")
            .replace(/[。；;]+$/u, "") + "。";
    }

    function sanitizeCatalogDescriptions() {
        document.querySelectorAll(".order3-card > p, #mw-dialog-description").forEach(element => {
            const current = clean(element.textContent);
            const next = sanitizeDescriptionText(current);
            if (next && next !== current) {
                element.textContent = next;
            }
        });
    }

    function removePublicInternalHints() {
        [
            ".order3-debug",
            ".order3-info",
            ".order3-verified-badge",
            ".order3-server-title > div > small",
            ".order-checkout-preview-badge",
            ".order-checkout-head p",
            ".order-checkout-terms > small",
            "#mw-next-notice",
            "#mw-checkout-final-note",
        ].forEach(selector => {
            document.querySelectorAll(selector).forEach(element => element.remove());
        });

        document
            .querySelectorAll(".order-checkout-account > div > small:not(#mw-checkout-vip-note)")
            .forEach(element => element.remove());

        const pointNote = byId("mw-checkout-point-note");
        if (
            pointNote
            && clean(pointNote.textContent).includes("伺服器重新驗證資格")
        ) {
            pointNote.remove();
        }
    }

    function sanitizePublicCopy() {
        removePublicInternalHints();
        sanitizeCatalogDescriptions();
        sanitizeRecordingKeeperCopy(byId("mw-order-dialog") || document);
    }

    function setupExtraRequirements() {
        const field = byId("mw-adjustments-field");
        const adjustments = byId("mw-adjustments");
        if (!field || !adjustments) {
            return;
        }

        field.hidden = false;
        let textarea = byId("mw-extra-requirements");
        if (!textarea) {
            textarea = document.createElement("textarea");
            textarea.id = "mw-extra-requirements";
            textarea.name = "extra_requirements";
            textarea.rows = 4;
            textarea.maxLength = 500;
            textarea.autocomplete = "off";
            textarea.placeholder = "可填寫稱呼、語音、打法或其他需求（選填）";
            textarea.value = sessionStorage.getItem(EXTRA_KEY) || "";
            adjustments.insertAdjacentElement("afterend", textarea);
        }

        textarea.disabled = false;
        textarea.readOnly = false;

        if (textarea.dataset.mwBound !== "1") {
            textarea.dataset.mwBound = "1";
            textarea.addEventListener("input", () => {
                sessionStorage.setItem(EXTRA_KEY, textarea.value);
            });
        }
    }

    function clearExtraRequirements() {
        sessionStorage.removeItem(EXTRA_KEY);
        const textarea = byId("mw-extra-requirements");
        if (textarea) {
            textarea.value = "";
        }
    }

    function currentRuleKey() {
        const direct = byId("mw-rule-key");
        if (direct) {
            const directValue = clean(
                direct.value
                || direct.dataset?.ruleKey
                || direct.textContent
            );
            if (directValue) {
                return directValue;
            }
        }

        const select = byId("mw-variant");
        if (select && select.selectedIndex >= 0) {
            const option = select.options[select.selectedIndex];
            return clean(
                option?.dataset?.ruleKey
                || option?.getAttribute("data-rule-key")
                || option?.value
            );
        }
        return "";
    }

    async function loadRuleMeta(ruleKey) {
        if (ruleCache.has(ruleKey)) {
            return ruleCache.get(ruleKey);
        }

        const response = await fetch(
            "/order/rule-ui-meta?rule_key=" + encodeURIComponent(ruleKey),
            {cache: "no-store"},
        );
        const result = await response.json();
        if (!response.ok || !result.ok) {
            throw new Error(result.error || "rule meta failed");
        }
        ruleCache.set(ruleKey, result.data);
        return result.data;
    }

    function playerUI() {
        const field = byId("mw-player-field");
        if (!field) {
            return null;
        }

        const minus = byId("mw-player-minus");
        const plus = byId("mw-player-plus");
        let value = (
            byId("mw-player-value")
            || byId("mw-player-count")
            || field.querySelector("input[name='player_count']")
        );

        if (!value) {
            const stepper = field.querySelector(".order3-stepper");
            if (stepper) {
                value = Array.from(stepper.children).find(element => {
                    if (element === minus || element === plus) {
                        return false;
                    }
                    return /^\d+$/.test(clean(element.textContent));
                }) || null;
            }
        }

        return {field, minus, plus, value};
    }

    function writePlayerCount(ui, value) {
        const count = Math.max(1, Number.parseInt(value, 10) || 1);
        if (ui?.value) {
            if ("value" in ui.value) {
                ui.value.value = String(count);
            } else {
                ui.value.textContent = String(count);
            }
        }
        document.querySelectorAll("input[name='player_count']").forEach(input => {
            input.value = String(count);
        });
    }

    function setDisabled(button, disabled) {
        if (!button) {
            return;
        }
        button.disabled = Boolean(disabled);
        button.setAttribute("aria-disabled", disabled ? "true" : "false");
    }

    function setFixedPlayerNote(ui, fixed) {
        ui.field.classList.toggle("mw-fixed-player-count", fixed);
        const oldNote = ui.field.querySelector(".mw-fixed-player-note");
        if (!fixed) {
            oldNote?.remove();
            return;
        }
        if (oldNote) {
            return;
        }
        const label = ui.field.querySelector("span");
        if (!label) {
            return;
        }
        const note = document.createElement("small");
        note.className = "mw-fixed-player-note";
        note.textContent = "固定";
        label.appendChild(note);
    }

    async function refreshPlayerRule() {
        const ruleKey = currentRuleKey();
        if (!ruleKey) {
            return;
        }

        const serial = ++ruleRequest;
        try {
            const meta = await loadRuleMeta(ruleKey);
            if (serial !== ruleRequest) {
                return;
            }

            const ui = playerUI();
            if (!ui) {
                return;
            }

            const editable = Boolean(meta.player_count_enabled);
            if (!editable) {
                const fixed = Math.max(
                    1,
                    Number.parseInt(meta.fixed_player_count, 10) || 1,
                );
                writePlayerCount(ui, fixed);
            }

            setDisabled(ui.minus, !editable);
            setDisabled(ui.plus, !editable);
            setFixedPlayerNote(ui, !editable);
        } catch (error) {
            console.error("[MAWAN PLAYER RULE]", error);
        }
    }

    function refreshModal() {
        setupExtraRequirements();
        sanitizePublicCopy();
        void refreshPlayerRule();
        syncBackgroundLock();
    }

    document.addEventListener("click", event => {
        const open = event.target.closest(".order3-open");
        if (open) {
            clearExtraRequirements();
            requestAnimationFrame(refreshModal);
            return;
        }
        if (backgroundLocked) {
            requestAnimationFrame(syncBackgroundLock);
        }
        requestAnimationFrame(sanitizePublicCopy);
    });

    document.addEventListener("change", event => {
        if (event.target?.id !== "mw-variant") {
            return;
        }
        requestAnimationFrame(() => {
            setupExtraRequirements();
            sanitizePublicCopy();
            void refreshPlayerRule();
        });
    });

    document.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            requestAnimationFrame(syncBackgroundLock);
        }
    });

    requestAnimationFrame(() => {
        setupExtraRequirements();
        sanitizePublicCopy();
        syncBackgroundLock();
    });
})();