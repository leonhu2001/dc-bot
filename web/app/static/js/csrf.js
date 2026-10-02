(() => {
    "use strict";

    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = String(meta?.getAttribute("content") || "").trim();

    if (!token) {
        return;
    }

    const unsafe = new Set(["POST", "PUT", "PATCH", "DELETE"]);

    function sameOriginUrl(value) {
        try {
            return new URL(value || window.location.href, window.location.href).origin === window.location.origin;
        } catch (_) {
            return false;
        }
    }

    function secureForm(form) {
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        const method = String(form.method || "GET").toUpperCase();
        if (!unsafe.has(method)) {
            return;
        }

        if (!sameOriginUrl(form.action || window.location.href)) {
            return;
        }

        let input = form.querySelector('input[name="csrf_token"]');
        if (!input) {
            input = document.createElement("input");
            input.type = "hidden";
            input.name = "csrf_token";
            form.appendChild(input);
        }

        input.value = token;
    }

    document.querySelectorAll("form").forEach(secureForm);

    document.addEventListener(
        "submit",
        (event) => {
            secureForm(event.target);
        },
        true,
    );

    const observer = new MutationObserver((records) => {
        for (const record of records) {
            for (const node of record.addedNodes) {
                if (!(node instanceof Element)) {
                    continue;
                }

                if (node.matches?.("form")) {
                    secureForm(node);
                }

                node.querySelectorAll?.("form").forEach(secureForm);
            }
        }
    });

    observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
    });

    const originalFetch = window.fetch.bind(window);

    window.fetch = (input, init = {}) => {
        const request = input instanceof Request ? input : null;
        const method = String(
            init.method || request?.method || "GET",
        ).toUpperCase();

        const url = request?.url || input;

        if (!unsafe.has(method) || !sameOriginUrl(url)) {
            return originalFetch(input, init);
        }

        const headers = new Headers(
            init.headers || request?.headers || undefined,
        );

        if (!headers.has("X-CSRF-Token")) {
            headers.set("X-CSRF-Token", token);
        }

        return originalFetch(input, {
            ...init,
            headers,
        });
    };
})();
