document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-summary-target]");
    if (!button) return;

    const targetId = button.getAttribute("data-summary-target");
    const row = document.getElementById(targetId);
    if (!row) return;

    const isHidden = row.hasAttribute("hidden");

    document.querySelectorAll(".staff-summary-detail-row").forEach(function (item) {
        if (item !== row) item.setAttribute("hidden", "");
    });

    document.querySelectorAll("[data-summary-target]").forEach(function (item) {
        if (item !== button) item.textContent = "明細";
    });

    if (isHidden) {
        row.removeAttribute("hidden");
        button.textContent = "收起";
    } else {
        row.setAttribute("hidden", "");
        button.textContent = "明細";
    }
});
