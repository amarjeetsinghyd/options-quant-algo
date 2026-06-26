// ==========================================
// Phase 4.1 Advanced Sensors JS
// ==========================================

async function loadPhase41Data() {
    try {
        const [ofaRes, targetRes, failureRes, vfiRes] = await Promise.all([
            fetch('/api/intelligence/ofa_health').then(r => r.json()),
            fetch('/api/intelligence/target_opt').then(r => r.json()),
            fetch('/api/intelligence/failure_dna').then(r => r.json()),
            fetch('/api/intelligence/vfi_edge').then(r => r.json())
        ]);

        renderOfaHealth(ofaRes);
        renderTargetOpt(targetRes);
        renderFailureDna(failureRes);
        renderVfiEdge(vfiRes);
    } catch (e) {
        console.error("Error loading Phase 4.1 data", e);
    }
}

function renderOfaHealth(data) {
    if (data.error || !data.trends) return;
    
    let html = `
        <div class="metric-card">
            <div class="metric-label">Avg Stability / Consistency</div>
            <div class="metric-value">${data.avg_consistency}%</div>
        </div>
    `;
    
    data.trends.forEach(t => {
        html += `
        <div class="metric-card">
            <div class="metric-label">Trend: ${t.trend} (${t.count} trades)</div>
            <div class="metric-value">${t.win_rate}% Win <span style="font-size:12px;color:var(--text-secondary)">Decay: ${t.avg_decay}</span></div>
        </div>`;
    });
    
    document.getElementById('ofa-health-metrics').innerHTML = html;
}

function renderTargetOpt(data) {
    if (data.error || !data.target_5) return;
    
    const tbody = document.querySelector('#target-opt-table tbody');
    let html = '';
    
    const targets = [
        {name: "5%", data: data.target_5},
        {name: "10% (Live Target)", data: data.target_10},
        {name: "15%", data: data.target_15},
        {name: "20%", data: data.target_20}
    ];
    
    targets.forEach(t => {
        let highlight = t.name.includes("10%") ? 'style="font-weight:bold; color:var(--primary)"' : '';
        html += `
            <tr ${highlight}>
                <td>${t.name}</td>
                <td>${t.data.hit_rate}%</td>
                <td>${t.data.avg_time}s</td>
            </tr>
        `;
    });
    
    // Add Post Target Runner metric if available
    if (data.post_target_runner) {
        html += `
            <tr style="border-top: 1px solid var(--border)">
                <td>Post-Target Runner Avg</td>
                <td colspan="2" style="color:var(--success)">+${data.post_target_runner}%</td>
            </tr>
        `;
    }
    
    tbody.innerHTML = html;
}

function renderFailureDna(data) {
    if (data.error || !data.total_failures) return;
    
    document.getElementById('failure-dna-metrics').innerHTML = `
        <div class="metric-card">
            <div class="metric-label">Avg Max Profit Before Failure</div>
            <div class="metric-value">${data.avg_max_profit_before_fail}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Time Survived Before Failure</div>
            <div class="metric-value">${data.avg_time_before_fail}s</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Failed After Moving > 5%</div>
            <div class="metric-value">${data.failed_after_positive_move_pct}%</div>
        </div>
    `;
}

function renderVfiEdge(data) {
    if (data.error || data.strong_cross_win_rate === undefined) return;
    
    document.getElementById('vfi-edge-metrics').innerHTML = `
        <div class="metric-card">
            <div class="metric-label">Strong Cross Win Rate</div>
            <div class="metric-value" style="color:var(--success)">${data.strong_cross_win_rate}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Weak Cross Win Rate</div>
            <div class="metric-value" style="color:var(--warning)">${data.weak_cross_win_rate}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Avg VFI Angle</div>
            <div class="metric-value">${data.avg_vfi_angle}</div>
        </div>
    `;
}

// Add hook into main initialization
document.addEventListener('DOMContentLoaded', () => {
    // Wait for main data to load, then load Phase 4.1
    setTimeout(loadPhase41Data, 1000);
});
