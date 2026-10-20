(() => {
    "use strict";

    function text(node) {
        return node ? String(node.textContent || "").replace(/\s+/g, " ").trim() : "";
    }

    function findPayoutCard() {
        return Array.from(document.querySelectorAll(".mw-r8-editor-card")).find((card) => {
            const heading = card.querySelector("h2, h3");
            return text(heading).includes("接單人員與分潤");
        }) || null;
    }

    function replaceCheckLabel(form, labelText) {
        if (!form) return;
        const label = form.querySelector(".mw-r8-check");
        const checkbox = label?.querySelector('input[type="checkbox"]');
        if (!label || !checkbox) return;
        label.replaceChildren(checkbox, document.createTextNode(" " + labelText));
    }

    function cleanup() {
        const card = findPayoutCard();
        if (!card) return;

        const headCopy = card.querySelector(".mw-r8-editor-head p");
        if (headCopy && /新制|舊單|80%|\+?3%|\+?2%/.test(text(headCopy))) {
            headCopy.textContent = "掛名與直播以核准報單為準；此處保留管理端修正與手動分潤功能。";
        }

        replaceCheckLabel(card.querySelector('form[action*="/named-bonus"]'), "管理端修正掛名");
        replaceCheckLabel(card.querySelector('form[action*="/stream-bonus"]'), "管理端修正直播");

        const streamForm = card.querySelector('form[action*="/stream-bonus"]');
        const streamMeta = streamForm?.querySelector(".mw-r8-meta");
        if (streamMeta && text(streamMeta).includes("需新制且報單審核通過")) {
            streamMeta.textContent = "需報單審核通過";
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", cleanup, { once: true });
    } else {
        cleanup();
    }
})();
