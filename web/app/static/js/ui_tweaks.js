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

  function orderRulePageActive() {
    return window.location.pathname.startsWith("/admin/order-rules");
  }

  function syncOrderRulePublishUi(options = {}) {
    if (!orderRulePageActive()) return;

    const focusPreview = Boolean(options.focusPreview);
    const previewPanel = document.querySelector(".rule-preview-panel");
    const previewForm = document.querySelector('form[data-form-kind="preview"]');
    const previewButton = previewForm?.querySelector('button[type="submit"]');
    const saveBar = previewForm?.querySelector(".rule-save-bar");
    const state = document.querySelector("[data-rule-save-state]");

    if (previewButton) {
      previewButton.textContent = previewPanel
        ? "重新預覽變更"
        : "預覽並準備發布";
    }

    let shortcut = saveBar?.querySelector("[data-rule-publish-shortcut]");

    if (previewPanel && saveBar && previewPanel.dataset.stale !== "1") {
      if (!shortcut) {
        shortcut = document.createElement("button");
        shortcut.type = "button";
        shortcut.className = "button";
        shortcut.dataset.rulePublishShortcut = "1";
        shortcut.textContent = "確認發布";
        shortcut.addEventListener("click", () => {
          const publishButton = document.querySelector(
            '.rule-preview-panel form[data-form-kind="publish"] button[type="submit"]'
          );
          if (publishButton && !publishButton.disabled) {
            publishButton.click();
          }
        });
        saveBar.appendChild(shortcut);
      }

      if (state) {
        state.textContent = "預覽完成，可直接確認發布";
      }
    } else if (shortcut) {
      shortcut.remove();
    }

    if (
      previewPanel &&
      focusPreview &&
      previewPanel.dataset.autoFocused !== "1"
    ) {
      previewPanel.dataset.autoFocused = "1";
      window.requestAnimationFrame(() => {
        previewPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  function markOrderRulePreviewStale(event) {
    if (!orderRulePageActive()) return;

    const editForm = event.target.closest?.('form[data-form-kind="preview"]');
    const previewPanel = document.querySelector(".rule-preview-panel");
    if (!editForm || !previewPanel) return;

    previewPanel.dataset.stale = "1";
    previewPanel.classList.add("is-stale");

    previewPanel
      .querySelectorAll('form[data-form-kind="publish"] button[type="submit"]')
      .forEach((button) => {
        button.disabled = true;
        button.title = "內容已再次修改，請先重新預覽";
      });

    document.querySelector("[data-rule-publish-shortcut]")?.remove();

    const state = document.querySelector("[data-rule-save-state]");
    if (state) {
      state.textContent = "內容已再次修改，請重新預覽後再發布";
    }

    const previewButton = editForm.querySelector('button[type="submit"]');
    if (previewButton) {
      previewButton.textContent = "重新預覽變更";
    }
  }

  function setupOrderRulePublishFlow() {
    if (!orderRulePageActive()) return;

    syncOrderRulePublishUi({ focusPreview: Boolean(document.querySelector(".rule-preview-panel")) });

    document.addEventListener("input", markOrderRulePreviewStale);
    document.addEventListener("change", markOrderRulePreviewStale);

    const observer = new MutationObserver((mutations) => {
      const workspaceChanged = mutations.some((mutation) =>
        Array.from(mutation.addedNodes || []).some((node) => {
          if (!(node instanceof Element)) return false;
          return (
            node.matches("#order-rule-workspace") ||
            Boolean(node.querySelector?.(".rule-preview-panel"))
          );
        })
      );

      if (workspaceChanged) {
        syncOrderRulePublishUi({ focusPreview: true });
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  function run() {
    replaceVisibleText();
    simplifyStaffPage();
    setupOrderRulePublishFlow();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }

  setTimeout(() => {
    replaceVisibleText();
    simplifyStaffPage();
    syncOrderRulePublishUi();
  }, 300);
})();
