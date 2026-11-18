(() => {
  "use strict";
  const boot = window.AFFECTION_GAME_BOOTSTRAP;
  const root = document.getElementById("affectionGameRoot");
  if (!root || !boot?.order?.id) return;
  const base = `/me/orders/${Number(boot.order.id)}/affection-game`;
  const $ = (id) => document.getElementById(id);
  let model = boot;
  let busy = false;
  let pending = null;
  let toastTimer = 0;
  const isBoss = model.viewer.role === "boss";

  function toast(message) {
    const element = $("agToast");
    if (!element) return;
    element.textContent = String(message || "");
    element.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => element.classList.remove("visible"), 2700);
  }

  async function api(suffix, body) {
    const response = await fetch(base + suffix, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {"Content-Type": "application/json"},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}),
    });
    let data;
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw Error(data?.detail || "操作失敗，請稍後再試。");
    return data;
  }

  const formatPoints = (value) => {
    const n = Number(value || 0);
    return n > 0 ? "+" + n : String(n);
  };
  function render(data) {
    if (!data?.ok) return;
    model = data;
    const state = data.state;
    $("agScore").textContent = String(state.affection);
    $("agRound").textContent = String(state.round_no);
    $("agStatus").textContent = state.completed ? "已完成" : (state.started ? "進行中" : "尚未開始");
    const progress = Math.max(0, Math.min(100, ((Number(state.affection) + 80) / 180) * 100));
    $("agProgressFill").style.width = progress.toFixed(2) + "%";

    const locked = !isBoss || data.read_only || !state.started || state.completed || busy;
    root.querySelectorAll("[data-event]").forEach((button) => { button.disabled = locked; });
    ["agSettleSuccess", "agSettleFail", "agExtra", "agUndo"].forEach((id) => {
      const element = $(id);
      if (element) element.disabled = locked;
    });
    const intro = $("agIntro");
    if (intro) intro.hidden = state.started || data.read_only;
    const introStart = $("agStart");
    if (introStart) introStart.disabled = busy;

    const history = $("agHistory");
    history.replaceChildren();
    const records = Array.isArray(data.events) ? data.events : [];
    if (!records.length) {
      const li = document.createElement("li");
      li.textContent = "目前尚無操作紀錄。";
      history.appendChild(li);
    }
    for (const event of records) {
      const li = document.createElement("li");
      if (event.undone) li.classList.add("is-undone");
      const text = document.createElement("span");
      text.textContent = `第${event.round}局　${event.label}　(${formatPoints(event.delta)})`;
      const small = document.createElement("small");
      small.textContent = `${event.actor}${event.undone ? "・已撤銷" : ""}`;
      li.append(text, small);
      history.appendChild(li);
    }
  }

  async function perform(suffix, body) {
    if (busy || model.state.completed || model.read_only) return;
    busy = true;
    render(model);
    try {
      const next = await api(suffix, body);
      busy = false;
      render(next);
      if (suffix === "/settle") $("agExtra").checked = false;
    } catch (error) {
      busy = false;
      toast(error.message);
      try { render(await api("/state")); } catch (_) { render(model); }
    }
  }

  root.querySelectorAll("[data-event]").forEach((button) => {
    button.addEventListener("click", () => perform("/event", {
      event_key: button.dataset.event, expected_round: Number(model.state.round_no),
    }));
  });

  $("agStart")?.addEventListener("click", () => {
    if (busy || !isBoss) return;
    perform("/start", {});
  });
  $("agUndo")?.addEventListener("click", () => {
    if (!window.confirm("確認撤銷本局最後一筆未結算的計分？")) return;
    perform("/undo", {});
  });

  const modal = $("agConfirm");
  function planSettle(result) {
    if (!isBoss || busy || model.read_only || model.state.completed || !model.state.started) return;
    const extra = Boolean($("agExtra")?.checked);
    if (result === "fail" && extra) {
      toast("額外撤離加分僅限撤離成功；請先取消勾選。");
      return;
    }
    pending = { result, extra, expected_round: Number(model.state.round_no) };
    $("agConfirmText").textContent = `第 ${pending.expected_round} 局：${result === "success" ? "成功撤離" : "撤離失敗"}${extra ? "（含額外 +3）" : ""}。結算後無法再次修改本局分數。`;
    if (typeof modal?.showModal === "function") modal.showModal();
  }
  $("agSettleSuccess")?.addEventListener("click", () => planSettle("success"));
  $("agSettleFail")?.addEventListener("click", () => planSettle("fail"));
  $("agCancel")?.addEventListener("click", () => { modal?.close(); pending = null; });
  $("agConfirmSubmit")?.addEventListener("click", () => {
    if (!pending) return;
    const submit = pending;
    pending = null;
    modal?.close();
    perform("/settle", submit);
  });
  modal?.addEventListener("close", () => { pending = null; });

  async function refresh() {
    if (busy || document.visibilityState === "hidden" || modal?.open) return;
    try { render(await api("/state")); } catch (_) { /* offline: preserve visible state */ }
  }
  render(model);
  setInterval(refresh, 6000);
})();
