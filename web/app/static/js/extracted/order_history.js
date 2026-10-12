document.addEventListener("click", function (event) {
    const button = event.target.closest("button.history-dossier-toggle[data-dossier-target]");
    if (!button) return;

    const targetId = button.getAttribute("data-dossier-target");
    const row = document.getElementById(targetId);

    if (!row) return;

    const isHidden = row.hasAttribute("hidden");

    document.querySelectorAll(".history-dossier-detail-row").forEach(function (item) {
        if (item !== row) {
            item.setAttribute("hidden", "");
        }
    });

    document.querySelectorAll("button.history-dossier-toggle[data-dossier-target]").forEach(function (item) {
        if (item !== button) {
            item.textContent = "\u6aa2\u8996\u5377\u5b97";
        }
    });

    if (isHidden) {
        row.removeAttribute("hidden");
        button.textContent = "\u6536\u8d77\u5377\u5b97";
    } else {
        row.setAttribute("hidden", "");
        button.textContent = "\u6aa2\u8996\u5377\u5b97";
    }
});
