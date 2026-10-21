(() => {
    const root = document.getElementById("vipTimerLive");
    if (!root) return;

    const statusUrl = root.dataset.statusUrl;
    if (!statusUrl) return;

    const el = (id) => document.getElementById(id);
    const fmtDuration = (rawSeconds) => {
        const seconds = Math.max(0, Number(rawSeconds || 0));
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        if (hours > 0) return `${hours} 小時 ${minutes} 分`;
        if (minutes > 0) return `${minutes} 分 ${secs} 秒`;
        return `${secs} 秒`;
    };
    const fmtMoney = (value) => `${Number(value || 0).toLocaleString("zh-TW")}T`;
    const statusText = {
        waiting_staff: "等待接單",
        ready: "等待開始",
        running: "計時中",
        paused: "已暫停",
        pending_payment: "待付款",
        paid: "已付款",
        cancelled: "已取消",
    };

    let polling = true;

    const renderSegments = (segments) => {
        const host = el("vipTimerSegments");
        if (!host) return;
        host.replaceChildren();
        if (!Array.isArray(segments) || segments.length === 0) {
            const empty = document.createElement("p");
            empty.className = "customer-detail-note";
            empty.textContent = "尚未建立計時區段。";
            host.appendChild(empty);
            return;
        }
        segments.forEach((segment) => {
            const row = document.createElement("div");
            row.className = "customer-detail-item";
            const small = document.createElement("small");
            small.textContent = `#${segment.seq} · ${segment.category_label || ""}`;
            const strong = document.createElement("strong");
            strong.textContent = `${segment.rule_label || ""}｜${Number(segment.hourly_rate || 0).toLocaleString("zh-TW")}T/H｜${fmtDuration(segment.seconds)}`;
            row.append(small, strong);
            host.appendChild(row);
        });
    };

    const render = (data) => {
        if (!data || !data.ok) return;
        if (el("vipTimerStatus")) el("vipTimerStatus").textContent = statusText[data.status] || data.status;
        if (el("vipTimerCategory")) el("vipTimerCategory").textContent = data.current_category_label || "-";
        if (el("vipTimerRule")) el("vipTimerRule").textContent = data.current_rule_label || "-";
        if (el("vipTimerRate")) el("vipTimerRate").textContent = `${Number(data.current_hourly_rate || 0).toLocaleString("zh-TW")}T/H`;
        if (el("vipTimerDuration")) el("vipTimerDuration").textContent = fmtDuration(data.live_seconds);
        if (el("vipTimerVip")) el("vipTimerVip").textContent = `${data.vip_name || "VIP"} · ${Number(data.vip_discount_pay_rate || 100)}%`;
        if (el("vipTimerPay")) {
            el("vipTimerPay").textContent = fmtMoney(data.status === "pending_payment" || data.status === "paid" ? data.final_amount : data.customer_preview);
        }
        const notice = el("vipTimerNotice");
        if (notice) {
            if (data.end_confirmation_pending) {
                notice.textContent = "目前已有一方提出結束申請，等待另一方確認；確認完成前不會結算。";
            } else if (data.status === "pending_payment") {
                notice.textContent = `計時已結束，待付款 ${fmtDuration(data.pending_age_seconds)}。付款完成前無法再開新的 VIP 自由計時單。`;
            } else {
                notice.textContent = "15 分鐘最低計費；VIP 折扣固定使用開單當下等級。月券、點數與其他活動不適用。";
            }
        }
        renderSegments(data.segments);
        if (["paid", "cancelled"].includes(data.status)) polling = false;
    };

    const refresh = async () => {
        try {
            const response = await fetch(statusUrl, { credentials: "same-origin", cache: "no-store" });
            if (!response.ok) return;
            render(await response.json());
        } catch (_) {
            // Keep the last known state; the next poll can recover.
        }
    };

    refresh();
    const timer = window.setInterval(() => {
        if (!polling) {
            window.clearInterval(timer);
            return;
        }
        refresh();
    }, 5000);
})();
