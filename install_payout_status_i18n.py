from pathlib import Path
import re

ROOT = Path(".")
JS_PATH = ROOT / "web" / "app" / "static" / "js" / "payout_status_i18n.js"
LAYOUT_PATH = ROOT / "web" / "app" / "templates" / "layout.html"

JS_PATH.parent.mkdir(parents=True, exist_ok=True)

JS_PATH.write_text(r'''
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
'''.strip() + "\n", encoding="utf-8")

if LAYOUT_PATH.exists():
    text = LAYOUT_PATH.read_text(encoding="utf-8")
    script = '<script src="/static/js/payout_status_i18n.js?v=1"></script>'

    text = re.sub(
        r'\s*<script[^>\n]*payout_status_i18n\.js[^>\n]*></script>',
        '',
        text,
    )

    if "</body>" in text:
        text = text.replace("</body>", script + "\n</body>", 1)
    else:
        text = text.rstrip() + "\n" + script + "\n"

    LAYOUT_PATH.write_text(text, encoding="utf-8")
    print("installed payout status i18n js")
else:
    print("layout.html not found")

print("done")
