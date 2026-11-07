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

    const tooltip = root.querySelector("[data-market-chart-tooltip]");
    const navigator = root.querySelector("[data-market-navigator]");
    const navWindow = root.querySelector("[data-market-nav-window]");
    const navHandles = Array.from(root.querySelectorAll("[data-market-nav-handle]"));
    const chartKpis = {
        last: root.querySelector("[data-market-chart-last]"),
        low: root.querySelector("[data-market-chart-low]"),
        high: root.querySelector("[data-market-chart-high]"),
        average: root.querySelector("[data-market-chart-avg]"),
        count: root.querySelector("[data-market-chart-count]"),
    };
    let selectedStart = null;
    let selectedEnd = null;
    let drag = null;
    const NAV_MINUTES = 15;

    const limitTo = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
    const marketExtent = () => {
        const first = allPoints[0]?.at.getTime() || 0;
        const last = allPoints[allPoints.length - 1]?.at.getTime() || first;
        return { first, last, span: Math.max(1, last - first) };
    };

    const renderNavigator = () => {
        if (!navigator || !navWindow || !allPoints.length) return;
        const { first, span } = marketExtent();
        const prices = allPoints.map((point) => point.price);
        const low = Math.min(...prices);
        const priceSpan = Math.max(1, Math.max(...prices) - low);
        const xFor = (point) => ((point.at.getTime() - first) / span) * 1000;
        const yFor = (point) => 60 - ((point.price - low) / priceSpan) * 45;
        const every = Math.max(1, Math.ceil(allPoints.length / 1300));
        const plotted = allPoints.filter((_point, i) => i % every === 0 || i === allPoints.length - 1);
        const line = plotted.map((point) => xFor(point).toFixed(2) + "," + yFor(point).toFixed(2)).join(" ");
        let svg = navigator.querySelector("svg");
        if (!svg) {
            svg = makeSvgNode("svg", { viewBox: "0 0 1000 74", preserveAspectRatio: "none", "aria-hidden": "true" });
            navigator.insertBefore(svg, navWindow);
        }
        svg.replaceChildren();
        svg.appendChild(makeSvgNode("polygon", {
            points: "0,74 " + line.replace(/,/g, ",") + " 1000,74",
            class: "market-item-chart-nav-area",
        }));
        svg.appendChild(makeSvgNode("polyline", { points: line, class: "market-item-chart-nav-line" }));
        const left = limitTo(((selectedStart - first) / span) * 100, 0, 100);
        const right = limitTo(((selectedEnd - first) / span) * 100, 0, 100);
        navWindow.style.left = left + "%";
        navWindow.style.width = Math.max(0, right - left) + "%";
        for (const handle of navHandles) {
            const isStart = handle.dataset.marketNavHandle === "start";
            handle.setAttribute("aria-valuemin", "0");
            handle.setAttribute("aria-valuemax", "100");
            handle.setAttribute("aria-valuenow", String(Math.round(isStart ? left : right)));
            handle.setAttribute("aria-valuetext", formatFullTime(new Date(isStart ? selectedStart : selectedEnd)));
        }
    };

    const renderChartSelection = () => {
        if (!allPoints.length || selectedStart === null || selectedEnd === null) return;
        renderNavigator();
        const points = allPoints.filter((point) => {
            const at = point.at.getTime();
            return at >= selectedStart && at <= selectedEnd;
        });
        if (!points.length) {
            setEmpty("所選區間沒有價格紀錄，可拖曳下方範圍選擇其他時間。");
            return;
        }
        if (empty) empty.hidden = true;
        if (tooltip) tooltip.hidden = true;

        const width = 1000, height = 340, left = 70, right = 26, top = 26, bottom = 52;
        const drawWidth = width - left - right, drawHeight = height - top - bottom;
        const prices = points.map((point) => point.price);
        const low = Math.min(...prices), high = Math.max(...prices);
        const average = prices.reduce((sum, value) => sum + value, 0) / prices.length;
        const padding = Math.max(1, (high - low) * 0.12);
        const minPrice = low - padding, maxPrice = high + padding;
        const ySpan = Math.max(1, maxPrice - minPrice);
        const timeSpan = Math.max(1, selectedEnd - selectedStart);
        const xFor = (point) => left + ((point.at.getTime() - selectedStart) / timeSpan) * drawWidth;
        const yFor = (price) => top + ((maxPrice - price) / ySpan) * drawHeight;
        const svg = makeSvgNode("svg", {
            viewBox: "0 0 " + width + " " + height,
            role: "img",
            "aria-label": "互動價格走勢；滑鼠懸停或點按即可查看單點時間與價格",
            preserveAspectRatio: "none",
        });

        for (let i = 0; i <= 4; i += 1) {
            const y = top + drawHeight * i / 4;
            svg.appendChild(makeSvgNode("line", {
                x1: left, x2: width - right, y1: y, y2: y,
                class: "market-item-chart-grid-line",
            }));
            const label = makeSvgNode("text", {
                x: left - 11, y: y + 5, "text-anchor": "end",
                class: "market-item-chart-axis-label",
            });
            label.textContent = String(Math.round(maxPrice - ySpan * i / 4));
            svg.appendChild(label);
        }
        for (let i = 0; i <= 5; i += 1) {
            const stamp = selectedStart + timeSpan * i / 5;
            const x = left + drawWidth * i / 5;
            const label = makeSvgNode("text", {
                x: x, y: height - 14, "text-anchor": "middle",
                class: "market-item-chart-axis-label market-item-chart-time-label",
            });
            label.textContent = formatTime(new Date(stamp));
            svg.appendChild(label);
        }

        const avgLine = makeSvgNode("line", {
            x1: left, x2: width - right, y1: yFor(average), y2: yFor(average),
            class: "market-item-chart-average-line",
        });
        svg.appendChild(avgLine);
        const averageText = makeSvgNode("text", {
            x: width - right - 3, y: Math.max(15, yFor(average) - 6),
            "text-anchor": "end", class: "market-item-chart-average-label",
        });
        averageText.textContent = "均 " + formatPrice(average);
        svg.appendChild(averageText);

        const stride = Math.max(1, Math.ceil(points.length / 1500));
        const plotted = points.filter((_point, i) => i % stride === 0 || i === points.length - 1);
        const line = plotted.map((point) => xFor(point).toFixed(2) + "," + yFor(point.price).toFixed(2)).join(" ");
        if (points.length > 1) {
            svg.appendChild(makeSvgNode("polygon", {
                points: xFor(plotted[0]).toFixed(2) + "," + (height - bottom) +
                    " " + line + " " + xFor(plotted[plotted.length - 1]).toFixed(2) + "," + (height - bottom),
                class: "market-item-chart-area",
            }));
            svg.appendChild(makeSvgNode("polyline", {
                points: line, class: "market-item-chart-line",
            }));
        }
        if (points.length <= 100) {
            for (const point of points) {
                svg.appendChild(makeSvgNode("circle", {
                    cx: xFor(point), cy: yFor(point.price), r: 2.8,
                    class: "market-item-chart-point",
                }));
            }
        }
        const marker = makeSvgNode("line", {
            x1: 0, x2: 0, y1: top, y2: height - bottom,
            class: "market-item-chart-cursor",
        });
        const dot = makeSvgNode("circle", {
            cx: 0, cy: 0, r: 6, class: "market-item-chart-active-point",
        });
        marker.style.display = "none";
        dot.style.display = "none";
        svg.append(marker, dot);

        stage.querySelectorAll("svg").forEach((node) => node.remove());
        stage.appendChild(svg);

        const nearestPoint = (x) => {
            let lowIndex = 0, highIndex = points.length - 1;
            while (lowIndex < highIndex) {
                const mid = Math.floor((lowIndex + highIndex) / 2);
                if (xFor(points[mid]) < x) lowIndex = mid + 1;
                else highIndex = mid;
            }
            const after = lowIndex, before = Math.max(0, after - 1);
            return Math.abs(xFor(points[before]) - x) < Math.abs(xFor(points[after]) - x)
                ? points[before] : points[after];
        };
        const focusPoint = (event) => {
            const rect = svg.getBoundingClientRect();
            if (!rect.width) return;
            const unitX = ((event.clientX - rect.left) / rect.width) * width;
            if (unitX < left || unitX > width - right) {
                if (tooltip) tooltip.hidden = true;
                marker.style.display = "none";
                dot.style.display = "none";
                return;
            }
            const point = nearestPoint(unitX);
            const x = xFor(point), y = yFor(point.price);
            marker.setAttribute("x1", x);
            marker.setAttribute("x2", x);
            dot.setAttribute("cx", x);
            dot.setAttribute("cy", y);
            marker.style.display = "";
            dot.style.display = "";
            if (tooltip) {
                tooltip.hidden = false;
                tooltip.textContent = formatFullTime(point.at) + "　｜　單顆價格 " + formatPrice(point.price);
                tooltip.style.left = limitTo((x / width) * 100, 20, 80) + "%";
                tooltip.style.top = limitTo((y / height) * 100, 20, 84) + "%";
            }
        };
        svg.addEventListener("pointermove", focusPoint);
        svg.addEventListener("pointerdown", focusPoint);
        svg.addEventListener("pointerleave", (event) => {
            if (event.pointerType === "mouse") {
                if (tooltip) tooltip.hidden = true;
                marker.style.display = "none";
                dot.style.display = "none";
            }
        });

        setText(chartKpis.last, formatPrice(points[points.length - 1].price));
        setText(chartKpis.low, formatPrice(low));
        setText(chartKpis.high, formatPrice(high));
        setText(chartKpis.average, formatPrice(average));
        setText(chartKpis.count, points.length + " 筆");
        const hours = (selectedEnd - selectedStart) / HOUR;
        if (chartStatus) {
            chartStatus.textContent = "已選範圍 " + formatTime(new Date(selectedStart)) +
                " 至 " + formatTime(new Date(selectedEnd)) +
                " · " + describeCoverage(hours) +
                " · 目前保留 " + describeCoverage(coverageHours()) + " 歷史";
        }
        if (foot) {
            foot.textContent = "區間最低 " + formatPrice(low) + "　｜　最高 " +
                formatPrice(high) + "　｜　均價 " + formatPrice(average) +
                "　｜　資料點 " + points.length + " 筆";
        }
    };

    const renderChart = (hours) => {
        if (!allPoints.length) return setEmpty("目前沒有可繪製的歷史價格。");
        const { first, last } = marketExtent();
        const duration = hours <= 0 ? last - first : hours * HOUR;
        selectedEnd = last;
        selectedStart = Math.max(first, last - duration);
        renderChartSelection();
    };

    const activateRange = (button) => {
        rangeButtons.forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
        const hours = Number.parseInt(button.dataset.marketRange || "0", 10);
        renderChart(Number.isFinite(hours) ? hours : 12);
    };

    const onNavigatorKey = (event) => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        if (!allPoints.length) return;
        event.preventDefault();
        const { first, last, span } = marketExtent();
        const minimum = Math.min(span, Math.max(NAV_MINUTES * 60000, span * 0.01));
        const step = Math.max(60000, span / 80);
        const direction = event.key === "ArrowRight" ? 1 : -1;
        if (event.currentTarget.dataset.marketNavHandle === "start") {
            selectedStart = limitTo(selectedStart + direction * step, first, selectedEnd - minimum);
        } else {
            selectedEnd = limitTo(selectedEnd + direction * step, selectedStart + minimum, last);
        }
        rangeButtons.forEach((button) => button.classList.remove("is-active"));
        renderChartSelection();
    };

    if (navigator) {
        const beginDrag = (event) => {
            if (!allPoints.length) return;
            if (event.button !== undefined && event.button !== 0) return;
            const rect = navigator.getBoundingClientRect();
            if (!rect.width) return;
            const { first, last, span } = marketExtent();
            const handle = event.target.closest("[data-market-nav-handle]");
            const inWindow = event.target.closest("[data-market-nav-window]");
            const mode = handle ? handle.dataset.marketNavHandle : inWindow ? "move" : "jump";
            drag = { mode, pointer: event.pointerId, x: event.clientX,
                start: selectedStart, end: selectedEnd, rectWidth: rect.width, first, last, span };
            if (mode === "jump") {
                const center = first + limitTo((event.clientX - rect.left) / rect.width, 0, 1) * span;
                const duration = selectedEnd - selectedStart;
                selectedStart = limitTo(center - duration / 2, first, last - duration);
                selectedEnd = selectedStart + duration;
                drag.mode = "move";
                drag.start = selectedStart;
                drag.end = selectedEnd;
            }
            navigator.setPointerCapture(event.pointerId);
            event.preventDefault();
            renderChartSelection();
        };
        const updateDrag = (event) => {
            if (!drag || drag.pointer !== event.pointerId) return;
            const delta = ((event.clientX - drag.x) / drag.rectWidth) * drag.span;
            const minimum = Math.min(drag.span, Math.max(NAV_MINUTES * 60000, drag.span * 0.01));
            if (drag.mode === "start") {
                selectedStart = limitTo(drag.start + delta, drag.first, drag.end - minimum);
            } else if (drag.mode === "end") {
                selectedEnd = limitTo(drag.end + delta, drag.start + minimum, drag.last);
            } else {
                const duration = drag.end - drag.start;
                selectedStart = limitTo(drag.start + delta, drag.first, drag.last - duration);
                selectedEnd = selectedStart + duration;
            }
            rangeButtons.forEach((button) => button.classList.remove("is-active"));
            renderChartSelection();
        };
        const endDrag = (event) => {
            if (!drag || drag.pointer !== event.pointerId) return;
            drag = null;
            try { navigator.releasePointerCapture(event.pointerId); } catch (_error) {}
        };
        navigator.addEventListener("pointerdown", beginDrag);
        navigator.addEventListener("pointermove", updateDrag);
        navigator.addEventListener("pointerup", endDrag);
        navigator.addEventListener("pointercancel", endDrag);
        navHandles.forEach((handle) => handle.addEventListener("keydown", onNavigatorKey));
    }

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
