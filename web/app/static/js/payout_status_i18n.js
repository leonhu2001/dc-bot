(function () {
  const map = {
    "unpaid": "未支付",
    "paid": "已支付",
    "pending": "待處理"
  };

  function translateTextNodes() {
    if (!document.body) return;

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];

    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }

    for (const node of nodes) {
      let value = node.nodeValue || "";
      const trimmed = value.trim();

      if (Object.prototype.hasOwnProperty.call(map, trimmed)) {
        node.nodeValue = value.replace(trimmed, map[trimmed]);
      }
    }
  }

  function translateBadges() {
    document.querySelectorAll("span, div, button, td, p, small, strong").forEach((el) => {
      const text = (el.textContent || "").trim();

      if (Object.prototype.hasOwnProperty.call(map, text)) {
        el.textContent = map[text];
      }
    });
  }

  function run() {
    translateTextNodes();
    translateBadges();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }

  setTimeout(run, 300);
  setTimeout(run, 1000);
})();
