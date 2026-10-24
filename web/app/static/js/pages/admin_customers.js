(function () {
    "use strict";

    const path =
        window.location.pathname;

    if (
        path !== "/admin/customers"
        &&
        !path.startsWith(
            "/admin/customers/"
        )
    ) {
        return;
    }

    const normalize = (value) =>
        String(value || "")
            .toLowerCase()
            .replace(/\s+/g, "")
            .replace(/[／/|｜·・:：()（）【】[\]「」『』]/g, "");

    const legacy =
        document.querySelector(
            ".mw-r5-legacy-body"
        )
        ||
        document.querySelector(
            "main"
        )
        ||
        document.body;

    const main =
        legacy.closest(
            "main"
        )
        ||
        document.querySelector(
            "main"
        );

    document.body.classList.add(
        "mw-r56-customer-page"
    );

    legacy.classList.add(
        "mw-r56-customer-legacy"
    );

    if (main) {
        main.classList.add(
            "mw-r56-customer-main"
        );
    }


    /*
     * ======================================================
     * 隱藏重複標題
     * ======================================================
     */

    const hideDuplicateHeader = (
        englishText
    ) => {
        const wanted =
            normalize(
                englishText
            );

        const candidates =
            Array.from(
                legacy.querySelectorAll(
                    "header,section,div"
                )
            ).filter(
                (node) => {
                    const text =
                        normalize(
                            node.innerText
                            ||
                            ""
                        );

                    return (
                        text.includes(
                            wanted
                        )
                        &&
                        text.length < 260
                        &&
                        node.querySelectorAll(
                            "input,table,form"
                        ).length
                        === 0
                    );
                }
            );

        candidates
            .sort(
                (
                    a,
                    b
                ) =>
                    (
                        a.innerText
                        ||
                        ""
                    ).length
                    -
                    (
                        b.innerText
                        ||
                        ""
                    ).length
            )
            .slice(
                0,
                1
            )
            .forEach(
                (node) =>
                    node.classList.add(
                        "mw-r56-duplicate-header"
                    )
            );
    };


    const commonAncestor = (
        a,
        b
    ) => {
        if (!a) {
            return b;
        }

        if (!b) {
            return a;
        }

        let node =
            a;

        while (
            node
            &&
            node !== document.body
        ) {
            if (
                node.contains(b)
            ) {
                return node;
            }

            node = node.parentElement;
        }

        return null;
    };


    /*
     * ======================================================
     * 把工作區一路往外撐滿
     * ======================================================
     */

    const widenChain = (
        node
    ) => {
        let current =
            node;

        const stop =
            main
            ?
            main.parentElement
            :
            document.body;

        while (
            current
            &&
            current !== stop
            &&
            current !== document.body
        ) {
            current.classList.add(
                "mw-r56-customer-expand"
            );

            current = current.parentElement;
        }

        if (main) {
            main.classList.add(
                "mw-r56-customer-expand"
            );
        }
    };


    const markWideStructuralChildren = (
        root
    ) => {
        if (!root) {
            return;
        }

        Array.from(
            root.children
        ).forEach(
            (child) => {
                const text =
                    normalize(
                        child.innerText
                        ||
                        ""
                    );

                const useful =
                    child.querySelector(
                        "table, form, input, select"
                    )
                    ||
                    text.includes(
                        "近期服務訂單"
                    )
                    ||
                    text.includes(
                        "近期訂單"
                    )
                    ||
                    text.includes(
                        "評價紀錄"
                    )
                    ||
                    text.includes(
                        "staffworkspace"
                    );

                if (useful) {
                    child.classList.add(
                        "mw-r56-customer-wide-block"
                    );
                }
            }
        );
    };


    /*
     * ======================================================
     * 客戶管理列表
     * ======================================================
     */

    const setupList = () => {
        hideDuplicateHeader(
            "CUSTOMER MANAGEMENT"
        );

        const search =
            Array.from(
                legacy.querySelectorAll(
                    "input"
                )
            ).find(
                (input) => {
                    const text =
                        normalize(
                            (
                                input.getAttribute(
                                    "placeholder"
                                )
                                ||
                                ""
                            )
                            +
                            " "
                            +
                            (
                                input.getAttribute(
                                    "name"
                                )
                                ||
                                ""
                            )
                        );

                    return (
                        text.includes(
                            "客戶"
                        )
                        ||
                        text.includes(
                            "discord"
                        )
                    );
                }
            );

        const customerLink =
            legacy.querySelector(
                'a[href*="/admin/customers/"]'
            );

        const table =
            legacy.querySelector(
                "table"
            );

        const root =
            commonAncestor(
                search || table,
                customerLink || table
            )
            ||
            legacy;

        root.classList.add(
            "mw-r56-customer-list-root"
        );

        widenChain(
            root
        );

        markWideStructuralChildren(
            root
        );

        if (search) {
            const form =
                search.closest(
                    "form"
                );

            if (form) {
                form.classList.add(
                    "mw-r56-customer-search"
                );
            }
        }

        if (table) {
            table.classList.add(
                "mw-r56-customer-table"
            );
        }
    };


    /*
     * ======================================================
     * 人員工作區
     * ======================================================
     */

    const setupDetail = () => {
        hideDuplicateHeader(
            "CUSTOMER WORKSPACE"
        );

        legacy.classList.add(
            "mw-r56-customer-detail-root"
        );

        widenChain(
            legacy
        );

        markWideStructuralChildren(
            legacy
        );

        const headings =
            Array.from(
                legacy.querySelectorAll(
                    "h2,h3,h4,strong"
                )
            );

        headings.forEach(
            (heading) => {
                const text =
                    normalize(
                        heading.textContent
                    );

                if (
                    text.includes(
                        "近期訂單"
                    )
                    ||
                    text.includes(
                        "近期服務訂單"
                    )
                    ||
                    text.includes(
                        "評價紀錄"
                    )
                ) {
                    const panel =
                        heading.closest(
                            '[class*="panel"], [class*="card"], section, article, div'
                        );

                    if (panel) {
                        panel.classList.add(
                            "mw-r56-customer-wide-panel"
                        );

                        widenChain(
                            panel
                        );
                    }
                }
            }
        );

        const labels = [
            "訂單",
            "完成",
            "取消",
            "進行中",
            "累計消費",
            "收藏",
            "評價",
        ];

        const metricCards =
            [];

        labels.forEach(
            (label) => {
                const node =
                    Array.from(
                        legacy.querySelectorAll(
                            "*"
                        )
                    ).find(
                        (element) =>
                            element.children.length
                            === 0
                            &&
                            normalize(
                                element.textContent
                            )
                            ===
                            normalize(label)
                    );

                if (!node) {
                    return;
                }

                const card =
                    node.closest(
                        '[class*="card"], [class*="metric"], [class*="stat"], div'
                    );

                if (
                    card
                    &&
                    !metricCards.includes(
                        card
                    )
                ) {
                    metricCards.push(
                        card
                    );

                    card.classList.add(
                        "mw-r56-customer-metric"
                    );
                }
            }
        );

        if (
            metricCards.length >= 2
        ) {
            const grid =
                metricCards[0]
                    .parentElement;

            if (
                grid
                &&
                metricCards.every(
                    (card) =>
                        grid.contains(
                            card
                        )
                )
            ) {
                grid.classList.add(
                    "mw-r56-customer-metric-grid"
                );

                widenChain(
                    grid
                );
            }
        }
    };


    if (
        path === "/admin/customers"
    ) {
        setupList();

    } else {
        setupDetail();
    }

})();
