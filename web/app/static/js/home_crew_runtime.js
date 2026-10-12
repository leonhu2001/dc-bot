(() => {
    "use strict";

    if (location.pathname !== "/") {
        return;
    }

    const normalize = value =>
        String(value || "").replace(/\s+/g, "").trim();

    const targets = [
        { label: "女陪", url: "/staff?role=female_companion" },
        { label: "男陪", url: "/staff?role=male_companion" },
        { label: "護航", url: "/staff?role=protector" },
    ];

    function findFigure(label) {
        for (const card of document.querySelectorAll(".crew-type-card")) {
            const heading = card.querySelector("h3");
            if (heading && normalize(heading.textContent) === normalize(label)) {
                return card.querySelector(".crew-figure");
            }
        }
        return null;
    }

    async function loadCrew(target) {
        const box = findFigure(target.label);
        if (!box) {
            return;
        }

        try {
            const response = await fetch(target.url, {
                credentials: "same-origin",
                cache: "no-store",
            });
            if (!response.ok) {
                return;
            }

            const documentCopy = new DOMParser().parseFromString(
                await response.text(),
                "text/html",
            );
            const seen = new Set();
            const items = [];

            documentCopy
                .querySelectorAll(".public-crew-card .public-crew-photo img[src]")
                .forEach(node => {
                    const src = String(node.getAttribute("src") || "").trim();
                    if (src && !seen.has(src) && items.length < 6) {
                        seen.add(src);
                        items.push([
                            src,
                            node.getAttribute("alt") || target.label,
                        ]);
                    }
                });

            if (!items.length) {
                return;
            }

            const grid = document.createElement("div");
            grid.className = "mw-r72-crew-avatars";

            for (const [src, alt] of items) {
                const figure = document.createElement("div");
                figure.className = "mw-r72-crew-avatar";

                const image = document.createElement("img");
                image.src = src;
                image.alt = alt;
                image.loading = "lazy";
                image.decoding = "async";

                figure.appendChild(image);
                grid.appendChild(figure);
            }

            box.replaceChildren(grid);
            box.classList.add("mw-r72-crew-figure-ready");
        } catch (error) {
            console.warn(
                "[MAWAN R7.2] crew avatars skipped",
                target.label,
                error,
            );
        }
    }

    targets.forEach(loadCrew);
})();
