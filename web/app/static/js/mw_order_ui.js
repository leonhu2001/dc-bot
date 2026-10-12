(() => {
  "use strict";
  if (window.__MAWAN_ORDER_UI__) return;
  window.__MAWAN_ORDER_UI__ = true;

  const EXTRA_KEY = "mawan_order_extra_requirements";
  const cache = new Map();
  let requestId = 0;
  const byId = (id) => document.getElementById(id);
  const clean = (value) => String(value || "").trim();

  function syncScrollLock() {
    const dialog = byId("mw-order-dialog");
    const open = Boolean(dialog && dialog.open);
    document.documentElement.classList.toggle("mw-order-open", open);
    document.body.classList.toggle("mw-order-open", open);
  }

  function setupExtraRequirements() {
    const field = byId("mw-adjustments-field");
    const adjustments = byId("mw-adjustments");
    if (!field || !adjustments) return;
    field.hidden = false;

    let textarea = byId("mw-extra-requirements");
    if (!textarea) {
      textarea = document.createElement("textarea");
      textarea.id = "mw-extra-requirements";
      textarea.name = "extra_requirements";
      textarea.rows = 4;
      textarea.maxLength = 500;
      textarea.autocomplete = "off";
      textarea.placeholder = "可填寫稱呼、語音、打法或其他需求（選填）";
      textarea.value = sessionStorage.getItem(EXTRA_KEY) || "";
      adjustments.insertAdjacentElement("afterend", textarea);
    }
    if (textarea.dataset.mwBound !== "1") {
      textarea.dataset.mwBound = "1";
      textarea.addEventListener("input", () => {
        sessionStorage.setItem(EXTRA_KEY, textarea.value);
      });
    }
  }

  function clearExtraRequirements() {
    sessionStorage.removeItem(EXTRA_KEY);
    const textarea = byId("mw-extra-requirements");
    if (textarea) textarea.value = "";
  }

  function currentRuleKey() {
    const direct = clean(byId("mw-rule-key")?.textContent);
    if (direct && direct !== "—") return direct;
    const select = byId("mw-variant");
    if (!select || select.selectedIndex < 0) return "";
    return clean(select.options[select.selectedIndex]?.value);
  }

  async function loadMeta(ruleKey) {
    if (cache.has(ruleKey)) return cache.get(ruleKey);
    const response = await fetch(
      "/order/rule-ui-meta?rule_key=" + encodeURIComponent(ruleKey),
      {cache: "no-store"},
    );
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "rule meta failed");
    }
    cache.set(ruleKey, result.data);
    return result.data;
  }

  function setButton(button, disabled) {
    if (!button) return;
    button.disabled = disabled;
    button.setAttribute("aria-disabled", disabled ? "true" : "false");
  }

  function setFixedNote(field, fixed) {
    field.classList.toggle("mw-fixed-player-count", fixed);
    const old = field.querySelector(".mw-fixed-player-note");
    if (!fixed) {
      old?.remove();
      return;
    }
    if (old) return;
    const label = field.querySelector("span");
    if (!label) return;
    const note = document.createElement("small");
    note.className = "mw-fixed-player-note";
    note.textContent = "固定";
    label.appendChild(note);
  }

  async function refreshPlayerRule() {
    const ruleKey = currentRuleKey();
    if (!ruleKey) return;
    const serial = ++requestId;
    try {
      const meta = await loadMeta(ruleKey);
      if (serial !== requestId) return;
      const field = byId("mw-player-field");
      if (!field) return;
      const editable = Boolean(meta.player_count_enabled);
      const minus = byId("mw-player-minus");
      const plus = byId("mw-player-plus");
      const value = byId("mw-player-count") || field.querySelector("input[name='player_count']");
      if (!editable && value) {
        const fixed = Math.max(1, Number.parseInt(meta.fixed_player_count, 10) || 1);
        if ("value" in value) value.value = String(fixed);
        else value.textContent = String(fixed);
        document.querySelectorAll("input[name='player_count']").forEach((input) => {
          input.value = String(fixed);
        });
      }
      setButton(minus, !editable);
      setButton(plus, !editable);
      setFixedNote(field, !editable);
    } catch (error) {
      console.error("[MAWAN ORDER UI]", error);
    }
  }

  function refresh() {
    setupExtraRequirements();
    void refreshPlayerRule();
    syncScrollLock();
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest(".order3-open")) {
      clearExtraRequirements();
      requestAnimationFrame(refresh);
    } else {
      requestAnimationFrame(syncScrollLock);
    }
  });

  document.addEventListener("change", (event) => {
    if (event.target?.id === "mw-variant") requestAnimationFrame(refresh);
  });

  const dialog = byId("mw-order-dialog");
  dialog?.addEventListener("close", syncScrollLock);
  dialog?.addEventListener("cancel", () => requestAnimationFrame(syncScrollLock));
  requestAnimationFrame(refresh);
})();
