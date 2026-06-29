async function fetchHealth() {
    try {
        const res = await fetch('/api/intelligence/health');
        if (!res.ok) throw new Error('API Error');
        const data = await res.json();
        if (data.error) return;

        // Health Score
        const score = data.health_score || 0;
        document.getElementById('health-score').textContent = score;
        const box = document.getElementById('health-score-box');
        if (score >= 90) box.style.borderColor = 'var(--success)';
        else if (score >= 70) box.style.borderColor = 'var(--warning)';
        else box.style.borderColor = 'var(--danger)';

        // Feed Service
        const feed = data.feed_service || {};
        document.getElementById('hs-feed-status').innerHTML = `<span class="dot ${feed.status === 'Healthy' ? 'dot-green' : 'dot-red'}"></span>${feed.status || 'Offline'}`;
        document.getElementById('hs-feed-ticks').textContent = `${(feed.ticks_per_sec_last_minute || 0).toFixed(1)} ticks/s`;

        // Brain Service
        const brain = data.brain_service || {};
        document.getElementById('hs-brain-status').innerHTML = `<span class="dot ${brain.status === 'Healthy' ? 'dot-green' : 'dot-red'}"></span>${brain.status || 'Offline'}`;
        document.getElementById('hs-brain-uptime').textContent = formatUptime(brain.uptime_seconds);

        // Research Collector
        const research = data.research_collector || {};
        document.getElementById('hs-research-status').innerHTML = `<span class="dot ${research.status === 'Healthy' ? 'dot-green' : 'dot-red'}"></span>${research.status || 'Offline'}`;
        document.getElementById('hs-research-mem').textContent = `${(research.memory_mb || 0).toFixed(1)} MB`;

        // Canonical
        const canonical = data.canonical_storage || {};
        document.getElementById('hs-canonical-status').innerHTML = `<span class="dot ${canonical.status === 'Healthy' ? 'dot-green' : (canonical.status === 'Warning' ? 'dot-yellow' : 'dot-red')}"></span>${canonical.status || 'Warning'}`;
        document.getElementById('hs-canonical-files').textContent = `${canonical.total_files || 0} files`;

        // System
        const sys = data.system || {};
        document.getElementById('hs-cpu').textContent = `CPU ${sys.cpu_usage_percent || 0}%`;
        document.getElementById('hs-ram').textContent = `RAM ${sys.ram_usage_percent || 0}% | Disk ${sys.disk_free_gb || 0}GB`;

        // Process Grid
        const grid = document.getElementById('proc-grid');
        grid.innerHTML = '';
        const procs = [
            { name: 'Feed Service', data: feed },
            { name: 'Brain Service', data: brain },
            { name: 'Research Collector', data: research }
        ];

        procs.forEach(p => {
            if (!p.data.pid) return;
            const healthClass = p.data.status === 'Healthy' ? 'healthy' : (p.data.status === 'Warning' ? 'warning' : 'critical');
            grid.innerHTML += `
                <div class="proc-card ${healthClass}">
                    <div class="proc-name">${p.name} <span class="proc-pid">PID: ${p.data.pid}</span></div>
                    <div class="proc-stats">
                        <span class="proc-stat">CPU: ${(p.data.cpu_percent || 0).toFixed(1)}%</span>
                        <span class="proc-stat">MEM: ${(p.data.memory_mb || 0).toFixed(1)}MB</span>
                        <span class="proc-stat">UP: ${formatUptime(p.data.uptime_seconds)}</span>
                    </div>
                </div>
            `;
        });
        if (grid.innerHTML === '') grid.innerHTML = '<div class="empty-state">No process data available.</div>';

    } catch (err) {
        console.error('Fetch Health Error:', err);
    }
}

async function fetchLiveState() {
    try {
        const res = await fetch('/api/intelligence/live_state');
        if (!res.ok) throw new Error('API Error');
        const data = await res.json();
        
        const t = data.telemetry || {};
        
        document.getElementById('li-ltp').textContent = (t.ltp || 0).toFixed(2);
        document.getElementById('li-symbol').textContent = t.symbol || '--';
        document.getElementById('li-vwap').textContent = (t.vwap || 0).toFixed(2);
        
        const ema = t.ema || 0;
        const vwap = t.vwap || 0;
        document.getElementById('li-ema').textContent = ema.toFixed(2);
        
        let diff = ema - vwap;
        let diffStr = (diff >= 0 ? '+' : '') + diff.toFixed(2);
        document.getElementById('li-ema-vs-vwap').innerHTML = `<span style="color: ${diff >= 0 ? 'var(--success)' : 'var(--danger)'}">${diffStr}</span> vs VWAP`;

        document.getElementById('li-vfi').textContent = `${(t.vfi || 0).toFixed(1)} / ${(t.vfi_ema || 0).toFixed(1)}`;
        document.getElementById('li-vfi-bias').textContent = `Volume Bias: ${(t.vfi || 0) >= 0 ? 'BULLISH' : 'BEARISH'}`;
        document.getElementById('li-vfi-bias').style.color = (t.vfi || 0) >= 0 ? 'var(--success)' : 'var(--danger)';

        // Regime
        const regimeNames = ['Normal', 'Trending Expansion', 'Range Compression'];
        const colors = ['var(--text)', 'var(--success)', 'var(--warning)'];
        const rIdx = data.market_regime !== null ? data.market_regime : 0;
        
        document.getElementById('regime-label').textContent = regimeNames[rIdx];
        document.getElementById('regime-label').style.color = colors[rIdx];
        
        if (rIdx === 0) document.getElementById('regime-desc').textContent = "Price hovering around VWAP";
        if (rIdx === 1) document.getElementById('regime-desc').textContent = "Price clearly trending away from VWAP";
        if (rIdx === 2) document.getElementById('regime-desc').textContent = "Price highly compressed, low volatility";

        document.getElementById('li-atr').textContent = data.atr ? data.atr.toFixed(2) : '--';
        document.getElementById('li-atr-exp').textContent = data.atr_expansion ? data.atr_expansion.toFixed(2) : '--';
        document.getElementById('li-compression').innerHTML = data.compression ? '<span class="badge badge-yellow">YES</span>' : '<span class="badge badge-gray">NO</span>';
        document.getElementById('li-volume').textContent = t.volume ? t.volume.toLocaleString() : '--';

    } catch (err) {
        console.error('Fetch Live State Error:', err);
    }
}

async function fetchDecisions() {
    try {
        const res = await fetch('/api/intelligence/decisions');
        if (!res.ok) throw new Error('API Error');
        const data = await res.json();
        
        // Stats
        document.getElementById('ds-total').textContent = data.total_today || 0;
        document.getElementById('ds-accepted').textContent = data.accepted_today || 0;
        document.getElementById('ds-rejected').textContent = data.rejected_today || 0;

        // Reason Bars
        const reasonBars = document.getElementById('reason-bars');
        let barHtml = `<div style="font-size: 11px; color: var(--text3); font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 4px;">Top Rejection Reasons</div>`;
        const reasons = data.rejection_reasons || {};
        const maxR = Math.max(...Object.values(reasons), 1);
        
        if (Object.keys(reasons).length === 0) {
            barHtml += `<div style="font-size: 11px; color: var(--text2); padding-top: 10px;">No rejections yet.</div>`;
        } else {
            for (const [r, count] of Object.entries(reasons)) {
                const pct = (count / maxR) * 100;
                barHtml += `
                <div class="reason-bar-item">
                    <div class="reason-bar-label"><span>${r}</span> <strong>${count}</strong></div>
                    <div class="reason-bar-track">
                        <div class="reason-bar-fill" style="width: ${pct}%"></div>
                    </div>
                </div>
                `;
            }
        }
        reasonBars.innerHTML = barHtml;

        // Feed
        const feed = document.getElementById('decision-feed');
        if (data.recent && data.recent.length > 0) {
            feed.innerHTML = data.recent.map(d => {
                const isAcc = d.status === 'ACCEPTED';
                const action = d.decision_action === 'CALL' ? '<span style="color:var(--success)">CALL</span>' : 
                              (d.decision_action === 'PUT' ? '<span style="color:var(--danger)">PUT</span>' : 'NONE');
                
                const time = d.timestamp ? d.timestamp.split(' ')[1].substring(0,8) : '--:--:--';
                
                return `
                <div class="decision-item ${isAcc ? 'accepted' : 'rejected'}">
                    <div class="decision-time">${time}</div>
                    <div class="decision-action">${action}</div>
                    <div class="decision-reason">${isAcc ? '<strong>Signal fired and executed</strong>' : d.human_reason}</div>
                    ${isAcc ? '<span class="badge badge-green">EXEC</span>' : '<span class="badge badge-gray">REJ</span>'}
                </div>
                `;
            }).join('');
        } else {
            feed.innerHTML = '<div class="empty-state">No recent decisions in memory.</div>';
        }

    } catch (err) {
        console.error('Fetch Decisions Error:', err);
    }
}

async function fetchOrderFlow() {
    try {
        const res = await fetch('/api/intelligence/order_flow');
        if (!res.ok) throw new Error('API Error');
        const data = await res.json();
        
        const body = document.getElementById('order-flow-body');
        
        if (!data.has_active || !data.active_trade) {
            body.innerHTML = `
                <div class="empty-state" style="padding: 30px;">
                    <ion-icon name="eye-off-outline"></ion-icon>
                    No active setup or trade.<br>Sniper mode is idle.
                </div>
            `;
            return;
        }

        const t = data.active_trade;
        const s = t.slippage && t.slippage.length > 0 ? t.slippage[t.slippage.length-1] : null;
        
        let ofHtml = `
            <div class="metric-row" style="padding: 10px 20px;">
                <span class="metric-key">Active Track</span>
                <span class="metric-val" style="color: ${t.type === 'CALL' ? 'var(--success)' : 'var(--danger)'}">
                    ${t.symbol || '--'} ${t.type}
                </span>
            </div>
            <div class="metric-row" style="padding: 10px 20px;">
                <span class="metric-key">Strategy</span>
                <span class="metric-val">${t.strategy || 'UNKNOWN'}</span>
            </div>
        `;

        if (s) {
            const buyQ = s.total_buy_qty || 0;
            const sellQ = s.total_sell_qty || 0;
            const total = buyQ + sellQ;
            const bPct = total > 0 ? (buyQ/total)*100 : 50;
            const sPct = total > 0 ? (sellQ/total)*100 : 50;
            const delta = buyQ - sellQ;
            
            ofHtml += `
            <div class="flow-gauge">
                <div class="flow-row">
                    <div class="flow-label">Buy Vol</div>
                    <div class="flow-bar-track">
                        <div class="flow-bar-fill-buy" style="width: ${bPct}%"></div>
                    </div>
                    <div class="flow-val" style="color: var(--success);">${buyQ.toLocaleString()}</div>
                </div>
                <div class="flow-row">
                    <div class="flow-label">Sell Vol</div>
                    <div class="flow-bar-track">
                        <div class="flow-bar-fill-sell" style="width: ${sPct}%"></div>
                    </div>
                    <div class="flow-val" style="color: var(--danger);">${sellQ.toLocaleString()}</div>
                </div>
                <div class="delta-display">
                    <div class="delta-val" style="color: ${delta > 0 ? 'var(--success)' : 'var(--danger)'}">
                        ${delta > 0 ? '+' : ''}${delta.toLocaleString()}
                    </div>
                    <div class="delta-label">Order Flow Delta</div>
                </div>
            </div>
            `;
        } else {
            ofHtml += `<div class="empty-state" style="padding: 20px;">No depth data available yet.</div>`;
        }
        
        body.innerHTML = ofHtml;

    } catch (err) {
        console.error('Fetch Order Flow Error:', err);
    }
}

async function fetchTrades() {
    try {
        const res = await fetch('/api/intelligence/trades');
        if (!res.ok) throw new Error('API Error');
        const data = await res.json();
        
        document.getElementById('total-pl').textContent = `₹${data.total_pl.toFixed(2)}`;
        document.getElementById('total-pl').style.color = data.total_pl >= 0 ? 'var(--success)' : 'var(--danger)';
        document.getElementById('trade-wins').textContent = `${data.wins}W`;
        document.getElementById('trade-losses').textContent = `${data.losses}L`;

        const tbody = document.getElementById('trade-tbody');
        if (data.history && data.history.length > 0) {
            tbody.innerHTML = data.history.map(t => {
                const date = t.entry_time ? t.entry_time.split('T')[0] : '--';
                const time = t.entry_time ? t.entry_time.split('T')[1].substring(0,8) : '--';
                
                const en = parseFloat(t.entry_price || 0);
                const ex = parseFloat(t.exit_price || 0);
                const pct = en > 0 ? ((ex - en)/en * 100).toFixed(1) : '0.0';
                
                let resClass = t.result === 'WIN' ? 'badge-green' : 'badge-red';
                
                return `
                <tr>
                    <td>${date} ${time}</td>
                    <td><strong>${t.symbol}</strong></td>
                    <td><span class="badge badge-purple">${t.strategy || 'NA'}</span></td>
                    <td>₹${en.toFixed(1)}</td>
                    <td>₹${ex.toFixed(1)}</td>
                    <td>${t.hold_duration_seconds || 0}s</td>
                    <td style="color: ${pct >= 0 ? 'var(--success)' : 'var(--danger)'}">${pct > 0 ? '+' : ''}${pct}%</td>
                    <td style="color: ${t.net_pl >= 0 ? 'var(--success)' : 'var(--danger)'}">₹${parseFloat(t.net_pl).toFixed(1)}</td>
                    <td><span class="badge ${resClass}">${t.result}</span></td>
                    <td style="color: var(--text2); font-family: 'Outfit', sans-serif;">${t.exit_reason || '--'}</td>
                </tr>
                `;
            }).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color: var(--text3); padding: 30px;">No trades executed yet.</td></tr>';
        }

    } catch (err) {
        console.error('Fetch Trades Error:', err);
    }
}

function formatUptime(seconds) {
    if (!seconds) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function updateTime() {
    const now = new Date();
    document.getElementById('last-refresh').textContent = `Last sync: ${now.toLocaleTimeString()}`;
}

async function loadAll() {
    await Promise.all([
        fetchHealth(),
        fetchLiveState(),
        fetchDecisions(),
        fetchOrderFlow(),
        fetchTrades()
    ]);
    updateTime();
}

// Init
setInterval(loadAll, 2000);
loadAll();
