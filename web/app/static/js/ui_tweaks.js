(function () {
  function replaceText(node, fromText, toText) {
    if (!node || !node.nodeValue) return;
    if (node.nodeValue.includes(fromText)) {
      node.nodeValue = node.nodeValue.replaceAll(fromText, toText);
    }
  }

  function replaceVisibleText() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];

    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }

    for (const node of nodes) {
      replaceText(node, "目前active的同步人員。", "目前可接單的同步人員。");
      replaceText(node, "客服 / 總控", "客服");
      replaceText(node, "客服/總控", "客服");
      replaceText(node, "有客服或總控身分組。", "有客服身分組。");

      const trimmed = (node.nodeValue || "").trim();
      if (trimmed === "active") {
        node.nodeValue = node.nodeValue.replace("active", "可接單");
      }
    }
  }

  function simplifyStaffFilters() {
    if (!window.location.pathname.startsWith("/admin/staff")) return;

    const selects = Array.from(document.querySelectorAll("select"));
    if (!selects.length) return;

    let roleSelect = null;
    let statusSelect = null;

    for (const select of selects) {
      const optionTexts = Array.from(select.options).map((o) => (o.textContent || "").trim());

      if (
        optionTexts.includes("客服 / 總控") ||
        optionTexts.includes("客服/總控") ||
        optionTexts.includes("打手") ||
        optionTexts.includes("陪玩")
      ) {
        roleSelect = select;
      }

      if (
        optionTexts.includes("全部狀態") ||
        optionTexts.includes("啟用") ||
        optionTexts.includes("停用")
      ) {
        statusSelect = select;
      }
    }

    if (roleSelect) {
      Array.from(roleSelect.options).forEach((option) => {
        const text = (option.textContent || "").trim();

        if (text === "全部身份") {
          option.textContent = "全部";
        } else if (text === "客服 / 總控" || text === "客服/總控") {
          option.textContent = "客服";
        }
      });

      const keep = new Set(["全部", "客服", "打手", "陪玩"]);
      Array.from(roleSelect.options).forEach((option) => {
        const text = (option.textContent || "").trim();
        if (!keep.has(text)) {
          option.remove();
        }
      });
    }

    if (statusSelect) {
      const wrapper =
        statusSelect.closest(".filter-field") ||
        statusSelect.closest(".form-group") ||
        statusSelect.closest("label") ||
        statusSelect.parentElement;

      if (wrapper) {
        wrapper.style.display = "none";
      } else {
        statusSelect.style.display = "none";
      }
    }

    document.querySelectorAll("button, a, span, div").forEach((el) => {
      const text = (el.textContent || "").trim();
      if (text === "啟用") {
        const cls = (el.className || "").toString().toLowerCase();
        if (
          cls.includes("badge") ||
          cls.includes("pill") ||
          cls.includes("tag") ||
          cls.includes("chip")
        ) {
          el.style.display = "none";
        }
      }
    });
  }

  function forceStatsToOneLine() {
    if (!window.location.pathname.startsWith("/admin/staff")) return;

    const cards = Array.from(document.querySelectorAll("div, section"))
      .filter((el) => {
        const text = (el.textContent || "").replace(/\s+/g, " ");
        return (
          text.includes("啟用人員") &&
          text.includes("客服") &&
          text.includes("打手") &&
          text.includes("陪玩")
        );
      });

    if (!cards.length) return;

    const container = cards[0];
    const children = Array.from(container.children);

    if (children.length >= 4) {
      container.style.display = "grid";
      container.style.gridTemplateColumns = "repeat(4, minmax(0, 1fr))";
      container.style.gap = "12px";
      container.style.alignItems = "stretch";
    }
  }

  function run() {
    replaceVisibleText();
    simplifyStaffFilters();
    forceStatsToOneLine();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }

  setTimeout(run, 300);
  setTimeout(run, 1000);
})();
