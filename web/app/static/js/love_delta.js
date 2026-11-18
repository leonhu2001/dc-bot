(() => {
  "use strict";

  const boot = window.LOVE_DELTA_BOOTSTRAP;
  if (!boot || !boot.order || !boot.state || !boot.viewer) return;

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const root = $("#loveDeltaRoot");
  const base = `/me/orders/${Number(boot.order.id)}/love-delta`;
  const viewer = boot.viewer;
  let state = boot.state;
  let events = Array.isArray(boot.events) ? boot.events : [];
  let readOnly = Boolean(boot.read_only);
  let selectedTier = 0;
  let pendingResult = null;
  let currentThemeScore = Number(state.theme_affection ?? state.initial_affection ?? -30);
  let polling = false;
  let toastTimer = null;

  const scoreText = (value) => {
    const n = Number(value || 0);
    return Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, "");
  };

  const visualPercent = (score) => {
    const n = Number(score || 0);
    return Math.max(0, Math.min(100, ((n + 80) / 180) * 100));
  };

  const escapeText = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

  function toast(message) {
    const node = $("#ldToast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => node.classList.remove("is-visible"), 1800);
  }

  async function request(path, options = {}) {
    const response = await fetch(base + path, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });

    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    if (!response.ok) {
      const detail = payload && payload.detail ? String(payload.detail) : "操作失敗，請稍後再試。";
      throw new Error(detail);
    }
    return payload;
  }

  function ambientPalette(score) {
    const anchors = [
      { s: -80, c1: [74, 78, 144], c2: [105, 68, 128], c3: [62, 100, 143], base: [206, 200, 217] },
      { s: -30, c1: [101, 68, 148], c2: [135, 63, 122], c3: [78, 90, 148], base: [215, 199, 216] },
      { s: 30, c1: [151, 55, 120], c2: [181, 72, 124], c3: [127, 72, 144], base: [225, 198, 213] },
      { s: 60, c1: [177, 46, 105], c2: [205, 75, 112], c3: [154, 63, 116], base: [230, 194, 205] },
      { s: 100, c1: [197, 54, 84], c2: [220, 91, 88], c3: [178, 66, 98], base: [232, 190, 194] },
    ];
    const clamp = Math.max(-80, Math.min(100, Number(score || 0)));
    let a = anchors[0];
    let b = anchors[1];
    for (let i = 0; i < anchors.length - 1; i += 1) {
      if (clamp >= anchors[i].s && clamp <= anchors[i + 1].s) {
        a = anchors[i];
        b = anchors[i + 1];
        break;
      }
    }
    const t = (clamp - a.s) / (b.s - a.s || 1);
    const mix = (x, y) => x.map((v, i) => Math.round(v + (y[i] - v) * t));
    const rgba = (c, alpha) => `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
    const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
    const c1 = mix(a.c1, b.c1);
    const c2 = mix(a.c2, b.c2);
    const c3 = mix(a.c3, b.c3);
    const baseColor = mix(a.base, b.base);
    const base2 = baseColor.map((v, i) => Math.round(v + ([216, 204, 211][i] - v) * 0.38));
    return `radial-gradient(circle at 5% -3%, ${rgba(c1, .54)}, transparent 40%),
            radial-gradient(circle at 97% 8%, ${rgba(c2, .44)}, transparent 38%),
            radial-gradient(circle at 50% 108%, ${rgba(c3, .32)}, transparent 44%),
            linear-gradient(180deg, ${rgb(baseColor)} 0%, ${rgb(base2)} 100%)`;
  }

  function setAmbientInstant(score) {
    $("#ldAmbient").style.background = ambientPalette(score);
    $("#ldAmbientNext").classList.remove("is-visible");
    currentThemeScore = Number(score || 0);
  }

  function animateAmbientTo(score) {
    const nextValue = Number(score || 0);
    if (nextValue === currentThemeScore) return;
    const current = $("#ldAmbient");
    const next = $("#ldAmbientNext");
    currentThemeScore = nextValue;
    next.style.background = ambientPalette(nextValue);
    next.classList.remove("is-visible");
    void next.offsetWidth;
    next.classList.add("is-visible");
    window.setTimeout(() => {
      current.style.background = next.style.background;
      next.classList.remove("is-visible");
      currentThemeScore = nextValue;
    }, 1580);
  }

  function setInputValue(selector, value) {
    const input = $(selector);
    if (!input || document.activeElement === input) return;
    input.value = String(value || "");
  }

  function disabledByState() {
    return readOnly || Boolean(state.completed) || !Boolean(state.started);
  }

  function renderRescueButtons() {
    const container = $("#ldRescueButtons");
    if (!container) return;
    const companions = Array.isArray(state.companions) ? state.companions : [];
    let visible = companions;
    if (viewer.role === "companion") {
      visible = companions.filter((item) => String(item.id) === String(viewer.id));
    }
    if (!visible.length) {
      container.innerHTML = `<div class="ld-empty">目前沒有可計算首次救援的女陪。</div>`;
      return;
    }
    container.innerHTML = visible.map((item) => {
      const used = Boolean(item.first_rescue_scored);
      const label = viewer.role === "boss" ? `${escapeText(item.name)} 第一次救起老闆` : "第一次救起老闆";
      return `<button class="ld-event" type="button" data-rescue-id="${escapeText(item.id)}" ${used || disabledByState() ? "disabled" : ""}>
        <strong>${label}</strong><span class="ld-points">${used ? "已計算" : "+5"}</span>
      </button>`;
    }).join("");
  }

  function renderBanButtons() {
    const container = $("#ldBanButtons");
    if (!container) return;
    const bans = Array.isArray(state.bans) ? state.bans : ["", "", ""];
    container.innerHTML = bans.map((value, index) => {
      const text = String(value || "").trim();
      return `<button class="ld-event" type="button" data-ban-index="${index + 1}" ${!text || disabledByState() ? "disabled" : ""}>
        <strong>${text ? `講到：${escapeText(text)}` : `禁語 ${index + 1} 尚未設定`}</strong><span class="ld-points is-minus">-2</span>
      </button>`;
    }).join("");
  }

  function renderLog() {
    const log = $("#ldLog");
    if (!log) return;
    if (!events.length) {
      log.innerHTML = `<div class="ld-empty">尚無操作紀錄。</div>`;
      return;
    }
    log.innerHTML = events.slice(0, 12).map((item) => {
      const delta = Number(item.delta || 0);
      const deltaText = delta === 0 ? "" : `${delta > 0 ? "+" : ""}${scoreText(delta)}`;
      return `<div class="ld-log-item">
        <span>第 ${Number(item.round_no || 1)} 局・${escapeText(item.label)}${item.is_undone ? "（已撤銷）" : ""}<br>${escapeText(item.actor_name || "")}</span>
        <b class="${delta < 0 ? "is-minus" : ""}">${deltaText}</b>
      </div>`;
    }).join("");
  }

  function render() {
    root.dataset.role = viewer.role;
    $("#ldScore").textContent = scoreText(state.affection);
    $("#ldRound").textContent = String(state.round_no || 1);
    $("#ldRoundPositive").textContent = scoreText(state.round_positive);
    $("#ldTrackFill").style.width = `${visualPercent(state.affection)}%`;
    $("#ldCompleteBanner").classList.toggle("is-visible", Boolean(state.completed));

    const bossLocked = Boolean(state.boss_answer_locked);
    const companionLocked = Boolean(state.companion_guess_locked);
    const bossStatus = $("#ldBossGuessStatus");
    if (bossStatus) {
      bossStatus.textContent = bossLocked ? "答案已鎖定" : "尚未鎖定";
      bossStatus.classList.toggle("is-locked", bossLocked);
    }
    const companionStatus = $("#ldCompanionGuessStatus");
    if (companionStatus) {
      companionStatus.textContent = companionLocked ? "答案已鎖定" : "尚未鎖定";
      companionStatus.classList.toggle("is-locked", companionLocked);
    }

    setInputValue("#ldHintCategory", state.hint_category);
    setInputValue("#ldHintQuality", state.hint_quality);
    setInputValue("#ldBossAnswer", state.boss_answer);
    setInputValue("#ldCompanionGuess", state.companion_guess);
    $("#ldShowHintCategory").textContent = bossLocked ? (state.hint_category || "未提供") : "等待老闆鎖定";
    $("#ldShowHintQuality").textContent = bossLocked ? (state.hint_quality || "未提供") : "等待老闆鎖定";

    const bossInputsDisabled = bossLocked || companionLocked || disabledByState();
    ["#ldHintCategory", "#ldHintQuality", "#ldBossAnswer"].forEach((selector) => {
      const node = $(selector);
      if (node) node.disabled = bossInputsDisabled;
    });
    $("#ldLockBossGuess").disabled = bossLocked || companionLocked || disabledByState();
    $("#ldClearBossGuess").disabled = !bossLocked || companionLocked || disabledByState();
    $("#ldCompanionGuess").disabled = companionLocked || !bossLocked || disabledByState();
    $("#ldLockCompanionGuess").disabled = companionLocked || !bossLocked || disabledByState();
    $("#ldClearCompanionGuess").disabled = !companionLocked || disabledByState();

    const bans = Array.isArray(state.bans) ? state.bans : ["", "", ""];
    setInputValue("#ldBan1", bans[0]);
    setInputValue("#ldBan2", bans[1]);
    setInputValue("#ldBan3", bans[2]);
    const canEditBans = viewer.role === "boss" && Boolean(state.bans_editable) && !disabledByState();
    ["#ldBan1", "#ldBan2", "#ldBan3"].forEach((selector) => {
      const node = $(selector);
      if (node) node.disabled = !canEditBans;
    });
    $("#ldSaveBans").disabled = !canEditBans;
    $("#ldBanEditHint").textContent = state.bans_editable ? "可設定／更換" : "下次成功撤離後可更換";
    [0, 1, 2].forEach((index) => {
      const node = $(`#ldBanRead${index + 1}`);
      if (node) node.textContent = bans[index] || "未設定";
    });

    setInputValue("#ldSuffix", state.suffix);
    setInputValue("#ldNickname", state.nickname);
    const suffixUnlocked = Boolean(state.suffix_unlocked);
    const nicknameUnlocked = Boolean(state.nickname_unlocked);
    $("#ldSuffix").disabled = !suffixUnlocked || disabledByState();
    $("#ldSaveSuffix").disabled = !suffixUnlocked || disabledByState();
    $("#ldNickname").disabled = !nicknameUnlocked || disabledByState();
    $("#ldSaveNickname").disabled = !nicknameUnlocked || disabledByState();
    $("#ldSuffixBox").classList.toggle("is-active", suffixUnlocked);
    $("#ldNicknameBox").classList.toggle("is-active", nicknameUnlocked);
    $("#ldSuffixRead").textContent = suffixUnlocked ? (state.suffix || "待設定") : "尚未解鎖";
    $("#ldNicknameRead").textContent = nicknameUnlocked ? (state.nickname || "待設定") : "尚未解鎖";
    $("#ldMissSuffix").disabled = !suffixUnlocked || !state.suffix || disabledByState();

    const current = state.current_designation;
    $("#ldCurrentDesignation").innerHTML = current
      ? `本局指定：幹員 <b>${escapeText(current.agent || "未指定")}</b>・槍械 <b>${escapeText(current.weapon || "未指定")}</b>`
      : "本局沒有指定幹員或槍械。";
    const next = state.next_designation;
    $("#ldNextDesignation").innerHTML = next
      ? `下一局指定：幹員 <b>${escapeText(next.agent || "未指定")}</b>・槍械 <b>${escapeText(next.weapon || "未指定")}</b>`
      : "尚未指定下一局。";
    const loadoutAvailable = Boolean(state.loadout_unlocked) && viewer.role === "boss" && !disabledByState();
    $("#ldAgent").disabled = !loadoutAvailable;
    $("#ldWeapon").disabled = !loadoutAvailable;
    $("#ldSaveLoadout").disabled = !loadoutAvailable;
    $("#ldLoadoutBox").classList.toggle("is-active", loadoutAvailable);

    $("#ldBossLockSide").textContent = bossLocked ? "已鎖定" : "尚未鎖定";
    $("#ldCompanionLockSide").textContent = companionLocked ? "已鎖定" : "尚未鎖定";
    $("#ldSuffixSide").textContent = suffixUnlocked ? (state.suffix || "待設定") : "尚未解鎖";
    $("#ldNicknameSide").textContent = nicknameUnlocked ? (state.nickname || "待設定") : "尚未解鎖";

    $$('[data-ld-event]').forEach((button) => {
      const type = button.dataset.ldEvent;
      if (type === "miss_suffix") return;
      button.disabled = disabledByState();
    });
    $$(".ld-settle-action").forEach((button) => {
      button.disabled = disabledByState();
    });
    $("#ldUndo").disabled = readOnly || !state.started;

    renderRescueButtons();
    renderBanButtons();
    renderLog();
  }

  function applyPayload(payload, options = {}) {
    if (!payload || !payload.state) return;
    const previousTheme = currentThemeScore;
    state = payload.state;
    events = Array.isArray(payload.events) ? payload.events : events;
    readOnly = Boolean(payload.read_only);
    const nextTheme = Number(state.theme_affection ?? previousTheme);
    if (options.animateTheme !== false && nextTheme !== previousTheme) {
      animateAmbientTo(nextTheme);
    }
    render();
  }

  async function run(button, callback, successMessage) {
    if (button) button.disabled = true;
    try {
      const payload = await callback();
      applyPayload(payload);
      if (successMessage) toast(successMessage);
      return payload;
    } catch (error) {
      toast(error.message || "操作失敗。");
      return null;
    } finally {
      render();
    }
  }

  function playIntroExit() {
    const intro = $("#ldIntro");
    if (!intro || intro.hidden) return;
    intro.classList.add("is-starting");
    window.setTimeout(() => intro.classList.add("is-leaving"), 520);
    window.setTimeout(() => {
      intro.hidden = true;
      intro.classList.remove("is-starting", "is-leaving");
      $("#ldPanel").classList.add("ld-enter");
      window.setTimeout(() => $("#ldPanel").classList.remove("ld-enter"), 700);
    }, 1000);
  }

  const startButton = $("#ldStart");
  if (startButton && viewer.role === "boss" && !state.started && !readOnly) {
    startButton.addEventListener("click", async () => {
      startButton.disabled = true;
      startButton.textContent = "攻略啟動中…";
      try {
        const payload = await request("/start", { method: "POST", body: "{}" });
        applyPayload(payload, { animateTheme: false });
        playIntroExit();
      } catch (error) {
        startButton.disabled = false;
        startButton.textContent = "開始攻略";
        toast(error.message || "無法開始攻略。");
      }
    });
  }

  $$("[data-ld-event]").forEach((button) => {
    button.addEventListener("click", () => run(
      button,
      () => request("/event", {
        method: "POST",
        body: JSON.stringify({ event_type: button.dataset.ldEvent }),
      }),
      "進度已更新",
    ));
  });

  $("#ldRescueButtons").addEventListener("click", (event) => {
    const button = event.target.closest("[data-rescue-id]");
    if (!button) return;
    run(
      button,
      () => request("/event", {
        method: "POST",
        body: JSON.stringify({ event_type: "first_rescue", target_companion_id: button.dataset.rescueId }),
      }),
      "首次救援已計分",
    );
  });

  $("#ldBanButtons").addEventListener("click", (event) => {
    const button = event.target.closest("[data-ban-index]");
    if (!button) return;
    run(
      button,
      () => request("/event", {
        method: "POST",
        body: JSON.stringify({ event_type: `ban_${button.dataset.banIndex}` }),
      }),
      "禁語已扣分",
    );
  });

  $("#ldLockBossGuess").addEventListener("click", () => run(
    $("#ldLockBossGuess"),
    () => request("/guess/boss", {
      method: "POST",
      body: JSON.stringify({
        answer: $("#ldBossAnswer").value,
        hint_category: $("#ldHintCategory").value,
        hint_quality: $("#ldHintQuality").value,
      }),
    }),
    "本局答案已鎖定",
  ));

  $("#ldClearBossGuess").addEventListener("click", () => run(
    $("#ldClearBossGuess"),
    () => request("/guess/boss", { method: "DELETE" }),
    "本局答案已清除",
  ));

  $("#ldLockCompanionGuess").addEventListener("click", () => run(
    $("#ldLockCompanionGuess"),
    () => request("/guess/companion", {
      method: "POST",
      body: JSON.stringify({ guess: $("#ldCompanionGuess").value }),
    }),
    "共同答案已鎖定",
  ));

  $("#ldClearCompanionGuess").addEventListener("click", () => run(
    $("#ldClearCompanionGuess"),
    () => request("/guess/companion", { method: "DELETE" }),
    "共同答案已清除",
  ));

  $("#ldSaveBans").addEventListener("click", () => run(
    $("#ldSaveBans"),
    () => request("/bans", {
      method: "POST",
      body: JSON.stringify({ bans: [$("#ldBan1").value, $("#ldBan2").value, $("#ldBan3").value] }),
    }),
    "禁語已儲存",
  ));

  $("#ldSaveSuffix").addEventListener("click", () => run(
    $("#ldSaveSuffix"),
    () => request("/settings/suffix", {
      method: "POST",
      body: JSON.stringify({ value: $("#ldSuffix").value }),
    }),
    "句末助詞已儲存",
  ));

  $("#ldSaveNickname").addEventListener("click", () => run(
    $("#ldSaveNickname"),
    () => request("/settings/nickname", {
      method: "POST",
      body: JSON.stringify({ value: $("#ldNickname").value }),
    }),
    "特殊稱呼已儲存",
  ));

  $("#ldSaveLoadout").addEventListener("click", () => run(
    $("#ldSaveLoadout"),
    () => request("/loadout", {
      method: "POST",
      body: JSON.stringify({ agent: $("#ldAgent").value, weapon: $("#ldWeapon").value }),
    }),
    "下局指定已儲存",
  ));

  $("#ldUndo").addEventListener("click", () => run(
    $("#ldUndo"),
    () => request("/undo", { method: "POST", body: "{}" }),
    "已撤銷上一個事件",
  ));

  $$("#ldValueGrid [data-tier]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTier = Number(button.dataset.tier || 0);
      $$("#ldValueGrid [data-tier]").forEach((node) => node.classList.toggle("is-active", node === button));
    });
  });

  function syncModalTier() {
    $$("#ldModalValueGrid [data-modal-tier]").forEach((node) => {
      node.classList.toggle("is-active", Number(node.dataset.modalTier || 0) === selectedTier);
    });
  }

  $$("#ldModalValueGrid [data-modal-tier]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTier = Number(button.dataset.modalTier || 0);
      syncModalTier();
      $$("#ldValueGrid [data-tier]").forEach((node) => {
        node.classList.toggle("is-active", Number(node.dataset.tier || 0) === selectedTier);
      });
    });
  });

  function openSettle(result) {
    pendingResult = result;
    $("#ldSettleTitle").textContent = result === "success" ? "✓ 成功撤離｜本局結算" : "× 撤離失敗｜本局結算";
    let message = "雙方答案尚未全部鎖定，本局不會套用猜中倍率。";
    if (state.boss_answer_locked && state.companion_guess_locked) {
      message = "雙方答案都已鎖定，確認結算後會自動比對並套用 1.2 倍。";
    } else if (state.boss_answer_locked) {
      message = "老闆答案已鎖定，但女陪尚未鎖定共同答案。";
    }
    $("#ldGuessResult").textContent = message;
    syncModalTier();
    $("#ldSettleModal").classList.add("is-open");
    $("#ldSettleModal").setAttribute("aria-hidden", "false");
  }

  $$("[data-settle]").forEach((button) => {
    button.addEventListener("click", () => openSettle(button.dataset.settle));
  });

  $("#ldCancelSettle").addEventListener("click", () => {
    pendingResult = null;
    $("#ldSettleModal").classList.remove("is-open");
    $("#ldSettleModal").setAttribute("aria-hidden", "true");
  });

  $("#ldConfirmSettle").addEventListener("click", async () => {
    if (!pendingResult) return;
    const button = $("#ldConfirmSettle");
    button.disabled = true;
    try {
      const payload = await request("/settle", {
        method: "POST",
        body: JSON.stringify({
          expected_round: Number(state.round_no || 1),
          result: pendingResult,
          extraction_tier: selectedTier,
        }),
      });
      applyPayload(payload, { animateTheme: pendingResult === "success" });
      $("#ldSettleModal").classList.remove("is-open");
      $("#ldSettleModal").setAttribute("aria-hidden", "true");
      toast(pendingResult === "success" ? "成功撤離｜本局已結算" : "撤離失敗｜安全箱價值已結算");
      selectedTier = 0;
      $$("#ldValueGrid [data-tier]").forEach((node) => node.classList.toggle("is-active", Number(node.dataset.tier || 0) === 0));
      pendingResult = null;
    } catch (error) {
      toast(error.message || "結算失敗。");
    } finally {
      button.disabled = false;
      render();
    }
  });

  $("#ldSettleModal").addEventListener("click", (event) => {
    if (event.target === $("#ldSettleModal")) $("#ldCancelSettle").click();
  });

  async function pollState() {
    if (polling || document.hidden) return;
    polling = true;
    try {
      const payload = await request("/state", { method: "GET", headers: {} });
      const wasStarted = Boolean(state.started);
      applyPayload(payload);
      if (!wasStarted && state.started && viewer.role === "companion") {
        playIntroExit();
      }
    } catch (_) {
      // Background sync is best-effort. User actions still surface errors.
    } finally {
      polling = false;
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) pollState();
  });

  setAmbientInstant(currentThemeScore);
  render();
  if (state.started) {
    const panel = $("#ldPanel");
    panel.classList.add("ld-enter");
    window.setTimeout(() => panel.classList.remove("ld-enter"), 700);
  }
  window.setInterval(pollState, 2500);
})();
