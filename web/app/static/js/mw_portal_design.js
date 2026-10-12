
/* MAWAN_PORTAL_DESIGN_SYSTEM_R3 */

(() => {

    "use strict";


    const path =
        window.location.pathname;


    const isAdmin =
        path === "/admin"
        || path.startsWith(
            "/admin/"
        );


    const isEmployee =
        path === "/employee"
        || path.startsWith(
            "/dispatch"
        )
        || path.startsWith(
            "/my/payouts"
        );


    if (
        !isAdmin
        && !isEmployee
    ) {

        return;

    }


    const pages = [

        {
            match:
                value =>
                    value
                    === "/admin",

            kicker:
                "CUSTOMER SERVICE BACKOFFICE",

            title:
                "客服後台",

            description:
                "訂單、客戶與目前營運狀態集中查看。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/admin/orders/history"
                    ),

            kicker:
                "ORDER MANAGEMENT",

            title:
                "訂單管理",

            description:
                "搜尋、篩選與查看完整訂單紀錄。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/admin/order-workspace"
                    )
                    || (
                        value.startsWith(
                            "/admin/orders/"
                        )
                        && !value.startsWith(
                            "/admin/orders/history"
                        )
                    ),

            kicker:
                "ORDER WORKSPACE",

            title:
                "訂單工作區",

            description:
                "查看訂單內容、客服處理狀態與相關紀錄。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/admin/staff"
                    ),

            kicker:
                "STAFF MANAGEMENT",

            title:
                "人員管理",

            description:
                "管理店內人員、身分、個人牆與服務紀錄。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/admin/customers"
                    )
                    || value.startsWith(
                        "/admin/wallets"
                    ),

            kicker:
                "CUSTOMER MANAGEMENT",

            title:
                "客戶管理",

            description:
                "訂單、收藏、評價與錢包資料集中管理。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/admin/payout"
                    ),

            kicker:
                "PAYOUT MANAGEMENT",

            title:
                "薪資結算",

            description:
                "檢視人員薪資、結算狀態與歷史紀錄。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/admin/reviews"
                    ),

            kicker:
                "REVIEW MANAGEMENT",

            title:
                "評價管理",

            description:
                "查看、篩選與管理客戶留下的服務評價。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/admin/audit"
                    ),

            kicker:
                "AUDIT LOG",

            title:
                "操作紀錄",

            description:
                "查看客服後台的重要操作與系統紀錄。"
        },


        {
            match:
                value =>
                    value === "/employee",

            kicker:
                "STAFF CENTER",

            title:
                "員工中心",

            description:
                "查看自己的服務狀態，快速進入接單、薪資與個人中心。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/dispatch"
                    ),

            kicker:
                "ORDER DISPATCH",

            title:
                "接單大廳",

            description:
                "查看符合目前身分的可接訂單，以及自己已接的訂單。"
        },


        {
            match:
                value =>
                    value.startsWith(
                        "/my/payouts"
                    ),

            kicker:
                "PAYOUT CENTER",

            title:
                "完整薪資",

            description:
                "依月份查看服務薪資、結算狀態與完整明細。"
        }

    ];


    const page =
        pages.find(
            item =>
                item.match(
                    path
                )
        )
        || {
            kicker:
                isAdmin
                    ? "MOWAN OPERATIONS"
                    : "MOWAN STAFF",

            title:
                isAdmin
                    ? "客服後台"
                    : "員工中心",

            description:
                ""
        };


    document.body.classList.add(
        "mw-portal"
    );


    if (
        isAdmin
    ) {

        document.body.classList.add(
            "mw-portal-admin"
        );

    }


    if (
        path === "/employee"
    ) {

        document.body.classList.add(
            "mw-portal-employee"
        );

    }


    if (
        path.startsWith(
            "/dispatch"
        )
    ) {

        document.body.classList.add(
            "mw-portal-dispatch"
        );

    }


    if (
        path.startsWith(
            "/my/payouts"
        )
    ) {

        document.body.classList.add(
            "mw-portal-payout"
        );

    }


    function escapeHtml(
        value
    ) {

        const div =
            document.createElement(
                "div"
            );


        div.textContent =
            String(
                value
            );


        return div.innerHTML;

    }


    /*
     * --------------------------------------------------------
     * Locate existing portal structure.
     * --------------------------------------------------------
     */

    let main =
        document.querySelector(
            ".main"
        )
        || document.querySelector(
            ".dashboard-main"
        )
        || document.querySelector(
            ".content-main"
        )
        || document.querySelector(
            "main"
        );


    if (
        !main
    ) {

        main =
            document.createElement(
                "main"
            );


        while (
            document.body.firstChild
        ) {

            main.appendChild(
                document.body.firstChild
            );

        }


        document.body.appendChild(
            main
        );

    }


    main.classList.add(
        "mw-portal-main"
    );


    let sidebar =
        document.querySelector(
            "aside.sidebar"
        )
        || document.querySelector(
            ".sidebar"
        );


    let shell =
        main.parentElement;


    if (
        !shell
        || shell === document.body
    ) {

        shell =
            document.createElement(
                "div"
            );


        shell.className =
            "mw-portal-shell";


        document.body.insertBefore(
            shell,
            main
        );


        shell.appendChild(
            main
        );

    }


    shell.classList.add(
        "mw-portal-shell"
    );


    /*
     * --------------------------------------------------------
     * Sidebar.
     * --------------------------------------------------------
     */

    const adminLinks = [

        [
            "/admin",
            "營運總覽",
            value =>
                value
                === "/admin"
        ],

        [
            "/admin/orders/history",
            "訂單管理",
            value =>
                value.startsWith(
                    "/admin/orders"
                )
                || value.startsWith(
                    "/admin/order-workspace"
                )
        ],

        [
            "/admin/staff",
            "人員管理",
            value =>
                value.startsWith(
                    "/admin/staff"
                )
        ],

        [
            "/admin/customers",
            "客戶管理",
            value =>
                value.startsWith(
                    "/admin/customers"
                )
                || value.startsWith(
                    "/admin/wallets"
                )
        ],

        [
            "/admin/payouts/summary",
            "薪資結算",
            value =>
                value.startsWith(
                    "/admin/payout"
                )
        ],

        [
            "/admin/reviews/",
            "評價管理",
            value =>
                value.startsWith(
                    "/admin/reviews"
                )
        ],

        [
            "/admin/audit",
            "操作紀錄",
            value =>
                value.startsWith(
                    "/admin/audit"
                )
        ],

        [
            "/",
            "返回官網",
            () =>
                false
        ]

    ];


    const employeeLinks = [

        [
            "/employee",
            "員工中心",
            value =>
                value
                === "/employee"
        ],

        [
            "/dispatch",
            "接單大廳",
            value =>
                value.startsWith(
                    "/dispatch"
                )
        ],

        [
            "/my/payouts",
            "完整薪資",
            value =>
                value.startsWith(
                    "/my/payouts"
                )
        ],

        [
            "/me",
            "個人中心",
            () =>
                false
        ],

        [
            "/",
            "返回官網",
            () =>
                false
        ]

    ];


    const links =
        isAdmin
            ? adminLinks
            : employeeLinks;


    const newSidebar =
        document.createElement(
            "aside"
        );


    newSidebar.className =
        "mw-portal-sidebar";


    const navHtml =
        links
        .map(
            (
                [
                    href,
                    label,
                    current
                ]
            ) => {

                const active =
                    current(
                        path
                    )
                        ? " active"
                        : "";


                return (
                    '<a class="'
                    + active.trim()
                    + '" href="'
                    + escapeHtml(
                        href
                    )
                    + '">'
                    + escapeHtml(
                        label
                    )
                    + "</a>"
                );

            }
        )
        .join(
            ""
        );


    newSidebar.innerHTML =
        `
        <div class="mw-portal-brand">

            <small>
                ${isAdmin
                    ? "MOWAN OPERATIONS"
                    : "MOWAN STAFF"}
            </small>

            <strong>
                魔丸娛樂
            </strong>

        </div>

        <nav class="mw-portal-navigation">
            ${navHtml}
        </nav>
        `;


    if (
        sidebar
    ) {

        sidebar.replaceWith(
            newSidebar
        );

    }
    else {

        shell.insertBefore(
            newSidebar,
            main
        );

    }


    /*
     * --------------------------------------------------------
     * Move old header action buttons.
     * --------------------------------------------------------
     */

    const actionContainer =
        document.createElement(
            "div"
        );


    actionContainer.className =
        "mw-standard-actions";


    const possibleActionSelectors = [

        ".top .actions",
        ".top-actions",
        ".page-actions",
        ".hero-actions",
        ".header-actions"

    ];


    for (
        const selector
        of possibleActionSelectors
    ) {

        const oldActions =
            main.querySelector(
                selector
            );


        if (
            !oldActions
        ) {

            continue;

        }


        while (
            oldActions.firstChild
        ) {

            actionContainer.appendChild(
                oldActions.firstChild
            );

        }

    }


    /*
     * --------------------------------------------------------
     * Standard page header.
     * --------------------------------------------------------
     */

    const header =
        document.createElement(
            "header"
        );


    header.className =
        "mw-standard-header";


    header.innerHTML =
        `
        <div>

            <div class="mw-standard-kicker">
                ${escapeHtml(
                    page.kicker
                )}
            </div>

            <h1 class="mw-standard-title">
                ${escapeHtml(
                    page.title
                )}
            </h1>

            <p class="mw-standard-description">
                ${escapeHtml(
                    page.description
                )}
            </p>

        </div>
        `;


    if (
        actionContainer.children.length
        > 0
    ) {

        header.appendChild(
            actionContainer
        );

    }


    main.insertBefore(
        header,
        main.firstChild
    );


    /*
     * --------------------------------------------------------
     * Remove visual duplication from original page heading.
     * Preserve page functionality and controls.
     * --------------------------------------------------------
     */

    const headingSelectors = [

        ":scope > .top",
        ":scope > header.top",
        ":scope > .page-header",
        ":scope > .page-head"

    ];


    for (
        const selector
        of headingSelectors
    ) {

        let node =
            null;


        try {

            node =
                main.querySelector(
                    selector
                );

        }
        catch (
            error
        ) {

            node =
                null;

        }


        if (
            !node
        ) {

            continue;

        }


        if (
            node === header
        ) {

            continue;

        }


        node.remove();

    }


    /*
     * Heading sections where the container itself contains
     * useful stats / filters. Hide only heading text.
     */

    const mixedHeaderSelectors = [

        ".history-ledger-hero",
        ".staff-summary-hero",
        ".my-payout-intro",
        ".dispatch-hero-main",
        ".employee-hero"

    ];


    for (
        const selector
        of mixedHeaderSelectors
    ) {

        const node =
            main.querySelector(
                selector
            );


        if (
            !node
        ) {

            continue;

        }


        node.classList.add(
            "mw-old-page-header"
        );


        const headings =
            node.querySelectorAll(
                [
                    "h1",
                    ".eyebrow",
                    ".page-kicker",
                    ".hero-kicker",
                    ".page-title"
                ].join(
                    ","
                )
            );


        headings.forEach(
            item => {

                item.classList.add(
                    "mw-old-page-heading"
                );

            }
        );

    }


    /*
     * --------------------------------------------------------
     * Employee homepage launchpad.
     * --------------------------------------------------------
     */

    if (
        path === "/employee"
        && !main.querySelector(
            ".mw-employee-launchpad"
        )
    ) {

        const launchpad =
            document.createElement(
                "section"
            );


        launchpad.className =
            "mw-employee-launchpad";


        launchpad.innerHTML =
            `
            <a
                class="mw-launch-card"
                href="/dispatch"
            >

                <div>

                    <small>
                        ORDER DISPATCH
                    </small>

                    <strong>
                        接單大廳
                    </strong>

                    <p>
                        查看目前可以接的訂單與自己的進行中訂單。
                    </p>

                </div>

                <span class="mw-launch-arrow">
                    →
                </span>

            </a>


            <a
                class="mw-launch-card"
                href="/my/payouts"
            >

                <div>

                    <small>
                        PAYOUT CENTER
                    </small>

                    <strong>
                        完整薪資
                    </strong>

                    <p>
                        查看本月薪資、結算狀態與歷史服務明細。
                    </p>

                </div>

                <span class="mw-launch-arrow">
                    →
                </span>

            </a>


            <a
                class="mw-launch-card"
                href="/me"
            >

                <div>

                    <small>
                        PROFILE CENTER
                    </small>

                    <strong>
                        個人中心
                    </strong>

                    <p>
                        查看自己的帳號、訂單、收藏、VIP、點數與錢包。
                    </p>

                </div>

                <span class="mw-launch-arrow">
                    →
                </span>

            </a>
            `;


        header.insertAdjacentElement(
            "afterend",
            launchpad
        );

    }


    /*
     * --------------------------------------------------------
     * Remove duplicate old navigation labels.
     * --------------------------------------------------------
     */

    document
    .querySelectorAll(
        "a"
    )
    .forEach(
        link => {

            if (
                link.closest(
                    ".mw-portal-sidebar"
                )
            ) {

                return;

            }


            const text =
                (
                    link.textContent
                    || ""
                ).trim();


            if (
                text
                === "會員中心"
            ) {

                link.textContent =
                    "個人中心";

            }

        }
    );

})();
