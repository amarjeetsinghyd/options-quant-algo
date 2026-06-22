// Poll the backend every 3 seconds
setInterval(fetchTelemetry, 3000);

let previousActiveTrade = null;
let previousHistoryCount = 0;

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
        document.getElementById('btn-stop').style.display = 'block';
    } else {
        document.getElementById('status-dot').className = 'dot dot-offline';
        document.getElementById('status-text').innerText = 'STOPPED';
        document.getElementById('btn-start').style.display = 'block';
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
                ltpElem.style.color = 'var(--text-main)';
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
            vfiEl.style.color = 'var(--text-main)';
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
    } else {
        document.getElementById('active-trade-panel').style.display = 'none';
    }
    
    // Check for Trade Entry (Ping)
    if (data.active_trade && !previousActiveTrade) {
        playPing();
    }
    previousActiveTrade = data.active_trade;
    
    // Update History
    const tbody = document.getElementById('history-table-body');
    const noTrades = document.getElementById('no-trades');
    
    if (data.history && data.history.length > 0) {
        noTrades.style.display = 'none';
        
        // Calculate Cumulative Metrics
        let totalRealized = 0;
        let capitalArr = [];
        data.history.forEach(t => {
            totalRealized += t.net_pl;
            if (t.capital_used) capitalArr.push(t.capital_used);
        });
        
        const totalNet = totalRealized - (data.history.length * 50);
        let avgCap = 0;
        let medCap = 0;
        if (capitalArr.length > 0) {
            avgCap = capitalArr.reduce((a, b) => a + b, 0) / capitalArr.length;
            capitalArr.sort((a, b) => a - b);
            const mid = Math.floor(capitalArr.length / 2);
            medCap = capitalArr.length % 2 !== 0 ? capitalArr[mid] : (capitalArr[mid - 1] + capitalArr[mid]) / 2;
        }
        
        document.getElementById('metric-realized').innerText = `₹${totalRealized.toFixed(2)}`;
        document.getElementById('metric-realized').className = totalRealized >= 0 ? "profit-text" : "loss-text";
        
        document.getElementById('metric-net').innerText = `₹${totalNet.toFixed(2)}`;
        document.getElementById('metric-net').className = totalNet >= 0 ? "profit-text" : "loss-text";
        
        document.getElementById('metric-avg-cap').innerText = `₹${avgCap.toFixed(2)}`;
        document.getElementById('metric-med-cap').innerText = `₹${medCap.toFixed(2)}`;
        
        // Check for Trade Exit (Ping)
        if (data.history.length > previousHistoryCount) {
            if (previousHistoryCount > 0) playPing();
            previousHistoryCount = data.history.length;
        }
        
        tbody.innerHTML = '';
        
        // Reverse array to show newest on top
        const reversedHistory = [...data.history].reverse();
        reversedHistory.forEach(trade => {
            const tr = document.createElement('tr');
            const rowClass = trade.result === "WIN" ? "profit-text" : "loss-text";
            // Encode slippage data securely for the onclick handler
            const slipJSON = encodeURIComponent(JSON.stringify(trade.slippage || {}));
            
            tr.innerHTML = `
                <td>${trade.id}</td>
                <td>${trade.date || '--'}</td>
                <td>${trade.duration || '--'}</td>
                <td class="${trade.type === 'CALL' ? 'bull-text' : 'bear-text'}">${trade.symbol}</td>
                <td>${trade.entry_price.toFixed(2)}</td>
                <td>${trade.exit_price.toFixed(2)}</td>
                <td class="${rowClass}">${trade.opt_pct ? trade.opt_pct.toFixed(2) + '%' : '--'}</td>
                <td>${trade.idx_pts !== undefined ? trade.idx_pts.toFixed(2) : '--'}</td>
                <td class="${rowClass}">${trade.net_pl.toFixed(2)}</td>
                <td class="${rowClass}">${trade.result}</td>
                <td>
                    <a href="${trade.chart}" target="_blank" style="color:#00ff88; text-decoration:underline; margin-right:10px;">Chart</a>
                    <a href="javascript:void(0)" onclick="showSpread('${slipJSON}')" style="color:#a5b4fc; text-decoration:underline;">Spread</a>
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
    if (data.success) {
        fetchTelemetry(); // Force immediate update
    }
}

// Initial fetch
fetchTelemetry();

function showSpread(slipJSONStr) {
    try {
        const slipData = JSON.parse(decodeURIComponent(slipJSONStr));
        const formattedData = JSON.stringify(slipData, null, 2);
        document.getElementById('spread-data').innerText = formattedData;
        document.getElementById('spread-modal').style.display = 'flex';
    } catch(e) {
        alert("No slippage data available for this trade.");
    }
}

// Ultra-smooth 60fps Progress Bar Animation (Independent of API ticks)
setInterval(() => {
    const bar = document.getElementById('volume-bar');
    if (!bar) return;
    
    const now = new Date();
    // Calculate exact percentage including milliseconds for liquid smooth CSS
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
