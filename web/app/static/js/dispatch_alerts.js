(function () {
  const REFRESH_INTERVAL_MS = 5000;
  const ENABLED_KEY = "mw_dispatch_alert_enabled";
  const LAST_KEYS_KEY = "mw_dispatch_last_order_keys";

  let enabled = localStorage.getItem(ENABLED_KEY) === "1";
  let audioContext = null;
  let checking = false;

  function isDispatchPage() {
    return window.location.pathname === "/dispatch";
  }

  function getOrderKeys(doc) {
    const text = (doc.body && doc.body.innerText) || "";
    const matches = text.match(/\b(?:MO\d{8,}|WEB-\d+)\b/g) || [];
    return Array.from(new Set(matches.map(x => x.trim()))).sort();
  }

  function getStoredKeys() {
    try {
      return JSON.parse(sessionStorage.getItem(LAST_KEYS_KEY) || "[]");
    } catch (_) {
      return [];
    }
  }

  function setStoredKeys(keys) {
    sessionStorage.setItem(LAST_KEYS_KEY, JSON.stringify(keys));
  }

  function hasNewOrder(oldKeys, newKeys) {
    const oldSet = new Set(oldKeys);
    return newKeys.some(key => !oldSet.has(key));
  }

  function getAudioContext() {
    const AudioClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioClass) return null;

    if (!audioContext) {
      audioContext = new AudioClass();
    }

    if (audioContext.state === "suspended") {
      audioContext.resume().catch(() => {});
    }

    return audioContext;
  }

  function tone(ctx, freq, start, duration, volume) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, start);

    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start(start);
    osc.stop(start + duration + 0.05);
  }

  function dingDong() {
    if (!enabled) return;

    const ctx = getAudioContext();
    if (!ctx) return;

    const now = ctx.currentTime;
    tone(ctx, 880, now, 0.22, 0.18);
    tone(ctx, 660, now + 0.18, 0.28, 0.16);
  }

  function makeButton() {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dispatch-alert-toggle";
    btn.textContent = enabled ? "🔔 新單提示已開" : "🔕 開啟新單提示";

    btn.addEventListener("click", () => {
      enabled = !enabled;
      localStorage.setItem(ENABLED_KEY, enabled ? "1" : "0");

      if (enabled) {
        getAudioContext();
        dingDong();
      }

      btn.textContent = enabled ? "🔔 新單提示已開" : "🔕 開啟新單提示";
    });

    document.body.appendChild(btn);
  }

  function skipReload() {
    const el = document.activeElement;
    if (!el) return false;
    return ["input", "textarea", "select"].includes(el.tagName.toLowerCase());
  }

  async function check() {
    if (checking || !isDispatchPage()) return;
    checking = true;

    try {
      const res = await fetch(window.location.pathname + window.location.search, {
        cache: "no-store",
        credentials: "same-origin"
      });

      if (!res.ok) return;

      const html = await res.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const newKeys = getOrderKeys(doc);
      const oldKeys = getStoredKeys();

      if (oldKeys.length > 0 && hasNewOrder(oldKeys, newKeys)) {
        dingDong();

        if (!skipReload()) {
          setTimeout(() => window.location.reload(), 450);
        }
      }

      setStoredKeys(newKeys);
    } catch (_) {
    } finally {
      checking = false;
    }
  }

  function init() {
    if (!isDispatchPage()) return;

    makeButton();
    setStoredKeys(getOrderKeys(document));
    setInterval(check, REFRESH_INTERVAL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
