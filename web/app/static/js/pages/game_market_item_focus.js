(() => {
    const card = document.querySelector('[data-market-restock-card]');
    if (!card) return;

    const overviewUrl = String(card.dataset.marketOverviewUrl || '').trim();
    const itemKey = String(card.dataset.marketItemKey || '').trim();
    if (!overviewUrl || !itemKey) return;

    const timeNode = card.querySelector('[data-restock-time]');
    const confidenceNode = card.querySelector('[data-restock-confidence]');
    const samplesNode = card.querySelector('[data-restock-samples]');
    const jitterNode = card.querySelector('[data-restock-jitter]');

    const setText = (node, value) => {
        if (node) node.textContent = value;
    };

    const loadPrediction = async () => {
        try {
            const response = await fetch(overviewUrl, {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: { Accept: 'text/html' },
            });
            if (!response.ok) return;

            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const row = Array.from(doc.querySelectorAll('[data-market-row]'))
                .find((candidate) => String(candidate.dataset.marketItemKey || '') === itemKey);
            if (!row) return;

            const predictedAt = String(row.dataset.marketRestockAt || '').trim();
            if (!predictedAt) return;

            const confidence = String(row.dataset.marketRestockConfidence || '').trim();
            const badge = Array.from(row.querySelectorAll('.game-market-value-badge'))
                .find((candidate) => String(candidate.textContent || '').includes('⏱'));
            const badgeText = String(badge?.textContent || '').trim();
            const title = String(badge?.getAttribute('title') || '');
            const timeText = badgeText
                .replace(/^⏱\s*/, '')
                .replace(/\s*·\s*\d+%\s*$/, '')
                .trim();
            const sampleMatch = title.match(/樣本\s*(\d+)\s*次/);
            const jitterMatch = title.match(/±\s*(\d+)\s*分鐘/);

            setText(timeNode, timeText || '—');
            setText(confidenceNode, confidence ? `${confidence}%` : '—');
            setText(samplesNode, sampleMatch ? `${sampleMatch[1]} 次` : '—');
            setText(jitterNode, jitterMatch ? `±${jitterMatch[1]} 分鐘` : '—');
            card.hidden = false;
        } catch (_error) {
            // Prediction is optional. Keep the detail page useful when unavailable.
        }
    };

    loadPrediction();
})();
