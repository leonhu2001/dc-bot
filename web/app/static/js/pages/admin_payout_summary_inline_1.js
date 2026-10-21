(() => {
    if (document.querySelector('link[data-payout-summary-layout="1"]')) return;

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/css/pages/admin_payout_summary_layout.css?v=20261022-1";
    link.dataset.payoutSummaryLayout = "1";
    document.head.appendChild(link);
})();

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
