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
})();
