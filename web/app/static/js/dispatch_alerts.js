(function () {
  const REFRESH_INTERVAL_MS = 5000;
  const ENABLED_KEY = "mw_dispatch_alert_enabled";
  const LAST_KEYS_KEY = "mw_dispatch_state_keys_v1";
  const LAST_SIGNATURE_KEY = "mw_dispatch_state_signature_v1";

  let enabled = localStorage.getItem(ENABLED_KEY) === "1";
  let audioContext = null;
  let checking = false;

  function isDispatchPage() {
    return window.location.pathname === "/dispatch";
  }

  function readJson(key, fallback) {
    try {
      return JSON.parse(sessionStorage.getItem(key) || JSON.stringify(fallback));
    } catch (_) {
      return fallback;
    }
  }

  function writeJson(key, value) {
    sessionStorage.setItem(key, JSON.stringify(value));
  }

  function getOldKeys() {
    return readJson(LAST_KEYS_KEY, []);
  }

  function setOldKeys(keys) {
    writeJson(LAST_KEYS_KEY, keys || []);
  }

  function getOldSignature() {
    return sessionStorage.getItem(LAST_SIGNATURE_KEY) || "";
  }

  function setOldSignature(signature) {
    sessionStorage.setItem(LAST_SIGNATURE_KEY, signature || "");
  }

  function getAddedKeys(oldKeys, newKeys) {
    const oldSet = new Set(oldKeys || []);
    return (newKeys || []).filter(key => !oldSet.has(key));
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
    if (document.querySelector(".dispatch-alert-toggle")) return;

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

  async function fetchState() {
    const res = await fetch("/dispatch/state?t=" + Date.now(), {
      cache: "no-store",
      credentials: "same-origin"
    });

    if (!res.ok) return null;

    const data = await res.json();

    if (!data || !data.ok) return null;

    return data;
  }

  async function check() {
    if (checking || !isDispatchPage()) return;
    checking = true;

    try {
      const data = await fetchState();

      if (!data) return;

      const oldKeys = getOldKeys();
      const oldSignature = getOldSignature();

      const newKeys = data.keys || [];
      const newSignature = data.signature || "";
      const addedKeys = getAddedKeys(oldKeys, newKeys);

      if (oldKeys.length === 0 && !oldSignature) {
        setOldKeys(newKeys);
        setOldSignature(newSignature);
        return;
      }

      if (addedKeys.length > 0) {
        dingDong();

        setOldKeys(newKeys);
        setOldSignature(newSignature);

        if (!skipReload()) {
          setTimeout(() => window.location.reload(), 450);
        }

        return;
      }

      if (oldSignature && newSignature && oldSignature !== newSignature) {
        setOldKeys(newKeys);
        setOldSignature(newSignature);

        if (!skipReload()) {
          setTimeout(() => window.location.reload(), 450);
        }

        return;
      }

      setOldKeys(newKeys);
      setOldSignature(newSignature);
    } catch (_) {
    } finally {
      checking = false;
    }
  }

  async function init() {
    if (!isDispatchPage()) return;

    makeButton();

    const data = await fetchState();

    if (data) {
      setOldKeys(data.keys || []);
      setOldSignature(data.signature || "");
    }

    setInterval(check, REFRESH_INTERVAL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
