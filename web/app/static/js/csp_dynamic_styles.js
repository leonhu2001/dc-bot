(() => {
    "use strict";

    const percent = (value) => {
        const number = Number(value);
        if (!Number.isFinite(number)) return 0;
        return Math.max(0, Math.min(100, number));
    };

    document.querySelectorAll("[data-csp-width-percent]").forEach((element) => {
        element.style.width = `${percent(element.dataset.cspWidthPercent)}%`;
    });

    document.querySelectorAll("[data-csp-share-percent]").forEach((element) => {
        element.style.setProperty("--share", `${percent(element.dataset.cspSharePercent)}%`);
    });
})();
