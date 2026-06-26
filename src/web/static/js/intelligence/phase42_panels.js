async function fetchPhase42Panels() {
    try {
        const [healthRes, freshRes, confRes] = await Promise.all([
            fetch('/api/system_health').then(r => r.json()),
            fetch('/api/intelligence/freshness').then(r => r.json()),
            fetch('/api/intelligence/confidence').then(r => r.json())
        ]);

        renderSystemHealth(healthRes);
        renderDbFreshness(freshRes);
        renderConfidence(confRes);
    } catch (e) {
        console.error("Phase 4.2 Panels Error:", e);
    }
}

function renderSystemHealth(data) {
    const list = document.getElementById('system-health-list');
    if(!list) return;

    const apiColor = data.api_status === 'CONNECTED' ? 'var(--success)' : 'var(--text-secondary)';
    const wsColor = data.ws_health === 'CONNECTED' ? 'var(--success)' : 'var(--danger)';

    list.innerHTML = `
        <li class="insight-item">
            <span class="insight-label">API Status</span>
            <span class="insight-value" style="color: ${apiColor}">${data.api_status}</span>
        </li>
        <li class="insight-item">
            <span class="insight-label">WebSocket Health</span>
            <span class="insight-value" style="color: ${wsColor}">${data.ws_health}</span>
        </li>
        <li class="insight-item">
            <span class="insight-label">Last Tick Received</span>
            <span class="insight-value">${data.last_tick_age}</span>
        </li>
    `;
}

function renderDbFreshness(data) {
    const list = document.getElementById('db-freshness-list');
    if(!list) return;

    list.innerHTML = `
        <li class="insight-item">
            <span class="insight-label">Last DB Write</span>
            <span class="insight-value">${data.last_updated}</span>
        </li>
        <li class="insight-item">
            <span class="insight-label">Last Signal Time</span>
            <span class="insight-value">${data.last_signal_time}</span>
        </li>
        <li class="insight-item" style="flex-direction: column; align-items: flex-start;">
            <span class="insight-label" style="margin-bottom: 5px;">Last Signal Type</span>
            <span class="insight-value" style="font-size: 12px; background: rgba(0,0,0,0.2); padding: 4px 8px; border-radius: 4px;">${data.last_signal_type}</span>
        </li>
    `;
}

function renderConfidence(data) {
    const levelEl = document.getElementById('confidence-level');
    const msgEl = document.getElementById('confidence-msg');
    const sigEl = document.getElementById('conf-sig');
    const exeEl = document.getElementById('conf-exe');
    const rejEl = document.getElementById('conf-rej');

    if(!levelEl) return;

    levelEl.innerText = data.confidence_level;
    msgEl.innerText = data.message;
    sigEl.innerText = data.signals;
    exeEl.innerText = data.executed;
    rejEl.innerText = data.rejected;

    if (data.confidence_level.includes("HIGH")) {
        levelEl.style.color = "var(--success)";
    } else if (data.confidence_level.includes("MEDIUM")) {
        levelEl.style.color = "var(--warning)";
    } else if (data.confidence_level.includes("LOW")) {
        levelEl.style.color = "var(--danger)";
    } else {
        levelEl.style.color = "var(--text-secondary)";
    }
}
