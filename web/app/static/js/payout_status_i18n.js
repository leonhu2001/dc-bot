(function () {
  const exactMap = {
    "unpaid": "未支付",
    "paid": "已支付",
    "pending": "待處理",
    "pending_review": "待審核",
    "approved": "已核准",
    "rejected": "已拒絕",
    "failed": "失敗",
    "error": "異常",
    "warning": "注意",
    "critical": "嚴重異常",
    "success": "正常",
    "healthy": "正常",
    "unknown": "未知",
    "open": "開啟",
    "closed": "已關閉",
    "active": "啟用中",
    "inactive": "已停用",
    "enabled": "已啟用",
    "disabled": "已停用",
    "waiting_acceptance": "等待接單",
    "accepted_pending_pay": "已接滿・待付款",
    "pending_payment": "待付款",
    "stored": "已存單",
    "cancelled": "已取消",
    "completed": "已完成",
    "SUCCESS": "正常",
    "ERROR": "異常",
    "WARNING": "注意",
    "CRITICAL": "嚴重異常",
    "HEALTHY": "正常",
    "ORDER MANAGEMENT": "訂單管理",
    "STAFF OPERATIONS": "人員作業",
    "CUSTOMER OPERATIONS": "客戶作業",
    "FINANCE OPERATIONS": "財務作業",
    "SUPPORT OPERATIONS": "客服作業",
    "GLOBAL SEARCH": "全域搜尋",
    "CUSTOMER WALLET": "客戶錢包",
    "WALLET LEDGER": "錢包流水",
    "PRODUCT RULES": "商品規則",
    "MARKETING FUNNEL": "行銷漏斗",
    "SYSTEM OPERATIONS": "系統維運",
    "PAYMENT REVIEW": "付款審核",
    "OPERATIONS & FINANCE": "營運與財務",
    "TICKET ARCHIVE": "票口封存",
    "PAYOUT MANAGEMENT": "薪資結算",
    "REVIEW MANAGEMENT": "評價管理",
    "ACCOUNTING RECONCILIATION": "帳務對帳",
    "AI SUPPORT KNOWLEDGE": "AI 客服知識",
    "AI OPERATIONS ANALYSIS": "AI 營運分析",
    "SYSTEM HEALTH": "系統健康",
    "AUDIT LOG": "操作紀錄",
    "ORDER DISPATCH": "接單大廳",
    "PAYOUT CENTER": "薪資中心",
    "CUSTOMER SERVICE BACKOFFICE": "客服後台",
    "EMPLOYEE WORKSPACE": "員工作業區",
    "Discord Bot": "Discord 機器人",
    "Web Dashboard": "網站後台",
    "Branch": "程式分支",
    "Working tree": "工作目錄狀態",
    "PID": "程序編號",
    "Stage": "執行環境",
    "Ticket": "票口",
    "SLA": "回應時限"
  };

  const phraseMap = [
    ["Discord ID", "Discord 使用者 ID"],
    ["Ticket ID", "票口 ID"],
    ["Working tree", "工作目錄狀態"],
    ["Web Dashboard", "網站後台"],
    ["Discord Bot", "Discord 機器人"],
    ["Critical", "嚴重異常"],
    ["Warning", "注意"],
    ["Error", "異常"]
  ];

  function shouldSkipNode(node) {
    const parent = node.parentElement;
    if (!parent) return false;
    return ["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA"].includes(parent.tagName);
  }

  function translateValue(value) {
    const trimmed = value.trim();
    if (!trimmed) return value;

    if (Object.prototype.hasOwnProperty.call(exactMap, trimmed)) {
      return value.replace(trimmed, exactMap[trimmed]);
    }

    let translated = value;
    for (const [source, target] of phraseMap) {
      if (translated.includes(source)) {
        translated = translated.replaceAll(source, target);
      }
    }

    // Static templates are UTF-8 clean. If a legacy/database value still carries
    // the Unicode replacement glyph, show an explicit Chinese fallback instead
    // of leaving an unreadable black-diamond/question-mark sequence on screen.
    if (translated.includes("\uFFFD")) {
      translated = translated.replace(/\uFFFD+/g, "〔文字編碼異常〕");
    }

    return translated;
  }

  function translateTextNodes() {
    if (!document.body) return;

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];

    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }

    for (const node of nodes) {
      if (shouldSkipNode(node)) continue;
      const value = node.nodeValue || "";
      const translated = translateValue(value);
      if (translated !== value) {
        node.nodeValue = translated;
      }
    }
  }

  function translateBadges() {
    document.querySelectorAll("span, div, button, td, p, small, strong, option, label").forEach((el) => {
      if (el.children.length) return;
      const text = (el.textContent || "").trim();

      if (Object.prototype.hasOwnProperty.call(exactMap, text)) {
        el.textContent = exactMap[text];
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

  let queued = false;
  const observer = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    window.setTimeout(() => {
      queued = false;
      run();
    }, 30);
  });

  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener("DOMContentLoaded", () => {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  }

  setTimeout(run, 300);
  setTimeout(run, 1000);
})();
