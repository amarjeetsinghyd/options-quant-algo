async function loadMarket() {
    const res = await fetch('/api/intelligence/market');
    const data = await res.json();
    const c = document.getElementById('market-metrics');
    c.innerHTML = `
        <div class="metric-card"><h3>Best Window</h3><div class="val" style="color:#00d2ff">${data.best_window}</div></div>
        <div class="metric-card"><h3>Avg VWAP Dist</h3><div class="val">${data.avg_vwap_dist}%</div></div>
        <div class="metric-card"><h3>Avg VFI Strength</h3><div class="val">${data.avg_vfi}</div></div>
    `;
}