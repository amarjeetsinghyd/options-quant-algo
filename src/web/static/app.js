// app.js — Bloomberg-style Operations & Research Console 2.0
let dashboardMode = 'AUTO'; // 'AUTO', 'LIVE', or 'RESEARCH'
let activeMode = 'LIVE';    // Resolved active mode: 'LIVE' or 'RESEARCH'
let logSeverity = '';

document.addEventListener('DOMContentLoaded', () => {
    // Initial fetches
    refreshConsole();
    loadLogs();
    
    // 10-second polling interval (Strict Operational Performance Policy)
    setInterval(refreshConsole, 10000);
});

function refreshConsole() {
    resolveActiveMode();
    fetchStatus();
    fetchDatasetHealth();
    fetchAuditStatus();
    renderOverlayCharts();
    if (activeMode === 'RESEARCH') {
        loadSummaries('daily');
    }
}

// 1. OPERATION MODES CONTROLLER (AUTO / LIVE / RESEARCH)
function resolveActiveMode() {
    if (dashboardMode === 'AUTO') {
        const now = new Date();
        const day = now.getDay();
        const hour = now.getHours();
        const min = now.getMinutes();
        
        // Trading hours: Mon-Fri (1 to 5), 09:15 to 15:30
        const isWeekday = day >= 1 && day <= 5;
        const timeVal = hour * 60 + min;
        const isOpen = timeVal >= (9 * 60 + 15) && timeVal <= (15 * 60 + 30);
        
        if (isWeekday && isOpen) {
            activeMode = 'LIVE';
        } else {
            activeMode = 'RESEARCH';
        }
    } else {
        activeMode = dashboardMode;
    }
    
    // Toggle UI views based on active resolved mode
    const liveGroup = document.getElementById('live-mode-group');
    const researchGroup = document.getElementById('research-mode-group');
    
    if (activeMode === 'LIVE') {
        liveGroup.style.display = '';
        researchGroup.style.display = 'none';
    } else {
        liveGroup.style.display = 'none';
        researchGroup.style.display = '';
    }
}

function setDashboardMode(mode) {
    dashboardMode = mode;
    
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    if (mode === 'AUTO') document.getElementById('btn-mode-auto').classList.add('active');
    else if (mode === 'LIVE') document.getElementById('btn-mode-live').classList.add('active');
    else if (mode === 'RESEARCH') document.getElementById('btn-mode-research').classList.add('active');
    
    refreshConsole();
}

// 2. LIVE TELEMETRY DATA FETCHING
async function fetchStatus() {
    try {
        const response = await fetch('/api/status', { cache: 'no-store' });
        if (!response.ok) throw new Error("Offline");
        const data = await response.json();
        updateUI(data);
    } catch (e) {
        showSystemOffline();
    }
}

function showSystemOffline() {
    document.getElementById('hdr-engine-status').innerText = 'OFFLINE';
    document.getElementById('hdr-engine-status').className = 'val text-error';
    document.getElementById('hdr-lifecycle').innerText = 'OFFLINE';
    document.getElementById('hdr-lifecycle').className = 'val text-muted';
    
    const overviewStatus = document.getElementById('val-engine-status');
    if (overviewStatus) {
        overviewStatus.innerText = 'OFFLINE';
        overviewStatus.className = 'font-bold text-error';
    }
}

function updateUI(data) {
    const summary = data.service_summary || {};
    const perf = data.system_performance || {};
    const runtimeVal = data.runtime_validation || {};
    const startupVal = data.startup_validation || {};
    const services = data.service_status || {};
    const telemetry = data.telemetry || {};
    const stats = telemetry.strategy_stats || {};

    const serviceList = Object.values(services);
    const totalServices = serviceList.length;
    const runningServices = serviceList.filter(s => s.state === 'running').length;
    
    document.getElementById('hdr-engine-status').innerText = runningServices > 0 ? 'ACTIVE' : 'OFFLINE';
    document.getElementById('hdr-engine-status').className = 'val ' + (runningServices > 0 ? 'text-success' : 'text-error');
    
    document.getElementById('hdr-lifecycle').innerText = data.lifecycle_state || 'OFFLINE';
    document.getElementById('hdr-lifecycle').className = 'val ' + getLifecycleColorClass(data.lifecycle_state);
    
    document.getElementById('hdr-services').innerText = `${runningServices}/${totalServices}`;
    document.getElementById('hdr-sys-cpu').innerText = `${(perf.system_cpu_percent || 0.0).toFixed(1)}%`;
    document.getElementById('hdr-plat-cpu').innerText = `${(perf.platform_cpu_percent || 0.0).toFixed(1)}%`;
    document.getElementById('hdr-ram').innerText = `${(perf.total_ram_percent || 0.0).toFixed(1)}%`;
    document.getElementById('hdr-trades').innerText = data.history ? data.history.length : '0';
    
    let lastUpdateStr = '--:--:--';
    if (summary.last_update) {
        lastUpdateStr = formatISOToTime(summary.last_update);
    }
    document.getElementById('hdr-last-update').innerText = lastUpdateStr;

    const valEngineStatus = document.getElementById('val-engine-status');
    if (valEngineStatus) {
        valEngineStatus.innerText = runningServices > 0 ? 'ACTIVE' : 'OFFLINE';
        valEngineStatus.className = 'font-bold ' + (runningServices > 0 ? 'text-success' : 'text-error');
        document.getElementById('val-lifecycle-state').innerText = data.lifecycle_state || '--';
        document.getElementById('val-lifecycle-state').className = 'highlight font-bold ' + getLifecycleColorClass(data.lifecycle_state);
        document.getElementById('val-platform-ver').innerText = summary.platform_version || '1.0.0';
        document.getElementById('val-engine-pid').innerText = summary.engine_pid || '--';
        
        const maxUptime = serviceList.length > 0 ? Math.max(...serviceList.map(s => s.uptime_seconds || 0)) : 0;
        document.getElementById('val-engine-uptime').innerText = formatUptime(maxUptime);
    }

    const tbody = document.getElementById('service-table-body');
    if (tbody) {
        tbody.innerHTML = '';
        for (const [name, s] of Object.entries(services)) {
            const tr = document.createElement('tr');
            const stateClass = s.state === 'running' ? 'text-success' : (s.state === 'failed' ? 'text-error' : 'text-warning');
            tr.innerHTML = `
                <td class="mono-font">${name}</td>
                <td><span class="${stateClass} font-bold">${s.state.toUpperCase()}</span></td>
                <td class="mono-font">${s.pid || '--'}</td>
                <td class="mono-font">${(s.cpu_percent || 0.0).toFixed(1)}%</td>
                <td class="mono-font">${(s.memory_mb || 0.0).toFixed(1)} MB</td>
                <td class="mono-font">${s.thread_count || 0}</td>
                <td class="mono-font">${s.restarts || 0}</td>
                <td class="mono-font">${formatUptime(s.uptime_seconds || 0)}</td>
            `;
            tbody.appendChild(tr);
        }
    }

    const perfCpuSys = document.getElementById('perf-cpu-sys');
    if (perfCpuSys) {
        perfCpuSys.innerText = `${(perf.system_cpu_percent || 0.0).toFixed(1)}%`;
        document.getElementById('perf-cpu-plat').innerText = `${(perf.platform_cpu_percent || 0.0).toFixed(1)}%`;
        document.getElementById('perf-ram-total').innerText = `${(perf.total_ram_percent || 0.0).toFixed(1)}%`;
        document.getElementById('perf-threads').innerText = perf.thread_count || '0';
        document.getElementById('perf-cpu-peak').innerText = `${(perf.peak_cpu_percent || 0.0).toFixed(1)}%`;
        document.getElementById('perf-ram-peak').innerText = `${(perf.peak_ram_percent || 0.0).toFixed(1)}%`;
    }

    let totalObserved = 0, totalCandidate = 0, totalFiltered = 0, totalSniper = 0, totalExecuted = 0;
    for (const sName of ["Strategy 1", "Strategy 2", "Strategy 3"]) {
        if (stats[sName]) {
            totalObserved += stats[sName].observed || 0;
            totalCandidate += stats[sName].candidate || 0;
            totalFiltered += stats[sName].filtered || 0;
            totalExecuted += stats[sName].executed || 0;
            totalSniper += (stats[sName].executed || 0) + (stats[sName].expired || 0);
        }
    }

    setFunnelStage('funnel-observed', totalObserved, '100%');
    setFunnelStage('funnel-candidate', totalCandidate, getPercentageStr(totalCandidate, totalObserved));
    setFunnelStage('funnel-filtered', totalFiltered, getPercentageStr(totalFiltered, totalCandidate));
    setFunnelStage('funnel-sniper', totalSniper, getPercentageStr(totalSniper, totalCandidate));
    setFunnelStage('funnel-executed', totalExecuted, getPercentageStr(totalExecuted, totalSniper));

    const valMarketRegime = document.getElementById('val-market-regime');
    if (valMarketRegime) {
        valMarketRegime.innerText = data.telemetry && data.telemetry.market_regime !== undefined ? (data.telemetry.market_regime === 1 ? 'BULLISH' : 'BEARISH') : 'NORMAL';
        document.getElementById('val-anchor-symbol').innerText = telemetry.symbol || '--';
        document.getElementById('val-last-signal').innerText = data.active_trade ? `${data.active_trade.type} signal locked` : 'SCANNING';
        document.getElementById('val-latest-action').innerText = data.active_trade ? 'SNIPER HUNT' : 'MONITORING';
        
        if (data.decisions && data.decisions.length > 0) {
            const lastDec = data.decisions[0];
            if (lastDec.status === 'REJECTED') {
                document.getElementById('val-last-rejection').innerText = lastDec.human_reason || '--';
            } else {
                document.getElementById('val-last-rejection').innerText = `Executed: ${lastDec.decision_action || 'ACCEPTED'}`;
            }
        }
    }

    const runtimeList = document.getElementById('runtime-checklist');
    if (runtimeList) {
        runtimeList.innerHTML = '';
        const checks = [
            { name: "Disk Writable State", status: runtimeVal.disk_space || 'UNKNOWN' },
            { name: "SQLite DB Readability", status: runtimeVal.sqlite_status || 'UNKNOWN' },
            { name: "Runtime Dir Writable", status: runtimeVal.runtime_folder || 'UNKNOWN' },
            { name: "Broker APIs Credentials", status: runtimeVal.broker_connectivity || 'UNKNOWN' },
            { name: "ZMQ Network Sockets", status: runtimeVal.zmq_health || 'UNKNOWN' },
            { name: "Flask Web Engine Port", status: runtimeVal.flask_health || 'UNKNOWN' },
            { name: "Microservice Tree Health", status: runtimeVal.service_health || 'UNKNOWN' }
        ];
        
        checks.forEach(c => {
            const div = document.createElement('div');
            div.className = 'overview-item';
            const statusClass = c.status === 'PASS' ? 'text-success' : (c.status === 'FAIL' ? 'text-error' : 'text-warning');
            div.innerHTML = `
                <span>${c.name}</span>
                <span class="${statusClass} font-bold">${c.status}</span>
            `;
            runtimeList.appendChild(div);
        });
    }

    const statsBody = document.getElementById('strategy-stats-body');
    if (statsBody) {
        statsBody.innerHTML = '';
        for (const [sName, s] of Object.entries(stats)) {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="highlight font-bold mono-font">${sName}</td>
                <td class="mono-font">${s.observed || 0}</td>
                <td class="mono-font">${s.candidate || 0}</td>
                <td class="mono-font text-warning">${s.filtered || 0}</td>
                <td class="mono-font">${s.rejected || 0}</td>
                <td class="mono-font">${s.expired || 0}</td>
                <td class="mono-font text-success font-bold">${s.executed || 0}</td>
                <td class="mono-font font-bold">${(s.win_rate || 0.0).toFixed(1)}%</td>
                <td class="mono-font font-bold text-success">+${(s.avg_premium_expansion || 0.0).toFixed(1)}%</td>
            `;
            statsBody.appendChild(tr);
        }
    }

    const startupList = document.getElementById('startup-checklist');
    if (startupList && startupVal.checks) {
        startupList.innerHTML = '';
        for (const [chkName, chk] of Object.entries(startupVal.checks)) {
            const div = document.createElement('div');
            const badgeClass = chk.status === 'PASS' ? 'badge-success' : (chk.status === 'FAIL' ? 'badge-danger' : 'badge-warning');
            div.className = 'startup-card';
            div.innerHTML = `
                <div class="chk-header">
                    <span class="chk-title">${chkName.toUpperCase().replace('_', ' ')}</span>
                    <span class="chk-badge ${badgeClass}">${chk.status}</span>
                </div>
                <div class="chk-details">${chk.details || 'Check Ok'}</div>
            `;
            startupList.appendChild(div);
        }
    }
}

// 3. RESEARCH MODE & SESSION SUMMARIES FETCHING
async function loadSummaries(mode) {
    try {
        const response = await fetch(`/api/summary?mode=${mode}`);
        const summaries = await response.json();
        
        const tbody = document.getElementById('summary-table-body');
        if (tbody) {
            tbody.innerHTML = '';
            const list = Array.isArray(summaries) ? [...summaries].reverse() : [];
            list.forEach(s => {
                const meta = s.summary_metadata || {};
                const trade = s.trade_metrics || {};
                const perf = s.system_performance || {};
                
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="mono-font font-bold">${meta.market_date || '--'}</td>
                    <td class="mono-font">${trade.total_trades || 0}</td>
                    <td class="mono-font font-bold">${(trade.win_rate || 0.0).toFixed(1)}%</td>
                    <td class="mono-font font-bold ${trade.net_pl >= 0 ? 'text-success' : 'text-error'}">₹${(trade.net_pl || 0.0).toFixed(2)}</td>
                    <td class="mono-font">${formatHoldTime(trade.avg_hold_time_seconds || 0)}</td>
                    <td class="mono-font text-success">+${(trade.avg_premium_expansion_pct || 0.0).toFixed(1)}%</td>
                    <td class="mono-font">${(perf.cpu_peak || 0.0).toFixed(1)}%</td>
                    <td class="mono-font">${(perf.ram_peak || 0.0).toFixed(1)}%</td>
                `;
                tbody.appendChild(tr);
            });
            
            if (list.length > 0) {
                const latest = list[0];
                const meta = latest.summary_metadata || {};
                const dq = latest.data_quality || {};
                const trade = latest.trade_metrics || {};
                
                document.getElementById('dq-ticks').innerText = dq.ticks_collected || '0';
                document.getElementById('dq-features').innerText = dq.indicators_written || '0';
                document.getElementById('dq-decisions').innerText = dq.decisions_logged || '0';
                document.getElementById('dq-trades').innerText = dq.trades_logged || '0';
                document.getElementById('dq-errors').innerText = dq.write_errors || '0';
                document.getElementById('dq-flush').innerText = dq.last_successful_flush || '--';
                document.getElementById('dq-backup').innerText = dq.last_successful_backup || '--';
                
                document.getElementById('r-win-rate').innerText = `${(trade.win_rate || 0.0).toFixed(1)}%`;
                document.getElementById('r-hold-time').innerText = formatHoldTime(trade.avg_hold_time_seconds || 0);
                document.getElementById('r-mfe').innerText = `+${(trade.avg_premium_expansion_pct || 0.0).toFixed(2)}%`;
                document.getElementById('r-mae').innerText = `-${(0.0).toFixed(2)}%`;
                document.getElementById('r-win-loss').innerText = `${trade.wins || 0}W / ${trade.losses || 0}L`;
                
                document.getElementById('meta-summary-ver').innerText = meta.summary_version || '--';
                document.getElementById('meta-engine-ver').innerText = meta.engine_version || '--';
                document.getElementById('meta-git-commit').innerText = meta.git_commit || '--';
                document.getElementById('meta-strat-hash').innerText = meta.strategy_hash || '--';
                document.getElementById('meta-generated-at').innerText = formatISOToTime(meta.generated_at);
                document.getElementById('meta-market-date').innerText = meta.market_date || '--';
            }
        }
    } catch(e) {
        console.log("Failed to load historical summaries.");
    }
}

// 4. ADAPTIVE DATASET HEALTH TELEMETRY
async function fetchDatasetHealth() {
    try {
        const res = await fetch('/api/dataset_health');
        const data = await res.json();
        
        const tbody = document.getElementById('dataset-table-body');
        if (tbody) {
            tbody.innerHTML = '';
            data.datasets.forEach(d => {
                const tr = document.createElement('tr');
                const statusClass = d.status === 'HEALTHY' ? 'text-success' : (d.status === 'CRITICAL' ? 'text-error' : 'text-warning');
                tr.innerHTML = `
                    <td class="mono-font">${d.name}</td>
                    <td class="mono-font">${d.size_mb > 10.0 ? `${d.size_mb.toFixed(1)} MB` : `${d.size_mb.toFixed(2)} MB`}</td>
                    <td class="mono-font">${d.rows}</td>
                    <td class="mono-font">${d.expected}</td>
                    <td class="mono-font"><span class="${statusClass} font-bold">${d.missing_pct.toFixed(1)}%</span></td>
                    <td><span class="${statusClass} font-bold">${d.status}</span></td>
                    <td class="mono-font">${d.last_write}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch(e) {
        console.log("Failed to load dataset health.");
    }
}

// 5. PHASE 2C DATA CERTIFICATION & TIMELINE
async function fetchAuditStatus() {
    try {
        const res = await fetch('/api/audit_status');
        const data = await res.json();
        
        const latest = data.latest || {};
        const manifest = data.manifest || [];
        
        // Populate scores & statuses
        const score = latest.confidence_score !== undefined ? latest.confidence_score : 100.0;
        document.getElementById('audit-score-badge').innerText = `${score.toFixed(2)}%`;
        
        const resGrade = latest.research_certification || 'PASS';
        const resBadge = document.getElementById('audit-status-badge');
        resBadge.innerText = resGrade;
        resBadge.className = 'chk-badge ' + (resGrade === 'PASS' ? 'badge-success' : (resGrade === 'FAILED' ? 'badge-danger' : 'badge-warning'));
        
        document.getElementById('audit-cert-res').innerText = resGrade;
        document.getElementById('audit-cert-res').className = resGrade === 'PASS' ? 'text-success' : 'text-error';
        
        const certs = latest.dataset_certification || {};
        document.getElementById('audit-cert-ticks').innerText = certs.raw_ticks || 'PASS';
        document.getElementById('audit-cert-ticks').className = certs.raw_ticks === 'PASS' ? 'text-success' : 'text-error';
        
        document.getElementById('audit-cert-indicators').innerText = certs.indicators || 'PASS';
        document.getElementById('audit-cert-indicators').className = certs.indicators === 'PASS' ? 'text-success' : 'text-error';
        
        document.getElementById('audit-cert-decisions').innerText = certs.decisions || 'PASS';
        document.getElementById('audit-cert-decisions').className = certs.decisions === 'PASS' ? 'text-success' : 'text-error';
        
        document.getElementById('audit-cert-trades').innerText = certs.trades || 'PASS';
        document.getElementById('audit-cert-trades').className = certs.trades === 'PASS' ? 'text-success' : 'text-error';
        
        document.getElementById('audit-meta-conf').innerText = latest.audit_config_hash || '--';
        
        // Populate historical manifest timeline registry
        const timelineBody = document.getElementById('audit-timeline-body');
        if (timelineBody) {
            timelineBody.innerHTML = '';
            manifest.slice(-10).reverse().forEach(entry => {
                const tr = document.createElement('tr');
                const gradeClass = entry.research_certification === 'PASS' ? 'text-success' : 'text-error';
                tr.innerHTML = `
                    <td class="mono-font">${entry.market_date}</td>
                    <td><span class="${gradeClass} font-bold">${entry.research_certification}</span></td>
                    <td class="mono-font font-bold">${entry.confidence_score.toFixed(2)}%</td>
                    <td class="mono-font">${entry.audit_config_hash}</td>
                `;
                timelineBody.appendChild(tr);
            });
            if (manifest.length === 0) {
                timelineBody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No audit history stored.</td></tr>';
            }
        }
    } catch(e) {
        console.log("Failed to load audit status.");
    }
}

// 6. CANVAS DOUBLE-LINE OVERLAY CHARTS
async function renderOverlayCharts() {
    try {
        const res = await fetch('/api/chart_data');
        const data = await res.json();
        
        if (!Array.isArray(data) || data.length === 0) return;
        
        // Chart 1: Price / VWAP / EMA Overlay
        const c1 = document.getElementById('chart-price-canvas');
        if (c1) {
            const ctx = c1.getContext('2d');
            const w = c1.clientWidth;
            const h = c1.clientHeight;
            c1.width = w;
            c1.height = h;
            
            ctx.fillStyle = "#000000";
            ctx.fillRect(0, 0, w, h);
            
            // Draw grid lines
            ctx.strokeStyle = "#111";
            ctx.lineWidth = 1;
            for (let i = 1; i < 4; i++) {
                const y = (h / 4) * i;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }
            
            // Extract series
            const closes = data.map(d => d.close);
            const vwaps_eng = data.map(d => d.vwap);
            const vwaps_ref = data.map(d => d.vwap_ref || d.vwap);
            const ema_eng = data.map(d => d.ema_9);
            const ema_ref = data.map(d => d.ema_9_ref || d.ema_9);
            
            const minP = Math.min(...closes, ...vwaps_eng, ...vwaps_ref, ...ema_eng, ...ema_ref) * 0.9995;
            const maxP = Math.max(...closes, ...vwaps_eng, ...vwaps_ref, ...ema_eng, ...ema_ref) * 1.0005;
            
            const scaleY = (val) => h - ((val - minP) / (maxP - minP)) * h;
            const scaleX = (idx) => (idx / (data.length - 1)) * w;
            
            // Plot close prices (Solid White)
            drawSeries(ctx, closes, scaleX, scaleY, "#ffffff", false, 1.5);
            
            // Plot VWAP Engine (Solid Blue) & Reference (Dashed Cyan)
            drawSeries(ctx, vwaps_eng, scaleX, scaleY, "#3b82f6", false, 1);
            drawSeries(ctx, vwaps_ref, scaleX, scaleY, "#06b6d4", true, 1);
            
            // Plot EMA Engine (Solid Green) & Reference (Dashed Lime)
            drawSeries(ctx, ema_eng, scaleX, scaleY, "#10b981", false, 1);
            drawSeries(ctx, ema_ref, scaleX, scaleY, "#84cc16", true, 1);
            
            // Write titles
            ctx.fillStyle = "#8e9bb4";
            ctx.font = "7px JetBrains Mono";
            ctx.fillText("NIFTY // PRICE (W) // VWAP (B) // EMA 9 (G)", 8, 12);
        }
        
        // Chart 2: VFI Engine vs Reference
        const c2 = document.getElementById('chart-vfi-canvas');
        if (c2) {
            const ctx = c2.getContext('2d');
            const w = c2.clientWidth;
            const h = c2.clientHeight;
            c2.width = w;
            c2.height = h;
            
            ctx.fillStyle = "#000000";
            ctx.fillRect(0, 0, w, h);
            
            // Draw baseline (VFI = 0.0)
            ctx.strokeStyle = "#222";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(0, h/2);
            ctx.lineTo(w, h/2);
            ctx.stroke();
            
            const vfis_eng = data.map(d => d.vfi_ema || 0.0);
            const vfis_ref = data.map(d => d.vfi_ref || 0.0);
            
            const minV = Math.min(-10.0, ...vfis_eng, ...vfis_ref) * 1.1;
            const maxV = Math.max(10.0, ...vfis_eng, ...vfis_ref) * 1.1;
            
            const scaleY = (val) => h - ((val - minV) / (maxV - minV)) * h;
            const scaleX = (idx) => (idx / (data.length - 1)) * w;
            
            // Plot VFI Engine (Solid Gold) & Reference (Dashed Yellow)
            drawSeries(ctx, vfis_eng, scaleX, scaleY, "#eab308", false, 1.5);
            drawSeries(ctx, vfis_ref, scaleX, scaleY, "#fbbf24", true, 1);
            
            ctx.fillStyle = "#8e9bb4";
            ctx.font = "7px JetBrains Mono";
            ctx.fillText("VFI OVERLAY // ENG (GOLD) // REF (YELLOW)", 8, 12);
        }
    } catch(e) {
        console.log("Failed to draw overlay charts: " + e);
    }
}

function drawSeries(ctx, arr, scaleX, scaleY, color, isDashed, thickness) {
    ctx.strokeStyle = color;
    ctx.lineWidth = thickness;
    if (isDashed) ctx.setLineDash([3, 3]);
    else ctx.setLineDash([]);
    
    ctx.beginPath();
    arr.forEach((val, idx) => {
        const x = scaleX(idx);
        const y = scaleY(val);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
}

// 7. STRUCTURED LOG EXPLORER
async function loadLogs() {
    const service = document.getElementById('log-service-select').value;
    const search = document.getElementById('log-search-input').value;
    const consoleDiv = document.getElementById('log-console');
    
    try {
        const res = await fetch(`/api/logs?service=${service}&severity=${logSeverity}&search=${encodeURIComponent(search)}`);
        const data = await res.json();
        
        if (data.lines && data.lines.length > 0) {
            consoleDiv.innerHTML = '';
            data.lines.forEach(l => {
                const span = document.createElement('span');
                span.className = 'log-line ' + getLogLevelClass(l.level);
                span.innerText = l.text + '\n';
                consoleDiv.appendChild(span);
            });
        } else {
            consoleDiv.innerText = "No matching logs found.";
        }
        consoleDiv.scrollTop = consoleDiv.scrollHeight;
    } catch (e) {
        consoleDiv.innerText = "Error loading logs from Flask service.";
    }
}

function setLogSeverity(btn) {
    document.querySelectorAll('.severity-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    logSeverity = btn.getAttribute('data-severity');
    loadLogs();
}

// UTILITY HELPERS
function formatUptime(secs) {
    if (secs < 60) return `${Math.round(secs)}s`;
    if (secs < 3600) return `${Math.floor(secs/60)}m ${Math.round(secs%60)}s`;
    return `${Math.floor(secs/3600)}h ${Math.floor((secs%3600)/60)}m`;
}

function formatHoldTime(secs) {
    if (secs === 0) return '0m';
    return `${Math.round(secs / 60)}m`;
}

function formatISOToTime(isoStr) {
    if (!isoStr) return '--:--:--';
    try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString();
    } catch(e) {
        return '--:--:--';
    }
}

function getPercentageStr(subset, total) {
    if (total === 0) return '0.0%';
    return `${((subset / total) * 100).toFixed(1)}%`;
}

function setFunnelStage(id, val, pct) {
    const el = document.getElementById(id);
    if (el) {
        el.querySelector('.stage-val').innerText = val;
        el.querySelector('.stage-meta').innerText = pct;
    }
}

function getLifecycleColorClass(state) {
    if (state === 'TRADING_LIVE') return 'text-success';
    if (state === 'TRADING_IDLE') return 'text-warning';
    return 'text-muted';
}

function getLogLevelClass(level) {
    if (level === 'ERROR') return 'text-error font-bold';
    if (level === 'WARNING') return 'text-warning';
    if (level === 'CRITICAL') return 'text-critical font-bold';
    if (level === 'SUCCESS') return 'text-success';
    return '';
}
