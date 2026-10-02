(() => {
    "use strict";

    const body = document.body;
    if (!body || body.dataset.marketingDisabled === "1") {
        return;
    }

    function emit(eventName, properties = {}) {
        if (!eventName) return;

        fetch("/marketing/event", {
            method: "POST",
            credentials: "same-origin",
            keepalive: true,
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                event_name: eventName,
                path: window.location.pathname,
                properties,
            }),
        }).catch(() => {});
    }

    emit("page_view", {
        page: body.dataset.page || "",
    });

    if (body.dataset.page === "game_delta_force") {
        emit("landing_view", {
            game: "delta_force",
        });
    }

    document.addEventListener("click", (event) => {
        const target = event.target.closest("[data-funnel-event]");
        if (target) {
            emit(target.dataset.funnelEvent, {
                label: target.dataset.funnelLabel || "",
                href: target.getAttribute("href") || "",
            });
        }

        const group = event.target.closest("[data-order-group]");
        if (group) {
            emit("view_item", {
                group: group.dataset.orderGroup || "",
            });
        }

        const login = event.target.closest('a[href^="/auth/discord/login"]');
        if (login) {
            emit("login_click", {
                from: window.location.pathname,
            });
        }
    }, true);
})();
