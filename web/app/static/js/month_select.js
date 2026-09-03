(function () {
  async function fetchMonths() {
    const res = await fetch("/admin/month-options?t=" + Date.now(), {
      cache: "no-store",
      credentials: "same-origin"
    });

    if (!res.ok) return [];

    const data = await res.json();

    if (!data || !data.ok || !Array.isArray(data.months)) return [];

    return data.months;
  }

  function replaceMonthInput(input, months) {
    if (!input || input.dataset.monthSelectConverted === "1") return;
    if (!months.length) return;

    const select = document.createElement("select");
    select.name = input.name;
    select.className = input.className || "input";
    select.id = input.id || "";
    select.dataset.monthSelectConverted = "1";

    const currentValue = input.value || input.getAttribute("value") || "";
    const hasCurrent = months.some((month) => month.value === currentValue);

    for (const month of months) {
      const option = document.createElement("option");
      option.value = month.value;
      option.textContent = month.label;

      if (hasCurrent && month.value === currentValue) {
        option.selected = true;
      }

      select.appendChild(option);
    }

    // 沒有目前選擇時，自動選第一個月份，例如 2026年5月。
    if (!hasCurrent && select.options.length > 0) {
      select.selectedIndex = 0;
    }

    input.replaceWith(select);
  }

  async function run() {
    const inputs = Array.from(document.querySelectorAll('input[type="month"][name="month"]'));

    if (!inputs.length) return;

    const months = await fetchMonths();

    for (const input of inputs) {
      replaceMonthInput(input, months);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
