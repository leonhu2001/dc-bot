// MAWAN_R13_FINAL_DATE_AUTOFILL
document.addEventListener("DOMContentLoaded", function () {
    const statusSelect = document.querySelector('select[name="status"]');
    const dateInput = document.querySelector('input[name="closed_date"]');
    const autoInput = document.querySelector('input[name="closed_date_auto"]');
    const touchedInput = document.querySelector('input[name="closed_date_touched"]');
    const cancellationFields = document.getElementById("mw-cancellation-reason-fields");

    function syncPayoutPolicyCopy() {
        document.querySelectorAll(".mw-r8-inline-form .mw-r8-check").forEach(function (label) {
            if (!label.textContent.includes("掛名 +5%")) {
                return;
            }
            Array.from(label.childNodes).forEach(function (node) {
                if (node.nodeType === Node.TEXT_NODE && node.nodeValue.includes("掛名 +5%")) {
                    node.nodeValue = node.nodeValue.replace(
                        "掛名 +5%",
                        "管理端修正掛名（新制 +3%；舊單依原制度）"
                    );
                }
            });
        });

        document.querySelectorAll(".mw-r8-editor-head h3").forEach(function (heading) {
            if (heading.textContent.trim() !== "接單人員與分潤") {
                return;
            }
            const paragraph = heading.parentElement && heading.parentElement.querySelector("p");
            if (paragraph) {
                paragraph.textContent = "新制為基礎 80%＋掛名 3%＋直播 2%＋前月已發放薪資達 5000T 次月 2%；掛名與直播以客服審核通過的報單為準，舊單保留原制度。此處保留管理端修正與手動分潤功能。";
            }
        });
    }

    syncPayoutPolicyCopy();

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