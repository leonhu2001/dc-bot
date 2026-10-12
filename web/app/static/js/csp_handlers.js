(() => {
    "use strict";

    document.addEventListener("submit", (event) => {
        const form = event.target instanceof HTMLFormElement
            ? event.target
            : null;
        if (!form) return;
        const message = String(form.dataset.confirmMessage || "").trim();
        if (message && !window.confirm(message)) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, true);

    document.addEventListener("error", (event) => {
        const image = event.target instanceof HTMLImageElement
            ? event.target
            : null;
        if (!image) return;

        if (image.dataset.removeParentOnError === "true") {
            image.parentElement?.remove();
            return;
        }

        const fallbackSrc = String(image.dataset.fallbackSrc || "").trim();
        if (!fallbackSrc || image.dataset.fallbackApplied === "true") return;
        image.dataset.fallbackApplied = "true";
        const fallbackClass = String(image.dataset.fallbackClass || "").trim();
        if (fallbackClass) image.classList.add(fallbackClass);
        image.src = fallbackSrc;
    }, true);
})();
