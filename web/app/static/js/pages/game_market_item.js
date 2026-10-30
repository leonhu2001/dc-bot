(() => {
    "use strict";

    const root = document.querySelector("[data-market-chart]");
    if (!root) return;

    const stage = root.querySelector("[data-market-chart-stage]");
    const empty = root.querySelector("[data-market-chart-empty]");
    const foot = root.querySelector("[data-market-chart-foot]");
    const rangeButtons = Array.from(root.querySelectorAll("[data-market-range]"));
    const historyUrl = String(root.dataset.historyUrl || "").trim();
    const svgNS = "http://www.w3.org/2000/svg";
    let allPoints = [];

    const formatPrice = (value) => `$${Math.round(value).toLocaleString("zh-TW")}`;
    const formatTime = (date) => new Intl.DateTimeFormat("zh-TW", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
    }).format(date);

    const setEmpty = (message) => {
        stage.querySelectorAll("svg").forEach((node) => node.remove());
        if (empty) {
            empty.hidden = false;
            empty.textContent = message;
        }
        if (foot) foot.textContent = "";
    };

    const makeSvgNode = (name, attributes = {}) => {
        const node = document.createElementNS(svgNS, name);
        Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
        return node;
    };

    const filterPoints = (hours) => {
        if (!allPoints.length) return [];
        const newest = allPoints[allPoints.length - 1].at.getTime();
        const cutoff = newest - (hours * 60 * 60 * 1000);
        const filtered = allPoints.filter((point) => point.at.getTime() >= cutoff);
        return filtered.length ? filtered : allPoints.slice(-1);
    };

    const renderChart = (hours) => {
        const points = filterPoints(hours);
        if (!points.length) {
            setEmpty("目前沒有可繪製的歷史價格。");
            return;
        }

        const width = 1000;
        const height = 320;
        const padX = 34;
        const padY = 28;
        const prices = points.map((point) => point.price);
        let minPrice = Math.min(...prices);
        let maxPrice = Math.max(...prices);

        if (minPrice === maxPrice) {
            const padding = Math.max(1, Math.round(minPrice * 0.03));
            minPrice -= padding;
            maxPrice += padding;
        }

        const firstTime = points[0].at.getTime();
        const lastTime = points[points.length - 1].at.getTime();
        const timeSpan = Math.max(1, lastTime - firstTime);
        const priceSpan = Math.max(1, maxPrice - minPrice);

        const xFor = (at) => padX + ((at.getTime() - firstTime) / timeSpan) * (width - padX * 2);
        const yFor = (price) => height - padY - ((price - minPrice) / priceSpan) * (height - padY * 2);

        const svg = makeSvgNode("svg", {
            viewBox: `0 0 ${width} ${height}`,
            role: "img",
            "aria-label": `價格走勢，共 ${points.length} 個資料點`,
            preserveAspectRatio: "none",
        });

        for (let index = 0; index <= 4; index += 1) {
            const y = padY + ((height - padY * 2) / 4) * index;
            svg.appendChild(makeSvgNode("line", {
                x1: padX,
                x2: width - padX,
                y1: y,
                y2: y,
                class: "market-item-chart-grid-line",
            }));
        }

        if (points.length === 1) {
            svg.appendChild(makeSvgNode("circle", {
                cx: width / 2,
                cy: yFor(points[0].price),
                r: 5,
                class: "market-item-chart-line",
            }));
        } else {
            const polylinePoints = points
                .map((point) => `${xFor(point.at).toFixed(2)},${yFor(point.price).toFixed(2)}`)
                .join(" ");
            svg.appendChild(makeSvgNode("polyline", {
                points: polylinePoints,
                class: "market-item-chart-line",
            }));
        }

        stage.querySelectorAll("svg").forEach((node) => node.remove());
        if (empty) empty.hidden = true;
        stage.appendChild(svg);

        if (foot) {
            foot.textContent = [
                `${formatTime(points[0].at)} → ${formatTime(points[points.length - 1].at)}`,
                `低 ${formatPrice(Math.min(...prices))}`,
                `高 ${formatPrice(Math.max(...prices))}`,
                `${points.length} 筆`,
            ].join(" · ");
        }
    };

    const activateRange = (button) => {
        rangeButtons.forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
        const hours = Number.parseInt(button.dataset.marketRange || "168", 10);
        renderChart(Number.isFinite(hours) ? hours : 168);
    };

    rangeButtons.forEach((button) => {
        button.addEventListener("click", () => activateRange(button));
    });

    if (!historyUrl) {
        setEmpty("歷史行情 API 尚未設定。");
        return;
    }

    fetch(historyUrl, { headers: { Accept: "application/json" } })
        .then((response) => {
            if (!response.ok) throw new Error(`history request failed: ${response.status}`);
            return response.json();
        })
        .then((payload) => {
            const rawPoints = Array.isArray(payload.points) ? payload.points : [];
            allPoints = rawPoints
                .map((point) => ({
                    at: new Date(point.at),
                    price: Number(point.price),
                }))
                .filter((point) => !Number.isNaN(point.at.getTime()) && Number.isFinite(point.price) && point.price > 0)
                .sort((left, right) => left.at - right.at);

            if (!allPoints.length) {
                setEmpty("目前尚未累積足夠的歷史價格。");
                return;
            }

            const activeButton = rangeButtons.find((button) => button.classList.contains("is-active")) || rangeButtons[0];
            if (activeButton) activateRange(activeButton);
            else renderChart(168);
        })
        .catch(() => {
            setEmpty("歷史價格暫時無法讀取，請以交易所行情頁的資料狀態為準。");
        });
})();
