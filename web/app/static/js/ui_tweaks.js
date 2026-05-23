(function () {
  function replaceVisibleText() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];

    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }

    for (const node of nodes) {
      const raw = node.nodeValue || "";
      const trimmed = raw.trim();

      if (trimmed === "active") {
        node.nodeValue = raw.replace("active", "可接單");
      }

      if (raw.includes("客服 / 總控")) {
        node.nodeValue = raw.replaceAll("客服 / 總控", "客服");
      }

      if (raw.includes("客服/總控")) {
        node.nodeValue = raw.replaceAll("客服/總控", "客服");
      }
    }
  }

  function simplifyStaffPage() {
    if (!window.location.pathname.startsWith("/admin/staff")) return;

    document.querySelectorAll("select option").forEach((option) => {
      const text = option.textContent.trim();

      if (text === "全部身份") {
        option.remove();
      }

      if (text === "客服 / 總控" || text === "客服/總控") {
        option.textContent = "客服";
      }

      if (text === "啟用" || text === "停用" || text === "全部狀態") {
        const select = option.closest("select");
        if (select) {
          select.dataset.staffStatusSelect = "1";
        }
      }
    });

    document.querySelectorAll("select[data-staff-status-select='1']").forEach((select) => {
      select.disabled = true;

      const wrapper =
        select.closest(".filter-field") ||
        select.closest(".form-group") ||
        select.closest("label") ||
        select.parentElement;

      if (wrapper) {
        wrapper.style.display = "none";
      } else {
        select.style.display = "none";
      }
    });

    document.querySelectorAll("button, a, span, .badge, .pill").forEach((el) => {
      if ((el.textContent || "").trim() === "啟用") {
        el.style.display = "none";
      }
    });
  }

  function run() {
    replaceVisibleText();
    simplifyStaffPage();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }

  setTimeout(run, 300);
})();
