async function loadOverview() {
    const res = await fetch('/api/intelligence/overview');
    const data = await res.json();
    const c = document.getElementById('overview-metrics');

    if (data.total_signals === 0 || data.error) {
        c.innerHTML = `
            <div class="metric-card"><h3>Total Signals</h3><div class="val">0</div></div>
            <div class="metric-card"><h3>Executed</h3><div class="val">0</div></div>
            <div class="metric-card"><h3>Rejected</h3><div class="val">0</div></div>
            <div class="metric-card"><h3>Exec Quality</h3><div class="val" style="font-size:14px;color:var(--text-secondary)">Collecting Data</div></div>
            <div class="metric-card"><h3>Success Rate</h3><div class="val" style="font-size:14px;color:var(--text-secondary)">Insufficient Samples</div></div>
            <div class="metric-card"><h3>Avg Target Time</h3><div class="val" style="font-size:14px;color:var(--text-secondary)">Waiting for Signals</div></div>
        `;
        return;
    }

    c.innerHTML = `
        <div class="metric-card"><h3>Total Signals</h3><div class="val">${data.total_signals}</div></div>
        <div class="metric-card"><h3>Executed</h3><div class="val">${data.executed}</div></div>
        <div class="metric-card"><h3>Rejected</h3><div class="val">${data.rejected}</div></div>
        <div class="metric-card"><h3>Exec Quality</h3><div class="val">${data.execution_quality_pct}%</div></div>
        <div class="metric-card"><h3>Success Rate</h3><div class="val">${data.overall_success_rate}%</div></div>
        <div class="metric-card"><h3>Avg Target Time</h3><div class="val">${data.avg_target_time}s</div></div>
    `;
}