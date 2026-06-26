async function fetchPhase43Panels() {
    try {
        const [regimeRes, atrRes, vwapRes, vfiRes, qualityRes] = await Promise.all([
            fetch('/api/intelligence/market_regime').then(r => r.json()),
            fetch('/api/intelligence/atr_intel').then(r => r.json()),
            fetch('/api/intelligence/vwap_health').then(r => r.json()),
            fetch('/api/intelligence/vfi_intel').then(r => r.json()),
            fetch('/api/intelligence/trade_quality').then(r => r.json())
        ]);

        renderMarketRegime(regimeRes);
        renderAtrIntel(atrRes);
        renderVwapHealth(vwapRes);
        renderVfiIntel(vfiRes);
        renderTradeQuality(qualityRes);
    } catch (e) {
        console.error("Error loading Phase 4.3 panels:", e);
    }
}

function renderMarketRegime(data) {
    const el = document.getElementById('market-regime-content');
    if (!el) return;
    if (!data || !data.regimes || data.regimes.length === 0) {
        el.innerHTML = `<div class="stat-value">Collecting Data</div>`;
        return;
    }
    
    let html = `<div class="info-grid" style="grid-template-columns: 1fr 1fr; gap: 15px;">`;
    html += `<div class="info-card">
                <div class="info-label" style="margin-bottom: 5px;">Best Condition</div>
                <div class="info-value text-green" style="font-size: 1.1em; font-weight: bold;">${data.best_regime.regime || 'N/A'}</div>
                <div class="info-sub" style="margin-top: 5px; opacity: 0.8;">${data.best_regime.hit_rate}% Hit Rate</div>
             </div>`;
    html += `<div class="info-card">
                <div class="info-label" style="margin-bottom: 5px;">Worst Condition</div>
                <div class="info-value text-red" style="font-size: 1.1em; font-weight: bold;">${data.worst_regime.regime || 'N/A'}</div>
                <div class="info-sub" style="margin-top: 5px; opacity: 0.8;">${data.worst_regime.hit_rate}% Hit Rate</div>
             </div>`;
    html += `</div>`;
    el.innerHTML = html;
}

function renderAtrIntel(data) {
    const el = document.getElementById('atr-intel-content');
    if (!el) return;
    if (!data || data.expanding_hit_rate === undefined) {
        el.innerHTML = `<div class="stat-value">Collecting Data</div>`;
        return;
    }

    el.innerHTML = `
        <div class="table-container">
            <table class="data-table">
                <thead><tr><th style="text-align:left">ATR State</th><th>Hit Rate</th></tr></thead>
                <tbody>
                    <tr><td style="text-align:left">Expanding (>1.3)</td><td class="text-green" style="font-weight:bold">${data.expanding_hit_rate}%</td></tr>
                    <tr><td style="text-align:left">Normal (0.8 - 1.3)</td><td class="text-yellow" style="font-weight:bold">${data.normal_hit_rate}%</td></tr>
                    <tr><td style="text-align:left">Compressed (<0.8)</td><td class="text-red" style="font-weight:bold">${data.compressed_hit_rate}%</td></tr>
                </tbody>
            </table>
        </div>
    `;
}

function renderVwapHealth(data) {
    const el = document.getElementById('vwap-health-content');
    if (!el) return;
    if (!data || !data.zones || data.zones.length === 0) {
        el.innerHTML = `<div class="stat-value">Collecting Data</div>`;
        return;
    }

    let rows = data.zones.map(z => `
        <tr>
            <td style="text-align:left">${z.zone}</td>
            <td>${z.count}</td>
            <td style="font-weight:bold">${z.hit_rate}%</td>
        </tr>
    `).join('');

    el.innerHTML = `
        <div style="margin-bottom: 15px; font-size: 0.9em;"><strong>Optimal Distance:</strong> <span class="text-blue">${data.best_zone}</span></div>
        <div class="table-container">
            <table class="data-table">
                <thead><tr><th style="text-align:left">EMA-VWAP Distance</th><th>Trades</th><th>Hit Rate</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function renderVfiIntel(data) {
    const el = document.getElementById('vfi-intel-content');
    if (!el) return;
    if (!data || !data.alignments || data.alignments.length === 0) {
        el.innerHTML = `<div class="stat-value">Collecting Data</div>`;
        return;
    }

    let rows = data.alignments.map(a => `
        <tr>
            <td style="text-align:left">${a.alignment.replace('_', ' ')}</td>
            <td>${a.count}</td>
            <td style="font-weight:bold">${a.hit_rate}%</td>
        </tr>
    `).join('');

    el.innerHTML = `
        <div class="table-container">
            <table class="data-table">
                <thead><tr><th style="text-align:left">VFI Price Alignment</th><th>Trades</th><th>Hit Rate</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function renderTradeQuality(data) {
    const el = document.getElementById('trade-quality-content');
    if (!el) return;
    if (!data || data.length === 0) {
        el.innerHTML = `<div class="stat-value">Collecting Data</div>`;
        return;
    }

    let rows = data.map(b => {
        let colorClass = b.bucket.includes('Elite') ? 'text-green' : 
                         b.bucket.includes('Good') ? 'text-blue' :
                         b.bucket.includes('Average') ? 'text-yellow' : 'text-red';
        return `
            <tr>
                <td style="text-align:left"><strong class="${colorClass}">${b.bucket}</strong></td>
                <td>${b.count}</td>
                <td style="font-weight:bold">${b.hit_rate}%</td>
            </tr>
        `;
    }).join('');

    el.innerHTML = `
        <div class="table-container">
            <table class="data-table">
                <thead><tr><th style="text-align:left">Quality Bucket</th><th>Trades</th><th>Hit Rate</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}
