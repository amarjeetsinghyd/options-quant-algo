// Initialization
document.addEventListener('DOMContentLoaded', () => {
    // Dynamic replacement of cached HTML emoji without requiring python server restart
    document.querySelectorAll('.btn').forEach(btn => {
        if (btn.innerHTML.includes('📊')) {
            btn.innerHTML = '<ion-icon name="flask-outline" style="font-size: 1.1em;"></ion-icon> Intelligence Lab';
            btn.style.display = 'flex';
            btn.style.alignItems = 'center';
            btn.style.gap = '6px';
        }
    });

    initTheme();
    fetchTelemetry();
    setInterval(fetchTelemetry, 3000);
});

let previousActiveTrade = null;
let previousHistoryCount = 0;
let currentLiveLtp = null;

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
    if (isChartInitialized) {
        applyChartTheme(target);
    }
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
        const response = await fetch('/api/status', { cache: 'no-store' });
        const data = await response.json();
        updateUI(data);
    } catch (e) {
        document.getElementById('status-dot').className = 'dot dot-offline';
        document.getElementById('status-text').innerText = 'OFFLINE';
    }
}

function updateUI(data) {
    const sysTop = document.getElementById('sys-mode-top');
    const sysBot = document.getElementById('sys-mode-bottom');
    const sysBadge = document.getElementById('system-mode-indicator');

    let btnStart = document.getElementById('btn-start');
    let btnStop = document.getElementById('btn-stop');

    if (data.status === 'initializing') {
        sysTop.innerText = "INITIALIZING MODE";
        sysBot.innerText = "CONNECTING...";
        sysBot.style.color = "var(--accent)";
        sysBadge.style.border = "1px solid var(--accent)";
        if(btnStart) btnStart.style.display = 'none';
        if(btnStop) btnStop.style.display = 'flex';
    } else if (data.status === 'running') {
        sysTop.innerText = "PAPER MODE";
        sysBot.innerText = "DATA LIVE";
        sysBot.style.color = "var(--success)";
        sysBadge.style.border = "1px solid var(--success)";
        if(btnStart) btnStart.style.display = 'none';
        if(btnStop) btnStop.style.display = 'flex';
    } else if (data.status === 'error') {
        sysTop.innerText = "ERROR MODE";
        sysBot.innerText = "API/WS DISCONNECTED";
        sysBot.style.color = "var(--danger)";
        sysBadge.style.border = "1px solid var(--danger)";
        if(btnStart) btnStart.style.display = 'flex';
        if(btnStop) btnStop.style.display = 'none';
        
        // Show error message if not shown in banner
        if (data.error_msg) {
            if(!data.errors) data.errors = [];
            if(!data.errors.includes(data.error_msg)) {
                data.errors.unshift(`[${data.error_time}] ${data.error_msg}`);
            }
        }
    } else {
        sysTop.innerText = "RESEARCH MODE";
        sysBot.innerText = "API OFF";
        sysBot.style.color = "var(--primary)";
        sysBadge.style.border = "1px solid var(--border)";
        if(btnStart) btnStart.style.display = 'flex';
        if(btnStop) btnStop.style.display = 'none';
    }

    // Render Error Banner
    const errorBanner = document.getElementById('error-banner');
    const errorList = document.getElementById('error-list');
    if (data.errors && data.errors.length > 0) {
        errorBanner.style.display = 'block';
        errorList.innerHTML = '';
        data.errors.forEach(err => {
            let li = document.createElement('li');
            li.innerText = err;
            errorList.appendChild(li);
        });
    } else {
        errorBanner.style.display = 'none';
    }

    if (data.telemetry) {
        if (data.telemetry.symbol) {
            document.getElementById('val-symbol').innerText = data.telemetry.symbol;
            const legendElem = document.getElementById('legend-symbol-display');
            if (legendElem) legendElem.innerText = data.telemetry.symbol;
        } else {
            document.getElementById('val-symbol').innerText = '--';
        }
        let ltpElem = document.getElementById('val-ltp');
        if (data.telemetry.ltp) {
            currentLiveLtp = data.telemetry.ltp;
            ltpElem.innerText = currentLiveLtp.toFixed(2);
        } else {
            ltpElem.innerText = '--';
        }
        
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
        
        let emaElem = document.getElementById('val-ema');
        let vwapVal = data.telemetry.vwap || 0;
        if (data.telemetry.ema) {
            let emaVal = data.telemetry.ema;
            emaElem.innerText = emaVal.toFixed(2);
            if (emaVal > vwapVal) emaElem.className = 'value text-green';
            else if (emaVal < vwapVal) emaElem.className = 'value text-red';
            else emaElem.className = 'value';
        } else {
            emaElem.innerText = '--';
            emaElem.className = 'value';
        }
        
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
        
        // Push live update to chart if initialized
        if (isChartInitialized && data.telemetry.ltp && candleSeries) {
            const t = Math.floor(Date.now() / 1000);
            
            // Note: In a production app, we would align this to the exact 1-min boundary 
            // and update the last candle. For simplicity, we just trigger a data refresh or append a live tick.
            // Since LightweightCharts needs standard time intervals, we'll re-fetch the small df or just update the last candle
            // However, to avoid complexity, we can just fetchChartData() every 60 seconds or so.
            // Let's just update the last candle's close if we have the current minute
            const lastCandleTime = (Math.floor(t / 60) * 60) + 19800; // rough IST alignment
            
            // To be precise with TradingView, it's safer to just let the backend feed the data on reload
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
    const progress = (exactSeconds / 60) * 100;
    bar.style.width = `${progress}%`;
}, 100);

// Candle Timer Overlay
setInterval(() => {
    const timerDiv = document.getElementById('candle-timer');
    if (!timerDiv || !chart || !candleSeries || !currentLiveLtp) return;
    
    // Check if the timer should be visible
    const sysModeBot = document.getElementById('sys-mode-bottom');
    const isOnline = sysModeBot && sysModeBot.innerText === 'DATA LIVE';
    
    if (!isOnline) {
        timerDiv.style.display = 'none';
        return;
    }

    const now = new Date();
    const secondsRemaining = 60 - now.getSeconds();
    timerDiv.innerText = `00:${secondsRemaining.toString().padStart(2, '0')}`;
    
    const yCoord = candleSeries.priceToCoordinate(currentLiveLtp);
    if (yCoord !== null) {
        timerDiv.style.display = 'block';
        timerDiv.style.top = `${yCoord + 12}px`;
    } else {
        timerDiv.style.display = 'none';
    }
}, 1000);

// --- CHART INTEGRATION ---
let chart;
let candleSeries;
let volumeSeries;
let vwapSeries;
let emaSeries;
let vfiChart;
let vfiSeries;
let vfiEmaSeries;
let vfiZeroLine;
let isChartInitialized = false;
let isFirstLoad = true;
let chartDataCache = [];
let isSyncing = false;

function initChart() {
    const chartContainer = document.getElementById('tv-chart');
    const vfiContainer = document.getElementById('vfi-chart');
    if (!chartContainer) return;
    
    // --- MAIN CHART ---
    const savedTheme = localStorage.getItem('theme') || 'dark';
    const isDark = savedTheme === 'dark';
    const bgColor = isDark ? '#1e293b' : '#ffffff';
    const txtColor = isDark ? '#d1d5db' : '#334155';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const borderColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';

    chart = LightweightCharts.createChart(chartContainer, {
        layout: {
            background: { type: 'solid', color: bgColor },
            textColor: txtColor,
        },
        grid: {
            vertLines: { color: gridColor },
            horzLines: { color: gridColor },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: borderColor,
            minimumWidth: 70,
            scaleMargins: {
                top: 0.1,
                bottom: 0.2, // Give the price 80% height, keeping a 5% buffer from volume
            },
        },
        timeScale: {
            borderColor: borderColor,
            timeVisible: true,
            secondsVisible: false,
        },
        handleScroll: true,
        handleScale: true,
    });

    candleSeries = chart.addCandlestickSeries({
        upColor: '#059669',
        downColor: '#dc2626',
        borderDownColor: '#dc2626',
        borderUpColor: '#059669',
        wickDownColor: '#dc2626',
        wickUpColor: '#059669',
    });

    volumeSeries = chart.addHistogramSeries({
        color: '#6366f1',
        priceFormat: { type: 'volume' },
        priceScaleId: '', 
        priceLineVisible: false,
    });
    
    volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 }
    });

    vwapSeries = chart.addLineSeries({
        color: '#3b82f6',
        lineWidth: 2,
        title: 'VWAP',
        crosshairMarkerVisible: false,
        priceLineVisible: false,
    });

    emaSeries = chart.addLineSeries({
        color: '#f59e0b',
        lineWidth: 2,
        title: '9 EMA',
        crosshairMarkerVisible: false,
        priceLineVisible: false,
    });

    // --- CROSSHAIR LEGEND ---
    function updateLegend(data) {
        const set = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val; };
        const fmt = (n) => n !== undefined && n !== null ? Number(n).toFixed(2) : '--';
        const fmtVol = (v) => v >= 1000000 ? (v/1000000).toFixed(2)+'M' : v >= 1000 ? (v/1000).toFixed(1)+'K' : (v||0).toString();

        set('legend-o', fmt(data.open));
        set('legend-h', fmt(data.high));
        set('legend-l', fmt(data.low));
        set('legend-c', fmt(data.close));
        set('legend-v', fmtVol(data.value));
        set('legend-vwap', fmt(data.vwap));
        set('legend-ema', fmt(data.ema_9));
        set('legend-vfi', fmt(data.vfi));
        set('legend-vfi-ema', fmt(data.vfi_ema));

        const legendC = document.getElementById('legend-c');
        if (legendC && data.close !== undefined && data.open !== undefined) {
            legendC.style.color = data.close >= data.open ? '#059669' : '#dc2626';
        }
        const legendVwap = document.getElementById('legend-vwap');
        if (legendVwap) legendVwap.style.color = '#3b82f6';
        const legendEma = document.getElementById('legend-ema');
        if (legendEma) legendEma.style.color = '#f59e0b';
        const legendVfiEma = document.getElementById('legend-vfi-ema');
        if (legendVfiEma) legendVfiEma.style.color = '#ef4444';
        const legendVfi = document.getElementById('legend-vfi');
        if (legendVfi && data.vfi !== undefined) {
            legendVfi.style.color = data.vfi > 0 ? '#10b981' : '#ef4444';
        }
    }

    // --- CROSSHAIR SYNC ---
    let isCrosshairSyncing = false;

    chart.subscribeCrosshairMove(param => {
        if (!chartDataCache.length) return;
        if (!param || !param.time) {
            updateLegend(chartDataCache[chartDataCache.length - 1]);
            if (!isCrosshairSyncing && vfiChart) {
                isCrosshairSyncing = true;
                vfiChart.clearCrosshairPosition();
                isCrosshairSyncing = false;
            }
            return;
        }

        const match = chartDataCache.find(d => d.time === param.time);
        if (match) updateLegend(match);

        if (!isCrosshairSyncing && vfiChart && vfiSeries) {
            isCrosshairSyncing = true;
            // Sync crosshair on VFI chart. We just use 0 as price to show the vertical line.
            vfiChart.setCrosshairPosition(0, param.time, vfiSeries);
            isCrosshairSyncing = false;
        }
    });

    // --- VFI SUB-CHART ---
    if (vfiContainer) {
        vfiChart = LightweightCharts.createChart(vfiContainer, {
            layout: {
                background: { type: 'solid', color: bgColor },
                textColor: txtColor,
            },
            grid: {
                vertLines: { color: gridColor },
                horzLines: { color: gridColor },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: borderColor,
                minimumWidth: 70,
            },
            timeScale: {
                borderColor: borderColor,
                timeVisible: true,
                secondsVisible: false,
                visible: false, // Hide time axis on VFI (main chart shows it)
            },
            handleScroll: true,
            handleScale: true,
        });

        // VFI Raw line (green)
        vfiSeries = vfiChart.addLineSeries({
            color: '#10b981',
            lineWidth: 2,
            title: 'VFI',
            crosshairMarkerVisible: false,
            priceLineVisible: false,
        });

        // VFI EMA line (orange/red)
        vfiEmaSeries = vfiChart.addLineSeries({
            color: '#ef4444',
            lineWidth: 1,
            lineStyle: 0,
            title: 'VFI EMA',
            crosshairMarkerVisible: false,
            priceLineVisible: false,
        });

        // Zero line (dashed)
        vfiZeroLine = vfiChart.addLineSeries({
            color: '#64748b',
            lineWidth: 1,
            lineStyle: 2, // Dashed
            title: '',
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
        });

        // --- SYNC TIME SCALES ---
        chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (isSyncing || !range) return;
            isSyncing = true;
            vfiChart.timeScale().setVisibleLogicalRange(range);
            isSyncing = false;
        });
        vfiChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (isSyncing || !range) return;
            isSyncing = true;
            chart.timeScale().setVisibleLogicalRange(range);
            isSyncing = false;
        });

        // Sync crosshair back from VFI to Main Chart
        vfiChart.subscribeCrosshairMove(param => {
            if (!chartDataCache.length) return;
            if (!param || !param.time) {
                updateLegend(chartDataCache[chartDataCache.length - 1]);
                if (!isCrosshairSyncing && chart) {
                    isCrosshairSyncing = true;
                    chart.clearCrosshairPosition();
                    isCrosshairSyncing = false;
                }
                return;
            }

            const match = chartDataCache.find(d => d.time === param.time);
            if (match) updateLegend(match);

            if (!isCrosshairSyncing && chart && candleSeries) {
                isCrosshairSyncing = true;
                // Use close price to roughly center the horizontal crosshair on main chart
                const price = match ? match.close : 0;
                chart.setCrosshairPosition(price, param.time, candleSeries);
                isCrosshairSyncing = false;
            }
        });
    }

    isChartInitialized = true;
    fetchChartData();
}

async function fetchChartData() {
    if (!isChartInitialized) return;
    const IST_OFFSET = 19800; // 5 hours 30 minutes in seconds
    try {
        const response = await fetch('/api/chart_data');
        const data = await response.json();
        
        if (data && data.length > 0) {
            // Add IST offset so chart displays Indian Standard Time
            data.forEach(d => { d.time = d.time + IST_OFFSET; });
            chartDataCache = data;
            
            const candles = data.map(d => ({time: d.time, open: d.open, high: d.high, low: d.low, close: d.close}));
            const volumes = data.map(d => ({time: d.time, value: d.value, color: d.close >= d.open ? '#05966988' : '#dc262688'}));
            
            candleSeries.setData(candles);
            volumeSeries.setData(volumes);
            
            if (data[0].vwap !== undefined) {
                vwapSeries.setData(data.filter(d => d.vwap).map(d => ({time: d.time, value: d.vwap})));
            }
            if (data[0].ema_9 !== undefined) {
                emaSeries.setData(data.filter(d => d.ema_9).map(d => ({time: d.time, value: d.ema_9})));
            }

            // --- VFI DATA ---
            if (vfiChart && data[0].vfi !== undefined) {
                const vfiData = data.filter(d => d.vfi !== 0).map(d => ({time: d.time, value: d.vfi}));
                if (vfiData.length > 0) {
                    vfiSeries.setData(vfiData);
                }
                
                if (data[0].vfi_ema !== undefined) {
                    const vfiEmaData = data.filter(d => d.vfi_ema !== 0).map(d => ({time: d.time, value: d.vfi_ema}));
                    if (vfiEmaData.length > 0) {
                        vfiEmaSeries.setData(vfiEmaData);
                    }
                }

                // Dashed zero line spanning the full data range
                const zeroData = data.map(d => ({time: d.time, value: 0}));
                vfiZeroLine.setData(zeroData);
            }
            
            // Only auto-fit on first load, after that preserve user's zoom/scroll position
            if (isFirstLoad) {
                chartShowToday();
                isFirstLoad = false;
            }
        }
    } catch (e) {
        console.error("Failed to fetch chart data", e);
    }
}

// --- CHART TOOLBAR FUNCTIONS ---
function chartZoomIn() {
    if (!chart) return;
    const timeScale = chart.timeScale();
    const range = timeScale.getVisibleLogicalRange();
    if (range) {
        const mid = (range.from + range.to) / 2;
        const halfRange = (range.to - range.from) / 4; // Zoom in by 50%
        timeScale.setVisibleLogicalRange({ from: mid - halfRange, to: mid + halfRange });
    }
}

function chartZoomOut() {
    if (!chart) return;
    const timeScale = chart.timeScale();
    const range = timeScale.getVisibleLogicalRange();
    if (range) {
        const mid = (range.from + range.to) / 2;
        const halfRange = (range.to - range.from); // Zoom out by 100%
        timeScale.setVisibleLogicalRange({ from: mid - halfRange, to: mid + halfRange });
    }
}

function chartScrollLeft() {
    if (!chart) return;
    const timeScale = chart.timeScale();
    const range = timeScale.getVisibleLogicalRange();
    if (range) {
        const shift = (range.to - range.from) * 0.2; // Shift by 20%
        timeScale.setVisibleLogicalRange({ from: range.from - shift, to: range.to - shift });
    }
}

function chartScrollRight() {
    if (!chart) return;
    const timeScale = chart.timeScale();
    const range = timeScale.getVisibleLogicalRange();
    if (range) {
        const shift = (range.to - range.from) * 0.2; // Shift by 20%
        timeScale.setVisibleLogicalRange({ from: range.from + shift, to: range.to + shift });
    }
}

function chartResetZoom() {
    if (!chart) return;
    chart.timeScale().fitContent();
}

function chartShowToday() {
    if (!chart || !chartDataCache.length) return;
    // Since we already added IST offset, chart times look like IST
    // Find today's 9:00 AM IST as a fake-UTC timestamp
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 9, 0, 0);
    const todayStartEpoch = Math.floor(todayStart.getTime() / 1000);
    
    // Find the index of the first candle today
    const todayIdx = chartDataCache.findIndex(d => d.time >= todayStartEpoch);
    if (todayIdx >= 0) {
        const totalBars = chartDataCache.length;
        chart.timeScale().setVisibleLogicalRange({
            from: todayIdx - 2,
            to: totalBars + 5
        });
    } else {
        // If no today data found, just fit all
        chart.timeScale().fitContent();
    }
}

function chartRefresh() {
    isFirstLoad = true;
    fetchChartData();
}

// Initialize chart immediately on DOM load (no delay)
document.addEventListener('DOMContentLoaded', () => {
    initChart();
});

// Refresh chart data every 15 seconds (without re-fitting)
setInterval(() => {
    const sysModeBot = document.getElementById('sys-mode-bottom');
    const isOnline = sysModeBot && sysModeBot.innerText === 'DATA LIVE';
    if (isChartInitialized && isOnline) {
        fetchChartData();
    }
}, 15000);

// --- CHART THEME TOGGLE ---
function applyChartTheme(theme) {
    if (!chart) return;
    const isDark = theme === 'dark';
    const bgColor = isDark ? '#1e293b' : '#ffffff';
    const txtColor = isDark ? '#d1d5db' : '#334155';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const borderColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';

    const chartOptions = {
        layout: {
            background: { type: 'solid', color: bgColor },
            textColor: txtColor,
        },
        grid: {
            vertLines: { color: gridColor },
            horzLines: { color: gridColor },
        },
        rightPriceScale: { borderColor: borderColor, minimumWidth: 70 },
        timeScale: { borderColor: borderColor },
    };

    chart.applyOptions(chartOptions);
    if (vfiChart) {
        vfiChart.applyOptions(chartOptions);
    }
}
