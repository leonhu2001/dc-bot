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

    if (
        accountDropdown
        && !accountDropdown.querySelector(
            '[href="/me/wallet"]'
        )
    ) {
        const vipLink = accountDropdown.querySelector(
            '[href="/me#vip"]'
        );

        const walletLink = document.createElement(
            "a"
        );

        walletLink.href = "/me/wallet";
        walletLink.textContent = "我的錢包 / 儲值";

        if (vipLink) {
            accountDropdown.insertBefore(
                walletLink,
                vipLink
            );
        } else {
            accountDropdown.appendChild(
                walletLink
            );
        }
    }
})();
