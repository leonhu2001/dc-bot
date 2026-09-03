(() => {
    "use strict";

    if (
        window.__MAWAN_STABLE_VARIANT_3210R__
    ) {
        return;
    }

    window.__MAWAN_STABLE_VARIANT_3210R__ =
        true;


    const ROOT_CLASS =
        "mw-variant-custom-root";

    const TRIGGER_CLASS =
        "mw-variant-custom-trigger";

    const MENU_CLASS =
        "mw-variant-custom-menu";

    const ITEM_CLASS =
        "mw-variant-custom-item";

    const HIDDEN_CLASS =
        "mw-native-variant-hidden";


    let activeMenu = null;
    let activeTrigger = null;


    function clean(
        value
    ) {

        return String(
            value
            || ""
        ).trim();
    }


    // ========================================================
    // Style
    // ========================================================

    const style =
        document.createElement(
            "style"
        );


    style.textContent = `
        select#mw-variant.${HIDDEN_CLASS} {
            position: absolute !important;

            width: 1px !important;
            height: 1px !important;

            min-width: 1px !important;
            min-height: 1px !important;

            margin: 0 !important;
            padding: 0 !important;

            opacity: 0 !important;

            pointer-events: none !important;

            clip-path: inset(50%) !important;
        }

        .${ROOT_CLASS} {
            position: relative;
            width: 100%;
        }

        .${TRIGGER_CLASS} {
            display: flex;
            align-items: center;
            justify-content: space-between;

            gap: 14px;

            width: 100%;
            min-height: 46px;

            box-sizing: border-box;

            padding: 0 15px;

            border:
                1px solid
                rgba(255, 255, 255, .11);

            border-radius: 10px;

            background:
                rgba(255, 255, 255, .018);

            color: inherit;

            font: inherit;

            text-align: left;

            cursor: pointer;

            outline: none;
        }

        .${TRIGGER_CLASS}:hover {
            border-color:
                rgba(224, 187, 102, .38);
        }

        .${TRIGGER_CLASS}:focus-visible {
            border-color:
                rgba(224, 187, 102, .65);
        }

        .${TRIGGER_CLASS}[disabled] {
            opacity: .45;
            cursor: not-allowed;
        }

        .mw-variant-custom-label {
            flex: 1 1 auto;
            min-width: 0;

            overflow: hidden;
            white-space: nowrap;
            text-overflow: ellipsis;
        }

        .mw-variant-custom-arrow {
            flex: 0 0 auto;

            opacity: .75;

            font-size: 11px;

            transition:
                transform .14s ease;
        }

        .${TRIGGER_CLASS}[aria-expanded="true"]
        .mw-variant-custom-arrow {
            transform: rotate(180deg);
        }

        .${MENU_CLASS} {
            position: fixed;

            box-sizing: border-box;

            max-height: 330px;

            overflow-y: auto;

            padding: 6px;

            border:
                1px solid
                rgba(224, 187, 102, .32);

            border-radius: 10px;

            background:
                #111113;

            box-shadow:
                0 20px 55px
                rgba(0, 0, 0, .58);

            z-index: 2147483000;

            overscroll-behavior: contain;
        }

        .${ITEM_CLASS} {
            display: block;

            width: 100%;

            box-sizing: border-box;

            padding: 11px 12px;

            border: 0;
            border-radius: 7px;

            background: transparent;

            color: inherit;

            font: inherit;
            line-height: 1.45;

            text-align: left;

            cursor: pointer;
        }

        .${ITEM_CLASS}:hover,
        .${ITEM_CLASS}:focus-visible {
            background:
                rgba(224, 187, 102, .12);

            outline: none;
        }

        .${ITEM_CLASS}.is-selected {
            background:
                rgba(224, 187, 102, .19);
        }

        .mw-variant-custom-empty {
            padding: 12px;

            opacity: .55;

            font-size: 13px;
        }
    `;


    document.head.appendChild(
        style
    );


    // ========================================================
    // Options
    // ========================================================

    function eligibleOptions(
        select
    ) {

        return Array.from(
            select.options
        )
        .filter(
            option => {

                if (
                    option.disabled
                    || option.hidden
                ) {
                    return false;
                }


                if (
                    window
                        .getComputedStyle(
                            option
                        )
                        .display
                    === "none"
                ) {
                    return false;
                }


                return true;
            }
        );
    }


    function currentOption(
        select
    ) {

        if (
            !select
            || select.selectedIndex < 0
        ) {
            return null;
        }


        return (
            select.options[
                select.selectedIndex
            ]
            || null
        );
    }


    // ========================================================
    // Close
    // ========================================================

    function closeMenu() {

        if (
            activeMenu
            && activeMenu.isConnected
        ) {

            activeMenu.remove();
        }


        if (
            activeTrigger
        ) {

            activeTrigger.setAttribute(
                "aria-expanded",
                "false"
            );
        }


        activeMenu =
            null;

        activeTrigger =
            null;
    }


    // ========================================================
    // Position
    // ========================================================

    function positionMenu(
        menu,
        trigger
    ) {

        const rect =
            trigger
            .getBoundingClientRect();


        const margin = 8;


        menu.style.width =
            `${Math.round(
                rect.width
            )}px`;


        menu.style.left =
            `${Math.round(
                Math.max(
                    margin,
                    Math.min(
                        rect.left,
                        window.innerWidth
                        - rect.width
                        - margin
                    )
                )
            )}px`;


        const availableBelow =
            window.innerHeight
            - rect.bottom
            - margin;


        const menuHeight =
            Math.min(
                330,
                menu.scrollHeight
            );


        if (
            availableBelow >= menuHeight
            || availableBelow >= rect.top
        ) {

            menu.style.top =
                `${Math.round(
                    rect.bottom + 4
                )}px`;


        } else {

            menu.style.top =
                `${Math.round(
                    Math.max(
                        margin,
                        rect.top
                        - menuHeight
                        - 4
                    )
                )}px`;
        }
    }


    // ========================================================
    // Select option
    // ========================================================

    function chooseOption(
        select,
        option
    ) {

        if (
            !select
            || !option
            || option.disabled
            || option.hidden
        ) {
            return;
        }


        select.value =
            option.value;


        select.dispatchEvent(
            new Event(
                "input",
                {
                    bubbles:
                        true,
                }
            )
        );


        select.dispatchEvent(
            new Event(
                "change",
                {
                    bubbles:
                        true,
                }
            )
        );


        updateSelect(
            select
        );


        closeMenu();
    }


    // ========================================================
    // Open menu
    // ========================================================

    function openMenu(
        select,
        trigger
    ) {

        closeMenu();


        const options =
            eligibleOptions(
                select
            );


        const menu =
            document.createElement(
                "div"
            );


        menu.className =
            MENU_CLASS;


        menu.setAttribute(
            "role",
            "listbox"
        );


        if (
            options.length === 0
        ) {

            const empty =
                document.createElement(
                    "div"
                );


            empty.className =
                "mw-variant-custom-empty";


            empty.textContent =
                "目前沒有可選方案";


            menu.appendChild(
                empty
            );


        } else {

            for (
                const option
                of options
            ) {

                const item =
                    document.createElement(
                        "button"
                    );


                item.type =
                    "button";


                item.className =
                    ITEM_CLASS;


                item.textContent =
                    clean(
                        option.textContent
                    );


                item.setAttribute(
                    "role",
                    "option"
                );


                if (
                    option.selected
                ) {

                    item.classList.add(
                        "is-selected"
                    );


                    item.setAttribute(
                        "aria-selected",
                        "true"
                    );


                } else {

                    item.setAttribute(
                        "aria-selected",
                        "false"
                    );
                }


                // Keep modal/card-level handlers away
                // from the dropdown interaction.
                for (
                    const eventName
                    of [
                        "pointerdown",
                        "mousedown",
                        "mouseup",
                    ]
                ) {

                    item.addEventListener(
                        eventName,
                        event => {

                            event.stopPropagation();
                        }
                    );
                }


                item.addEventListener(
                    "click",
                    event => {

                        event.preventDefault();

                        event.stopPropagation();


                        chooseOption(
                            select,
                            option
                        );
                    }
                );


                menu.appendChild(
                    item
                );
            }
        }


        document.body.appendChild(
            menu
        );


        activeMenu =
            menu;

        activeTrigger =
            trigger;


        trigger.setAttribute(
            "aria-expanded",
            "true"
        );


        positionMenu(
            menu,
            trigger
        );
    }


    // ========================================================
    // Update custom trigger
    // ========================================================

    function updateSelect(
        select
    ) {

        if (!select) {
            return;
        }


        const parent =
            select.parentElement;


        if (!parent) {
            return;
        }


        const root =
            parent.querySelector(
                `:scope > .${ROOT_CLASS}`
            );


        if (!root) {
            return;
        }


        const trigger =
            root.querySelector(
                `.${TRIGGER_CLASS}`
            );


        const label =
            root.querySelector(
                ".mw-variant-custom-label"
            );


        if (
            !trigger
            || !label
        ) {
            return;
        }


        const current =
            currentOption(
                select
            );


        label.textContent =
            current
            ? clean(
                current.textContent
            )
            : "選擇方案";


        trigger.disabled =
            eligibleOptions(
                select
            ).length === 0;
    }


    // ========================================================
    // Mount
    // ========================================================

    function mountSelect() {

        const select =
            document.getElementById(
                "mw-variant"
            );


        if (!select) {
            return;
        }


        const parent =
            select.parentElement;


        if (!parent) {
            return;
        }


        let root =
            parent.querySelector(
                `:scope > .${ROOT_CLASS}`
            );


        if (!root) {

            root =
                document.createElement(
                    "div"
                );


            root.className =
                ROOT_CLASS;


            const trigger =
                document.createElement(
                    "button"
                );


            trigger.type =
                "button";


            trigger.className =
                TRIGGER_CLASS;


            trigger.setAttribute(
                "aria-haspopup",
                "listbox"
            );


            trigger.setAttribute(
                "aria-expanded",
                "false"
            );


            const label =
                document.createElement(
                    "span"
                );


            label.className =
                "mw-variant-custom-label";


            const arrow =
                document.createElement(
                    "span"
                );


            arrow.className =
                "mw-variant-custom-arrow";


            arrow.textContent =
                "▼";


            trigger.appendChild(
                label
            );


            trigger.appendChild(
                arrow
            );


            root.appendChild(
                trigger
            );


            parent.insertBefore(
                root,
                select
            );


            for (
                const eventName
                of [
                    "pointerdown",
                    "mousedown",
                    "mouseup",
                ]
            ) {

                trigger.addEventListener(
                    eventName,
                    event => {

                        event.stopPropagation();
                    }
                );
            }


            trigger.addEventListener(
                "click",
                event => {

                    event.preventDefault();

                    event.stopPropagation();


                    if (
                        activeTrigger
                        === trigger
                        && activeMenu
                    ) {

                        closeMenu();

                        return;
                    }


                    openMenu(
                        select,
                        trigger
                    );
                }
            );
        }


        select.classList.add(
            HIDDEN_CLASS
        );


        if (
            select.dataset
                .mwStableVariantBound
            !== "1"
        ) {

            select.dataset
                .mwStableVariantBound =
                    "1";


            select.addEventListener(
                "change",
                () => {

                    updateSelect(
                        select
                    );


                    closeMenu();
                }
            );
        }


        updateSelect(
            select
        );


        console.info(
            "[MAWAN STABLE VARIANT]",
            {
                total:
                    select.options.length,

                eligible:
                    eligibleOptions(
                        select
                    ).length,

                selected:
                    select.value,
            }
        );
    }


    // ========================================================
    // Outside events
    // ========================================================

    document.addEventListener(
        "pointerdown",
        event => {

            if (!activeMenu) {
                return;
            }


            if (
                activeMenu.contains(
                    event.target
                )
                || activeTrigger
                    ?.contains(
                        event.target
                    )
            ) {
                return;
            }


            closeMenu();
        }
    );


    document.addEventListener(
        "keydown",
        event => {

            if (
                event.key
                === "Escape"
            ) {

                closeMenu();
            }
        }
    );


    window.addEventListener(
        "resize",
        () => {

            if (
                activeMenu
                && activeTrigger
            ) {

                positionMenu(
                    activeMenu,
                    activeTrigger
                );
            }
        }
    );


    // ========================================================
    // Modal / variant events
    // ========================================================

    document.addEventListener(
        "pointerdown",
        event => {

            const action =
                event.target.closest(
                    "button,a"
                );


            if (
                !action
                || !clean(
                    action.textContent
                ).includes(
                    "開始設定"
                )
            ) {
                return;
            }


            closeMenu();


            setTimeout(
                mountSelect,
                50
            );


            setTimeout(
                mountSelect,
                160
            );


            setTimeout(
                mountSelect,
                300
            );
        },
        true
    );


    document.addEventListener(
        "change",
        event => {

            if (
                event.target?.id
                === "mw-variant"
            ) {

                setTimeout(
                    mountSelect,
                    0
                );
            }
        }
    );


    window.addEventListener(
        "mawan:order-reset",
        closeMenu
    );


    setTimeout(
        mountSelect,
        150
    );

})();
