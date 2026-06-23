// Initialization
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    fetchTelemetry();
    setInterval(fetchTelemetry, 3000);
});

let previousActiveTrade = null;
let previousHistoryCount = 0;

// THEME MANAGEMENT
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const target = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', target);
    localStorage.setItem('theme', target);
    updateThemeIcon(target);
}

function updateThemeIcon(theme) {
    const icon = document.getElementById('theme-icon');
    if(icon) {
        icon.setAttribute('name', theme === 'dark' ? 'sunny-outline' : 'moon-outline');
    }
}

// SETTINGS MANAGEMENT
async function openSettings() {
    document.getElementById('settings-modal').style.display = 'flex';
    document.getElementById('settings-msg').innerText = 'Loading...';
    document.getElementById('settings-msg').style.color = 'var(--text-secondary)';
    
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        document.getElementById('inp-api-key').value = data.ANGEL_API_KEY || '';
        document.getElementById('inp-client-id').value = data.ANGEL_CLIENT_ID || '';
        document.getElementById('inp-password').value = data.ANGEL_PASSWORD || '';
        document.getElementById('inp-totp').value = data.ANGEL_TOTP_SECRET || '';
        document.getElementById('settings-msg').innerText = '';
    } catch(e) {
        document.getElementById('settings-msg').innerText = 'Failed to load settings.';
        document.getElementById('settings-msg').style.color = 'var(--danger)';
    }
}

function closeSettings() {
    document.getElementById('settings-modal').style.display = 'none';
}

async function saveSettings() {
    const btn = document.getElementById('btn-save-settings');
    const msg = document.getElementById('settings-msg');
    btn.disabled = true;
    msg.innerText = 'Saving...';
    msg.style.color = 'var(--text-secondary)';
    
    const payload = {
        "ANGEL_API_KEY": document.getElementById('inp-api-key').value,
        "ANGEL_CLIENT_ID": document.getElementById('inp-client-id').value,
        "ANGEL_PASSWORD": document.getElementById('inp-password').value,
        "ANGEL_TOTP_SECRET": document.getElementById('inp-totp').value
    };
    
    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if(data.success) {
            msg.innerText = 'Saved! Restart algo to apply.';
            msg.style.color = 'var(--success)';
            setTimeout(closeSettings, 2000);
        }
    } catch(e) {
        msg.innerText = 'Failed to save.';
        msg.style.color = 'var(--danger)';
    } finally {
        btn.disabled = false;
    }
}

// AUDIO
function playPing() {
    try {
        const context = new (window.AudioContext || window.webkitAudioContext)();
        const osc = context.createOscillator();
        const gain = context.createGain();
        osc.connect(gain);
        gain.connect(context.destination);
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, context.currentTime); // A5
        osc.frequency.exponentialRampToValueAtTime(440, context.currentTime + 0.1);
        gain.gain.setValueAtTime(1, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, context.currentTime + 0.5);
        osc.start(context.currentTime);
        osc.stop(context.currentTime + 0.5);
    } catch(e) {
        console.log("Audio not supported or blocked");
    }
}

// TELEMETRY
async function fetchTelemetry() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        updateUI(data);
    } catch (e) {
        document.getElementById('status-dot').className = 'dot dot-offline';
        document.getElementById('status-text').innerText = 'OFFLINE';
    }
}

function updateUI(data) {
    if (data.status === 'running') {
        document.getElementById('status-dot').className = 'dot dot-online';
        document.getElementById('status-text').innerText = 'ONLINE';
        document.getElementById('btn-start').style.display = 'none';
        document.getElementById('btn-stop').style.display = 'flex';
    } else {
        document.getElementById('status-dot').className = 'dot dot-offline';
        document.getElementById('status-text').innerText = 'STOPPED';
        document.getElementById('btn-start').style.display = 'flex';
        document.getElementById('btn-stop').style.display = 'none';
    }

    if (data.telemetry) {
        document.getElementById('val-symbol').innerText = data.telemetry.symbol || '--';
        let ltpElem = document.getElementById('val-ltp');
        ltpElem.innerText = data.telemetry.ltp ? data.telemetry.ltp.toFixed(2) : '--';
        
        if (data.telemetry.ltp_time) {
            document.getElementById('ltp-time').innerText = `(${data.telemetry.ltp_time})`;
        }
        
        if (data.telemetry.ltp && data.telemetry.vwap) {
            if (data.telemetry.ltp > data.telemetry.vwap) {
                ltpElem.style.color = 'var(--success)';
            } else if (data.telemetry.ltp < data.telemetry.vwap) {
                ltpElem.style.color = 'var(--danger)';
            } else {
                ltpElem.style.color = 'var(--text-primary)';
            }
        }
        
        document.getElementById('val-vwap').innerText = data.telemetry.vwap ? data.telemetry.vwap.toFixed(2) : '--';
        
        const vfi = data.telemetry.vfi !== undefined ? data.telemetry.vfi.toFixed(2) : '--';
        const vfiEma = data.telemetry.vfi_ema !== undefined ? data.telemetry.vfi_ema.toFixed(2) : '--';
        const vfiEl = document.getElementById('val-vfi');
        vfiEl.innerText = `${vfi} / ${vfiEma}`;
        
        if (data.telemetry.vfi > 0) {
            vfiEl.style.color = 'var(--success)';
        } else if (data.telemetry.vfi < 0) {
            vfiEl.style.color = 'var(--danger)';
        } else {
            vfiEl.style.color = 'var(--text-primary)';
        }
        let vol = data.telemetry.volume;
        document.getElementById('val-volume').innerText = vol ? (vol >= 1000000 ? (vol / 1000000).toFixed(2) + 'M' : (vol / 1000).toFixed(1) + 'K') : '--';
        
        if (data.telemetry.volume_time) {
            document.getElementById('volume-time').innerText = `(${data.telemetry.volume_time})`;
        }
    }

    if (data.active_trade) {
        document.getElementById('active-trade-panel').style.display = 'block';
        document.getElementById('trade-symbol').innerText = data.active_trade.symbol;
        document.getElementById('trade-entry').innerText = data.active_trade.entry_price.toFixed(2);
        document.getElementById('trade-target').innerText = data.active_trade.target_price.toFixed(2);
        document.getElementById('trade-ltp').innerText = data.active_trade.current_ltp ? data.active_trade.current_ltp.toFixed(2) : '--';
        
        // Update Order Flow Delta
        if (data.order_flow) {
            let buy = data.order_flow.buy_vol || 0;
            let sell = data.order_flow.sell_vol || 0;
            let net = data.order_flow.delta || 0;
            
            document.getElementById('trade-buy-vol').innerText = buy;
            document.getElementById('trade-sell-vol').innerText = sell;
            
            let deltaEl = document.getElementById('trade-net-delta');
            deltaEl.innerText = net;
            if (net > 0) deltaEl.style.color = 'var(--success)';
            else if (net < 0) deltaEl.style.color = 'var(--danger)';
            else deltaEl.style.color = 'var(--text-primary)';
            
            let total = buy + sell;
            if (total > 0) {
                let buyPct = (buy / total) * 100;
                let sellPct = (sell / total) * 100;
                document.getElementById('delta-buy-bar').style.width = buyPct + '%';
                document.getElementById('delta-sell-bar').style.width = sellPct + '%';
            } else {
                document.getElementById('delta-buy-bar').style.width = '50%';
                document.getElementById('delta-sell-bar').style.width = '50%';
            }
        }
    } else {
        document.getElementById('active-trade-panel').style.display = 'none';
    }
    
    // Ping Check
    if (data.active_trade && !previousActiveTrade) playPing();
    previousActiveTrade = data.active_trade;
    
    // History
    const tbody = document.getElementById('history-table-body');
    const noTrades = document.getElementById('no-trades');
    
    if (data.history && data.history.length > 0) {
        noTrades.style.display = 'none';
        
        let totalRealized = 0;
        let capitalArr = [];
        data.history.forEach(t => {
            totalRealized += t.net_pl;
            if (t.capital_used) capitalArr.push(t.capital_used);
        });
        
        let avgCap = 0;
        let medCap = 0;
        if (capitalArr.length > 0) {
            avgCap = capitalArr.reduce((a, b) => a + b, 0) / capitalArr.length;
            capitalArr.sort((a, b) => a - b);
            const mid = Math.floor(capitalArr.length / 2);
            medCap = capitalArr.length % 2 !== 0 ? capitalArr[mid] : (capitalArr[mid - 1] + capitalArr[mid]) / 2;
        }
        
        let totalRoi = 0;
        if (avgCap > 0) {
            totalRoi = (totalRealized / avgCap) * 100;
        }
        
        document.getElementById('metric-realized').innerText = `₹${totalRealized.toFixed(2)}`;
        document.getElementById('metric-realized').className = 'metric-val ' + (totalRealized >= 0 ? "profit-text" : "loss-text");
        
        document.getElementById('metric-roi').innerText = `${totalRoi.toFixed(2)}%`;
        document.getElementById('metric-roi').className = 'metric-val ' + (totalRoi >= 0 ? "profit-text" : "loss-text");
        
        document.getElementById('metric-avg-cap').innerText = `₹${avgCap.toFixed(2)}`;
        document.getElementById('metric-med-cap').innerText = `₹${medCap.toFixed(2)}`;
        
        if (data.history.length > previousHistoryCount) {
            if (previousHistoryCount > 0) playPing();
            previousHistoryCount = data.history.length;
        }
        
        tbody.innerHTML = '';
        const reversedHistory = [...data.history].reverse();
        reversedHistory.forEach(trade => {
            const tr = document.createElement('tr');
            const rowClass = trade.result === "WIN" ? "profit-text" : (trade.result.includes("LOSS") ? "loss-text" : "neutral");
            const slipJSON = encodeURIComponent(JSON.stringify(trade.slippage || {}));
            
            
            let strategyBadge = '';
            if (trade.strategy) {
                if (trade.strategy.includes('REJECTION') || trade.strategy.includes('SUPPORT')) {
                    strategyBadge = `<span style="background:var(--card-bg); padding:2px 6px; border-radius:4px; font-size:0.8rem; border:1px solid var(--border);">[R] Mean Rev</span>`;
                } else {
                    strategyBadge = `<span style="background:var(--card-bg); padding:2px 6px; border-radius:4px; font-size:0.8rem; border:1px solid var(--border);">[B] Breakout</span>`;
                }
            } else {
                strategyBadge = `<span style="color:var(--text-secondary)">--</span>`;
            }
            
            tr.innerHTML = `
                <td>${trade.id}</td>
                <td>${trade.date || '--'}</td>
                <td>${trade.duration || '--'}</td>
                <td>${strategyBadge}</td>
                <td style="font-weight:600;" class="${trade.type === 'CALL' ? 'profit-text' : 'loss-text'}">${trade.symbol}</td>
                <td>${trade.entry_price.toFixed(2)}</td>
                <td>${trade.exit_price.toFixed(2)}</td>
                <td class="${rowClass}">${trade.opt_pct ? trade.opt_pct.toFixed(2) + '%' : '--'}</td>
                <td>${trade.idx_pts !== undefined ? trade.idx_pts.toFixed(2) : '--'}</td>
                <td class="${rowClass}"><b>₹${trade.net_pl.toFixed(2)}</b></td>
                <td class="${rowClass}">${trade.result}</td>
                <td>
                    <a href="${trade.chart}" target="_blank" style="color:var(--accent); margin-right:10px;"><ion-icon name="image-outline"></ion-icon></a>
                    <a href="javascript:void(0)" onclick="showSpread('${slipJSON}')" style="color:var(--text-secondary);"><ion-icon name="list-outline"></ion-icon></a>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } else {
        noTrades.style.display = 'block';
        tbody.innerHTML = '';
    }
}

async function controlAlgo(action) {
    const res = await fetch(`/api/control?action=${action}`);
    const data = await res.json();
    if (data.success) fetchTelemetry();
}

function showSpread(slipJSONStr) {
    try {
        const slipData = JSON.parse(decodeURIComponent(slipJSONStr));
        const formattedData = JSON.stringify(slipData, null, 2);
        document.getElementById('spread-data').innerText = formattedData;
        document.getElementById('spread-modal').style.display = 'flex';
    } catch(e) {
        alert("No slippage data available.");
    }
}

// Progress Bar Animation
setInterval(() => {
    const bar = document.getElementById('volume-bar');
    if (!bar) return;
    const now = new Date();
    const exactSeconds = now.getSeconds() + (now.getMilliseconds() / 1000);
    const pct = (exactSeconds / 60) * 100;
    
    if (exactSeconds < 0.1 || pct < parseFloat(bar.style.width || "0")) {
        bar.style.transition = 'none';
        bar.style.width = '0%';
    } else {
        bar.style.transition = 'width 0.1s linear';
        bar.style.width = pct + '%';
    }
}, 100);
