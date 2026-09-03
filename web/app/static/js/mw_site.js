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
})();