(() => {
    "use strict";

    const root = document.querySelector("[data-market-chart]");
    if (!root) return;

    const stage = root.querySelector("[data-market-chart-stage]");
    const empty = root.querySelector("[data-market-chart-empty]");
    const foot = root.querySelector("[data-market-chart-foot]");
    const chartStatus = root.querySelector("[data-market-chart-status]");
    const rangeButtons = Array.from(root.querySelectorAll("[data-market-range]"));
    const historyUrl = String(root.dataset.historyUrl || "").trim();
    const latestTime = document.querySelector("[data-market-latest-at]");
    const change24 = document.querySelector("[data-market-change-24h]");
    const change24Note = document.querySelector("[data-market-change-24h-note]");
    const range24 = document.querySelector("[data-market-range-24h]");
    const average7d = document.querySelector("[data-market-average-7d]");
    const range7d = document.querySelector("[data-market-range-7d]");
    const coverage = document.querySelector("[data-market-coverage]");
    const coverageNote = document.querySelector("[data-market-coverage-note]");
    const compareRoot = document.querySelector("[data-market-compare]");
    const compareList = compareRoot?.querySelector("[data-market-compare-list]") || null;
    const compareCount = compareRoot?.querySelector("[data-market-compare-count]") || null;
    const svgNS = "http://www.w3.org/2000/svg";
    const HOUR = 60 * 60 * 1000;
    let allPoints = [];

    const formatPrice = (value) => `$${Math.round(value).toLocaleString("zh-TW")}`;
    const formatTime = (date) => new Intl.DateTimeFormat("zh-TW", {
        timeZone: "Asia/Taipei",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
    }).format(date);
    const formatFullTime = (date) => new Intl.DateTimeFormat("zh-TW", {
        timeZone: "Asia/Taipei",
        year: "numeric",
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

    const setText = (node, value) => {
        if (node) node.textContent = value;
    };

    const coverageHours = () => {
        if (allPoints.length < 2) return 0;
        return Math.max(0, (allPoints[allPoints.length - 1].at - allPoints[0].at) / HOUR);
    };

    const describeCoverage = (hours) => {
        if (hours < 1) return `${Math.max(0, Math.round(hours * 60))} 分鐘`;
        if (hours < 48) return `${hours.toFixed(1)} 小時`;
        return `${(hours / 24).toFixed(1)} 天`;
    };

    const updateLatestTime = () => {
        if (!latestTime) return;
        const parsed = new Date(latestTime.getAttribute("datetime") || "");
        if (!Number.isNaN(parsed.getTime())) latestTime.textContent = `${formatFullTime(parsed)}（台灣時間）`;
    };

    const calculateSummary = () => {
        if (!allPoints.length) return;

        const latest = allPoints[allPoints.length - 1];
        const totalCoverage = coverageHours();
        const cutoff24 = latest.at.getTime() - 24 * HOUR;
        const cutoff7d = latest.at.getTime() - 7 * 24 * HOUR;
        const baselineCandidates = allPoints.filter((point) => point.at.getTime() <= cutoff24);
        const baseline = baselineCandidates.length ? baselineCandidates[baselineCandidates.length - 1] : null;
        const baselineGap = baseline ? cutoff24 - baseline.at.getTime() : Number.POSITIVE_INFINITY;
        const baselineSpan = baseline ? (latest.at.getTime() - baseline.at.getTime()) / HOUR : 0;
        const ready24 = Boolean(baseline && baselineGap >= 0 && baselineGap <= 6 * HOUR && baselineSpan >= 20);

        if (ready24 && baseline) {
            const pct = ((latest.price - baseline.price) / baseline.price) * 100;
            const sign = pct > 0 ? "+" : "";
            setText(change24, `${sign}${pct.toFixed(1)}%`);
            change24?.classList.toggle("is-positive", pct > 0);
            change24?.classList.toggle("is-negative", pct < 0);
            setText(change24Note, `${formatPrice(baseline.price)} → ${formatPrice(latest.price)}`);

            const points24 = allPoints.filter((point) => point.at.getTime() >= cutoff24);
            const prices24 = [baseline.price, ...points24.map((point) => point.price)];
            setText(range24, `${formatPrice(Math.min(...prices24))} – ${formatPrice(Math.max(...prices24))}`);
        } else {
            setText(change24, "累積中");
            setText(range24, "累積中");
            setText(change24Note, `目前 ${describeCoverage(totalCoverage)}，至少需約 20 小時可信歷史`);
        }

        const points7d = allPoints.filter((point) => point.at.getTime() >= cutoff7d);
        const ready7d = totalCoverage >= 6 * 24 && points7d.length > 1;
        if (ready7d) {
            const prices7d = points7d.map((point) => point.price);
            const avg = prices7d.reduce((sum, value) => sum + value, 0) / prices7d.length;
            setText(average7d, formatPrice(avg));
            setText(range7d, `${formatPrice(Math.min(...prices7d))} – ${formatPrice(Math.max(...prices7d))}`);
        } else {
            setText(average7d, "累積中");
            setText(range7d, "累積中");
        }

        setText(coverage, describeCoverage(totalCoverage));
        setText(
            coverageNote,
            `${allPoints.length} 筆 · ${formatTime(allPoints[0].at)} → ${formatTime(latest.at)}`,
        );
    };

    const filterPoints = (hours) => {
        if (!allPoints.length) return [];
        const newest = allPoints[allPoints.length - 1].at.getTime();
        const cutoff = newest - (hours * HOUR);
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
        const padX = 54;
        const padY = 30;
        const prices = points.map((point) => point.price);
        let minPrice = Math.min(...prices);
        let maxPrice = Math.max(...prices);
        const average = prices.reduce((sum, value) => sum + value, 0) / prices.length;

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

        const averageLine = makeSvgNode("line", {
            x1: padX,
            x2: width - padX,
            y1: yFor(average),
            y2: yFor(average),
            class: "market-item-chart-average-line",
        });
        svg.appendChild(averageLine);

        const highLabel = makeSvgNode("text", {
            x: width - padX,
            y: padY - 8,
            "text-anchor": "end",
            class: "market-item-chart-axis-label",
        });
        highLabel.textContent = formatPrice(Math.max(...prices));
        svg.appendChild(highLabel);

        const lowLabel = makeSvgNode("text", {
            x: width - padX,
            y: height - 8,
            "text-anchor": "end",
            class: "market-item-chart-axis-label",
        });
        lowLabel.textContent = formatPrice(Math.min(...prices));
        svg.appendChild(lowLabel);

        if (points.length === 1) {
            svg.appendChild(makeSvgNode("circle", {
                cx: width / 2,
                cy: yFor(points[0].price),
                r: 5,
                class: "market-item-chart-point",
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

        const availableHours = Math.max(0, (lastTime - firstTime) / HOUR);
        if (chartStatus) {
            const requestedLabel = hours === 24 ? "24H" : hours === 168 ? "7D" : "30D";
            chartStatus.textContent = availableHours + 0.1 < hours
                ? `${requestedLabel} 視圖 · 目前實際累積 ${describeCoverage(coverageHours())}`
                : `${requestedLabel} 視圖 · 魔丸自有台服歷史`;
        }

        if (foot) {
            foot.textContent = [
                `${formatTime(points[0].at)} → ${formatTime(points[points.length - 1].at)}`,
                `低 ${formatPrice(Math.min(...prices))}`,
                `高 ${formatPrice(Math.max(...prices))}`,
                `均 ${formatPrice(average)}`,
                `${points.length} 筆`,
            ].join(" · ");
        }
    };

    const activateRange = (button) => {
        rangeButtons.forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
        const hours = Number.parseInt(button.dataset.marketRange || "168", 10);
        renderChart(Number.isFinite(hours) ? hours : 168);
    };

    const renderCompareEmpty = (message) => {
        if (!compareList) return;
        const node = document.createElement("div");
        node.className = "market-item-compare-empty";
        node.textContent = message;
        compareList.replaceChildren(node);
    };

    const loadComparison = async () => {
        if (!compareRoot || !compareList) return;
        const itemsUrl = String(compareRoot.dataset.marketItemsUrl || "").trim();
        const baseUrl = String(compareRoot.dataset.marketItemBaseUrl || "").trim();
        const currentCategory = String(compareRoot.dataset.marketCurrentCategory || "").trim();
        const currentKey = String(compareRoot.dataset.marketCurrentItemKey || "").trim();
        const currentPrice = Number(compareRoot.dataset.marketCurrentPrice || "0");
        if (!itemsUrl || !baseUrl || !currentCategory) {
            renderCompareEmpty("目前沒有可比較的同口徑資料。");
            setText(compareCount, "0 個品項");
            return;
        }

        try {
            const response = await fetch(itemsUrl, {
                cache: "no-store",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            });
            if (!response.ok) throw new Error(`comparison request failed: ${response.status}`);
            const payload = await response.json();
            const items = (Array.isArray(payload?.items) ? payload.items : [])
                .filter((item) => String(item?.category || "").trim() === currentCategory)
                .filter((item) => String(item?.item_key || "").trim() !== currentKey)
                .filter((item) => Number(item?.current_price) > 0)
                .sort((left, right) => {
                    const tierLeft = Number(left?.tier) || 99;
                    const tierRight = Number(right?.tier) || 99;
                    if (tierLeft !== tierRight) return tierLeft - tierRight;
                    return Number(left?.current_price) - Number(right?.current_price);
                });

            setText(compareCount, `${items.length} 個同口徑品項`);
            if (!items.length) {
                renderCompareEmpty("目前沒有其他同口徑品項可比較。");
                return;
            }

            compareList.replaceChildren();
            items.forEach((item) => {
                const price = Number(item.current_price);
                const delta = Number.isFinite(currentPrice) && currentPrice > 0 ? price - currentPrice : null;
                const link = document.createElement("a");
                link.className = "market-item-compare-row";
                link.href = `${baseUrl}${encodeURIComponent(String(item.item_key || ""))}`;

                const identity = document.createElement("div");
                const name = document.createElement("strong");
                name.textContent = String(item.name || item.item_key || "未命名品項");
                const meta = document.createElement("small");
                const tier = Number(item.tier);
                meta.textContent = Number.isInteger(tier) && tier > 0 ? `${tier}級 · ${currentCategory}` : currentCategory;
                identity.append(name, meta);

                const priceNode = document.createElement("strong");
                priceNode.className = "market-item-compare-price";
                priceNode.textContent = formatPrice(price);

                const deltaNode = document.createElement("span");
                deltaNode.className = "market-item-compare-delta";
                if (delta === null || delta === 0) {
                    deltaNode.textContent = delta === 0 ? "與本品同價" : "—";
                } else {
                    const sign = delta > 0 ? "+" : "−";
                    deltaNode.textContent = `比本品 ${sign}${formatPrice(Math.abs(delta))}`;
                    deltaNode.classList.add(delta > 0 ? "is-higher" : "is-lower");
                }

                link.append(identity, priceNode, deltaNode);
                compareList.appendChild(link);
            });
        } catch (_error) {
            renderCompareEmpty("同口徑比較暫時無法讀取，現價與歷史走勢仍可正常查看。");
            setText(compareCount, "讀取失敗");
        }
    };

    rangeButtons.forEach((button) => {
        button.addEventListener("click", () => activateRange(button));
    });

    updateLatestTime();
    loadComparison();

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

            calculateSummary();
            const activeButton = rangeButtons.find((button) => button.classList.contains("is-active")) || rangeButtons[0];
            if (activeButton) activateRange(activeButton);
            else renderChart(168);
        })
        .catch(() => {
            setEmpty("歷史價格暫時無法讀取，請以交易所行情頁的資料狀態為準。");
            setText(coverageNote, "歷史資料暫時無法讀取");
        });
})();
