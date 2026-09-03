(() => {
    "use strict";


    const MAIN_ID =
        "mw-extra-requirements";


    const STORAGE_KEY =
        "mawan_order_extra_requirements";


    const STYLE_ID =
        "mw-extra-requirements-integrated-style";


    let applying =
        false;


    // ========================================================
    // CSS
    // ========================================================

    function ensureStyle() {

        if (
            document.getElementById(
                STYLE_ID
            )
        ) {
            return;
        }


        const style =
            document.createElement(
                "style"
            );


        style.id =
            STYLE_ID;


        style.textContent = `
            .mw-extra-requirements-box {
                position: relative !important;
                cursor: text !important;
                overflow: hidden !important;
            }

            .mw-extra-requirements-box
            #mw-extra-requirements {
                position: absolute !important;

                left: 18px !important;
                right: 18px !important;

                width: auto !important;

                min-width: 0 !important;
                max-width: none !important;

                min-height: 0 !important;
                height: auto !important;

                margin: 0 !important;
                padding: 0 !important;

                border: 0 !important;
                outline: 0 !important;
                box-shadow: none !important;

                resize: none !important;

                overflow-y: auto !important;

                background: transparent !important;

                color: inherit !important;

                font: inherit !important;
                line-height: 1.65 !important;

                z-index: 3 !important;

                pointer-events: auto !important;
            }

            .mw-extra-requirements-box
            #mw-extra-requirements::placeholder {
                opacity: .38 !important;
            }

            .mw-extra-requirements-label {
                position: relative !important;
                z-index: 4 !important;
                pointer-events: none !important;
            }
        `;


        document.head.appendChild(
            style
        );
    }


    // ========================================================
    // Find label
    // ========================================================

    function normalize(
        value
    ) {

        return String(
            value
            || ""
        )
        .replace(
            /\s+/g,
            ""
        )
        .trim();
    }


    function findLabel() {

        const elements =
            Array.from(
                document.querySelectorAll(
                    "body *"
                )
            );


        return (
            elements.find(
                element => {

                    if (
                        normalize(
                            element.textContent
                        )
                        !== "附加需求"
                    ) {
                        return false;
                    }


                    if (
                        element.children.length
                        > 3
                    ) {
                        return false;
                    }


                    const rect =
                        element
                        .getBoundingClientRect();


                    return (
                        rect.width > 0
                        && rect.height > 0
                    );
                }
            )
            || null
        );
    }


    // ========================================================
    // Find the ORIGINAL visual box
    // ========================================================

    function findOriginalBox(
        label
    ) {

        if (!label) {
            return null;
        }


        const labelRect =
            label
            .getBoundingClientRect();


        const candidates =
            [];


        let current =
            label.parentElement;


        for (
            let depth = 0;
            depth < 8 && current;
            depth += 1
        ) {

            const rect =
                current
                .getBoundingClientRect();


            const labelTopOffset =
                labelRect.top
                - rect.top;


            const labelLeftOffset =
                labelRect.left
                - rect.left;


            const text =
                String(
                    current.textContent
                    || ""
                );


            const looksLikeBox =
                (
                    rect.width >= 300
                    && rect.height >= 80
                    && rect.height <= 240

                    && labelTopOffset >= 0
                    && labelTopOffset <= 55

                    && labelLeftOffset >= 0
                    && labelLeftOffset <= 80

                    && !text.includes(
                        "CURRENT TOTAL"
                    )

                    && !text.includes(
                        "取得價格"
                    )

                    && !text.includes(
                        "陪玩人數"
                    )
                );


            if (looksLikeBox) {

                candidates.push(
                    {
                        element:
                            current,

                        area:
                            rect.width
                            * rect.height,

                        depth,
                    }
                );
            }


            current =
                current.parentElement;
        }


        if (
            candidates.length
            === 0
        ) {

            return (
                label.parentElement
                || null
            );
        }


        // Smallest valid visual container is normally
        // the exact existing "附加需求" card.
        candidates.sort(
            (
                a,
                b
            ) =>
                a.area
                - b.area
        );


        return (
            candidates[0]
            .element
        );
    }


    // ========================================================
    // Remove duplicates
    // ========================================================

    function removeDuplicateTextareas(
        keep
    ) {

        const candidates =
            Array.from(
                document.querySelectorAll(
                    [
                        "textarea#mw-extra-requirements",
                        "textarea[name='extra_requirements']",
                    ].join(",")
                )
            );


        for (
            const textarea
            of candidates
        ) {

            if (
                textarea
                === keep
            ) {
                continue;
            }


            textarea.remove();
        }
    }


    // ========================================================
    // Main
    // ========================================================

    function integrate() {

        if (applying) {
            return;
        }


        applying =
            true;


        try {

            ensureStyle();


            const label =
                findLabel();


            if (!label) {
                return;
            }


            const box =
                findOriginalBox(
                    label
                );


            if (!box) {
                return;
            }


            let textarea =
                document.getElementById(
                    MAIN_ID
                );


            if (
                textarea
                && textarea.tagName
                    .toLowerCase()
                    !== "textarea"
            ) {

                textarea.remove();

                textarea =
                    null;
            }


            if (!textarea) {

                textarea =
                    document.createElement(
                        "textarea"
                    );


                textarea.id =
                    MAIN_ID;


                textarea.name =
                    "extra_requirements";


                textarea.rows =
                    4;


                textarea.maxLength =
                    500;


                textarea.autocomplete =
                    "off";


                textarea.value =
                    sessionStorage.getItem(
                        STORAGE_KEY
                    )
                    || "";
            }


            textarea.disabled =
                false;


            textarea.readOnly =
                false;


            textarea.maxLength =
                500;


            textarea.placeholder =
                "可填寫稱呼、語音、打法或其他需求（選填）";


            // IMPORTANT:
            // Move the existing textarea INTO the original
            // visible card instead of creating another card.
            if (
                textarea.parentElement
                !== box
            ) {

                box.appendChild(
                    textarea
                );
            }


            removeDuplicateTextareas(
                textarea
            );


            box.classList.add(
                "mw-extra-requirements-box"
            );


            label.classList.add(
                "mw-extra-requirements-label"
            );


            // Position textarea below the existing label.
            const boxRect =
                box
                .getBoundingClientRect();


            const labelRect =
                label
                .getBoundingClientRect();


            const top =
                Math.max(
                    42,
                    Math.round(
                        labelRect.bottom
                        - boxRect.top
                        + 10
                    )
                );


            textarea.style.top =
                `${top}px`;


            textarea.style.bottom =
                "14px";


            // Preserve text across "取得價格".
            if (
                !textarea.dataset
                    .mwIntegratedBound
            ) {

                textarea.dataset
                    .mwIntegratedBound =
                        "1";


                textarea.addEventListener(
                    "input",
                    () => {

                        sessionStorage.setItem(
                            STORAGE_KEY,
                            textarea.value
                        );
                    }
                );
            }


            const stored =
                sessionStorage.getItem(
                    STORAGE_KEY
                );


            if (
                stored
                && !textarea.value
            ) {

                textarea.value =
                    stored;
            }


            if (
                box.dataset
                    .mwFocusBound
                !== "1"
            ) {

                box.dataset
                    .mwFocusBound =
                        "1";


                box.addEventListener(
                    "click",
                    event => {

                        if (
                            event.target
                            === textarea
                        ) {
                            return;
                        }


                        textarea.focus();
                    }
                );
            }


        } finally {

            applying =
                false;
        }
    }


    // ========================================================
    // Keep it correct after modal / variant rebuilding
    // ========================================================

    let scheduled =
        false;


    function scheduleIntegrate() {

        if (scheduled) {
            return;
        }


        scheduled =
            true;


        requestAnimationFrame(
            () => {

                scheduled =
                    false;

                integrate();
            }
        );
    }


    new MutationObserver(
        scheduleIntegrate
    ).observe(
        document.body,
        {
            childList:
                true,

            subtree:
                true,
        }
    );


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
                .includes(
                    "開始設定"
                )
            ) {

                setTimeout(
                    integrate,
                    20
                );


                setTimeout(
                    integrate,
                    120
                );
            }
        },
        true
    );


    setTimeout(
        integrate,
        0
    );


    setTimeout(
        integrate,
        100
    );


    setTimeout(
        integrate,
        300
    );

})();
