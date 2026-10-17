// MAWAN_R13_FINAL_DATE_AUTOFILL
document.addEventListener("DOMContentLoaded", function () {
    const statusSelect = document.querySelector('select[name="status"]');
    const dateInput = document.querySelector('input[name="closed_date"]');
    const autoInput = document.querySelector('input[name="closed_date_auto"]');
    const touchedInput = document.querySelector('input[name="closed_date_touched"]');
    const cancellationFields = document.getElementById("mw-cancellation-reason-fields");

    if (!statusSelect || !dateInput || !autoInput || !touchedInput) {
        return;
    }

    function taipeiDate() {
        const parts = new Intl.DateTimeFormat("en-US", {
            timeZone: "Asia/Taipei",
            year: "numeric",
            month: "2-digit",
            day: "2-digit"
        }).formatToParts(new Date());
        const values = {};
        parts.forEach(function (part) {
            values[part.type] = part.value;
        });
        return values.year + "-" + values.month + "-" + values.day;
    }

    function syncFinalDate() {
        const isFinal = statusSelect.value === "closed" || statusSelect.value === "cancelled";
        if (cancellationFields) {
            cancellationFields.hidden = statusSelect.value !== "cancelled";
        }
        if (isFinal && !dateInput.value) {
            dateInput.value = taipeiDate();
            autoInput.value = "1";
        } else if (!isFinal && autoInput.value === "1") {
            dateInput.value = "";
            autoInput.value = "";
        }
    }

    statusSelect.addEventListener("change", syncFinalDate);
    dateInput.addEventListener("input", function () {
        autoInput.value = "";
        touchedInput.value = "1";
    });
    syncFinalDate();
});