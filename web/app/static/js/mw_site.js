(() => {
    const button = document.querySelector(
        "[data-mobile-nav-button]"
    );

    const menu = document.querySelector(
        "[data-mobile-nav]"
    );

    if (button && menu) {
        button.addEventListener(
            "click",
            () => {
                const open =
                    menu.classList.toggle(
                        "is-open"
                    );

                button.setAttribute(
                    "aria-expanded",
                    open ? "true" : "false"
                );
            }
        );
    }

    document.addEventListener(
        "click",
        (event) => {
            document
                .querySelectorAll(
                    ".account-menu[open]"
                )
                .forEach(
                    (details) => {
                        if (
                            !details.contains(
                                event.target
                            )
                        ) {
                            details.removeAttribute(
                                "open"
                            );
                        }
                    }
                );
        }
    );

    const accountDropdown = document.querySelector(
        ".account-dropdown"
    );

    if (accountDropdown) {
        const logoutLink = accountDropdown.querySelector(
            '[href="/auth/logout"]'
        );

        const logoutDivider =
            logoutLink
                ? logoutLink.previousElementSibling
                : null;

        let walletLink = accountDropdown.querySelector(
            '[href="/me/wallet"]'
        );

        if (!walletLink) {
            walletLink = document.createElement(
                "a"
            );
            walletLink.href = "/me/wallet";
            walletLink.textContent = "我的錢包 / 儲值";
        }

        if (
            logoutDivider
            && logoutDivider.classList.contains(
                "account-divider"
            )
        ) {
            accountDropdown.insertBefore(
                walletLink,
                logoutDivider
            );
        } else if (logoutLink) {
            accountDropdown.insertBefore(
                walletLink,
                logoutLink
            );
        } else if (!walletLink.isConnected) {
            accountDropdown.appendChild(
                walletLink
            );
        }
    }

    // ORDER_RULE_PRESENTATION_STOREFRONT
    // 「備註」只顯示在商品卡外層；「簡介」只在點進商品後顯示。
    // 多方案商品若備註完全相同，外層可共用；簡介則跟著方案切換。
    const orderGroupsNode = document.getElementById(
        "mw-order-groups-data"
    );

    if (orderGroupsNode) {
        let orderGroups = [];

        try {
            orderGroups = JSON.parse(
                orderGroupsNode.textContent || "[]"
            );
        } catch (_) {
            orderGroups = [];
        }

        const orderGroupMap = new Map(
            orderGroups.map(
                (group) => [
                    String(group?.key || ""),
                    group,
                ]
            )
        );

        const normalizeCopy = (value) =>
            String(value || "")
                .replace(/\r\n?/g, "\n")
                .split("\n")
                .map((line) => line.trim())
                .filter(Boolean)
                .join("\n")
                .trim();

        const summarizeNote = (value) => {
            const full = normalizeCopy(value);

            if (!full) {
                return "";
            }

            const lines = full.split("\n");
            const visibleLines = lines.slice(0, 2);
            let summary = visibleLines.join("\n");
            let truncated = lines.length > visibleLines.length;

            if (summary.length > 90) {
                summary = summary.slice(0, 90).trimEnd();
                truncated = true;
            }

            return truncated
                ? `${summary}…`
                : summary;
        };

        orderGroups.forEach(
            (group) => {
                const variants = Array.isArray(group?.variants)
                    ? group.variants
                    : [];

                const notes = variants
                    .map((variant) => normalizeCopy(variant?.note))
                    .filter(Boolean);

                const note = (
                    variants.length === 1
                        ? (notes[0] || "")
                        : (
                            notes.length === variants.length
                            && notes.every((item) => item === notes[0])
                                ? notes[0]
                                : ""
                        )
                );

                if (!note) {
                    return;
                }

                const card = document.querySelector(
                    `[data-order-group-card="${CSS.escape(String(group.key || ""))}"]`
                );
                const copy = card?.querySelector(
                    ":scope > p"
                );

                if (!copy) {
                    return;
                }

                copy.textContent = summarizeNote(note);
                copy.style.whiteSpace = "pre-line";
            }
        );

        const dialogDescription = document.getElementById(
            "mw-dialog-description"
        );
        const variantSelect = document.getElementById(
            "mw-variant"
        );
        let activeOrderGroupKey = "";

        const syncDialogIntro = () => {
            if (!dialogDescription) {
                return;
            }

            const group = orderGroupMap.get(
                activeOrderGroupKey
            );

            if (!group) {
                return;
            }

            const variants = Array.isArray(group.variants)
                ? group.variants
                : [];
            const index = Math.max(
                0,
                Number(variantSelect?.selectedIndex || 0)
            );
            const variant = variants[index] || variants[0] || null;
            const intro = normalizeCopy(
                variant?.intro
            );

            dialogDescription.textContent =
                intro
                || String(group.description || "選擇適合你的方案。");
            dialogDescription.style.whiteSpace = "pre-line";
        };

        document
            .querySelectorAll(
                "[data-order-group]"
            )
            .forEach(
                (openButton) => {
                    openButton.addEventListener(
                        "click",
                        () => {
                            activeOrderGroupKey = String(
                                openButton.dataset.orderGroup || ""
                            );
                            syncDialogIntro();
                        }
                    );
                }
            );

        variantSelect?.addEventListener(
            "change",
            syncDialogIntro
        );
    }
})();
