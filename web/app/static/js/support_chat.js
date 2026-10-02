
(() => {
    "use strict";

    const launcher = document.querySelector("[data-mw-support-launcher]");
    const panel = document.querySelector("[data-mw-support-panel]");
    const closeButton = document.querySelector("[data-mw-support-close]");
    const messagesBox = document.querySelector("[data-mw-support-messages]");
    const statusBox = document.querySelector("[data-mw-support-status]");
    const form = document.querySelector("[data-mw-support-form]");
    const input = document.querySelector("[data-mw-support-input]");
    const sendButton = document.querySelector("[data-mw-support-send]");
    const humanButton = document.querySelector("[data-mw-support-human]");

    if (!launcher || !panel || !messagesBox || !form || !input) {
        return;
    }

    let bootstrapped = false;
    let lastId = 0;
    let pollTimer = null;
    let sending = false;

    const labels = {
        customer: "你",
        ai: "魔丸客服助理",
        staff: "真人客服",
        system: "系統",
    };

    function setStatus(session) {
        const status = String(session?.status || "ai");
        statusBox?.classList.toggle(
            "is-human",
            status === "waiting_human" || status === "human",
        );

        if (!statusBox) return;

        if (status === "waiting_human") {
            statusBox.textContent = "已通知真人客服，等待接手中";
        } else if (status === "human") {
            const name = String(session?.claimed_by || "").trim();
            statusBox.textContent = name
                ? `真人客服 ${name} 處理中`
                : "真人客服處理中";
        } else if (status === "closed") {
            statusBox.textContent = "本次真人客服已結束，可重新開始對話";
        } else {
            statusBox.textContent = "AI 客服在線 · 需要時可轉真人";
        }

        if (humanButton) {
            const humanActive = status === "waiting_human" || status === "human";
            humanButton.disabled = humanActive;
            humanButton.textContent = status === "waiting_human"
                ? "等待真人客服中"
                : status === "human"
                    ? "真人客服已接手"
                    : "轉接真人客服";
        }
    }

    function appendMessage(item) {
        const id = Number(item?.id || 0);
        if (id && messagesBox.querySelector(`[data-message-id="${id}"]`)) {
            lastId = Math.max(lastId, id);
            return;
        }

        const sender = String(item?.sender_type || "system");
        const wrap = document.createElement("div");
        wrap.className = `mw-support-message is-${sender}`;
        if (id) wrap.dataset.messageId = String(id);

        const small = document.createElement("small");
        small.textContent = String(
            item?.sender_display_name || labels[sender] || "客服"
        );

        const body = document.createElement("div");
        body.textContent = String(item?.body || "");

        wrap.append(small, body);
        messagesBox.appendChild(wrap);
        lastId = Math.max(lastId, id);
    }

    function appendMessages(items) {
        const list = Array.isArray(items) ? items : [];
        for (const item of list) appendMessage(item);
        if (list.length) {
            messagesBox.scrollTop = messagesBox.scrollHeight;
        }
    }

    async function bootstrap() {
        if (bootstrapped) return;
        bootstrapped = true;

        try {
            const response = await fetch("/api/support-chat/bootstrap", {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                headers: {"Content-Type": "application/json"},
                body: "{}",
            });
            if (!response.ok) throw new Error("bootstrap failed");
            const data = await response.json();
            appendMessages(data.messages);
            setStatus(data.session);
            startPolling();
        } catch (_) {
            bootstrapped = false;
            if (statusBox) statusBox.textContent = "客服目前暫時無法連線";
        }
    }

    async function poll() {
        if (!panel.classList.contains("is-open")) return;
        try {
            const response = await fetch(
                `/api/support-chat/messages?after_id=${encodeURIComponent(lastId)}`,
                {
                    credentials: "same-origin",
                    cache: "no-store",
                },
            );
            if (!response.ok) return;
            const data = await response.json();
            appendMessages(data.messages);
            setStatus(data.session);
        } catch (_) {}
    }

    function startPolling() {
        if (pollTimer) return;
        pollTimer = window.setInterval(poll, 3000);
    }

    launcher.addEventListener("click", async () => {
        panel.classList.add("is-open");
        launcher.setAttribute("aria-expanded", "true");
        await bootstrap();
        input.focus();
    });

    closeButton?.addEventListener("click", () => {
        panel.classList.remove("is-open");
        launcher.setAttribute("aria-expanded", "false");
    });

    humanButton?.addEventListener("click", async () => {
        humanButton.disabled = true;
        try {
            const response = await fetch("/api/support-chat/human", {
                method: "POST",
                credentials: "same-origin",
                headers: {"Content-Type": "application/json"},
                body: "{}",
            });
            if (!response.ok) throw new Error("handoff failed");
            const data = await response.json();
            setStatus(data.session);
            await poll();
        } catch (_) {
            humanButton.disabled = false;
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = String(input.value || "").trim();
        if (!message || sending) return;

        sending = true;
        sendButton && (sendButton.disabled = true);
        input.value = "";

        try {
            const response = await fetch("/api/support-chat/messages", {
                method: "POST",
                credentials: "same-origin",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({message}),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || "send failed");
            }
            appendMessages(data.messages);
            setStatus(data.session);
        } catch (_) {
            const fallback = {
                id: 0,
                sender_type: "system",
                sender_display_name: "系統",
                body: "訊息送出失敗，請稍後再試。",
            };
            appendMessage(fallback);
        } finally {
            sending = false;
            sendButton && (sendButton.disabled = false);
            input.focus();
        }
    });

    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
})();
