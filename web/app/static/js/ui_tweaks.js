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

  function addOrderRuleDirectPublish() {
    if (!window.location.pathname.startsWith("/admin/order-rules")) return;

    const editForm = document.querySelector("form[data-rule-edit-form]");
    const saveBar = editForm?.querySelector(".rule-save-bar");
    if (!editForm || !saveBar || saveBar.querySelector("[data-rule-direct-publish]")) return;

    const previewButton = saveBar.querySelector('button[type="submit"]');
    if (!previewButton) return;

    const actions = document.createElement("div");
    actions.className = "rule-save-actions";
    actions.style.display = "flex";
    actions.style.gap = "8px";
    actions.style.flexWrap = "wrap";
    actions.style.justifyContent = "flex-end";

    previewButton.classList.add("secondary");
    previewButton.parentNode.insertBefore(actions, previewButton);
    actions.appendChild(previewButton);

    const publishButton = document.createElement("button");
    publishButton.type = "button";
    publishButton.className = "button";
    publishButton.dataset.ruleDirectPublish = "1";
    publishButton.textContent = "直接發布";
    actions.appendChild(publishButton);

    publishButton.addEventListener("click", async () => {
      if (!window.confirm("確定直接發布目前修改嗎？系統仍會先驗證規則，發布後 Web 與 Discord Bot 會使用新版本。")) {
        return;
      }

      previewButton.disabled = true;
      publishButton.disabled = true;
      publishButton.textContent = "發布中…";

      try {
        const previewResponse = await fetch(editForm.action, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-Requested-With": "order-rules-direct-publish" },
          body: new FormData(editForm),
        });
        const previewHtml = await previewResponse.text();
        const previewDoc = new DOMParser().parseFromString(previewHtml, "text/html");

        if (!previewResponse.ok) {
          throw new Error(`preview HTTP ${previewResponse.status}`);
        }

        const publishForm = previewDoc.querySelector('form[data-form-kind="publish"]');
        if (!publishForm) {
          const message =
            previewDoc.querySelector(".rule-alert--error p")?.textContent?.trim() ||
            "規則驗證未通過，請檢查欄位後再發布。";
          window.alert(message);
          return;
        }

        const publishAction = publishForm.getAttribute("action");
        if (!publishAction) {
          throw new Error("publish action missing");
        }

        const publishResponse = await fetch(publishAction, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-Requested-With": "order-rules-direct-publish" },
          body: new FormData(publishForm),
        });

        if (!publishResponse.ok) {
          throw new Error(`publish HTTP ${publishResponse.status}`);
        }

        window.location.assign(publishResponse.url || window.location.href);
      } catch (error) {
        console.error("[order-rules] direct publish failed", error);
        window.alert("直接發布失敗，請重新整理後再試一次；原本的預覽發布流程仍可使用。");
      } finally {
        previewButton.disabled = false;
        publishButton.disabled = false;
        publishButton.textContent = "直接發布";
      }
    });
  }

  function observeOrderRuleDirectPublish() {
    if (!window.location.pathname.startsWith("/admin/order-rules")) return;

    addOrderRuleDirectPublish();

    const observer = new MutationObserver(() => {
      addOrderRuleDirectPublish();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function run() {
    replaceVisibleText();
    simplifyStaffPage();
    addOrderRuleDirectPublish();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      run();
      observeOrderRuleDirectPublish();
    });
  } else {
    run();
    observeOrderRuleDirectPublish();
  }

  setTimeout(run, 300);
})();
