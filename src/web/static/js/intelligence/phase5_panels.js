let rawMLData = null;

async function loadPhase5Data() {
    try {
        const response = await fetch('/api/intelligence/ml_brain');
        const data = await response.json();
        
        if (data.error) {
            console.error("ML Brain API error:", data.error);
            return;
        }
        
        rawMLData = data;
        renderPhase5Data();
    } catch (e) {
        console.error("Error loading Phase 5 ML panels:", e);
    }
}

function getSessionBadge(sessionType) {
    sessionType = sessionType || "UNKNOWN";
    let bg = "rgba(108,117,125,0.15)", color = "#6c757d";
    if (sessionType === "LIVE") { bg = "rgba(40,167,69,0.15)"; color = "#28a745"; }
    else if (sessionType === "PREOPEN") { bg = "rgba(255,193,7,0.15)"; color = "#ffc107"; }
    else if (sessionType === "AFTER_MARKET") { bg = "rgba(108,117,125,0.15)"; color = "#6c757d"; }
    else if (sessionType === "HOLIDAY") { bg = "rgba(220,53,69,0.15)"; color = "#dc3545"; }
    else if (sessionType === "SIMULATION") { bg = "rgba(111,66,193,0.15)"; color = "#6f42c1"; }
    else if (sessionType === "REPLAY") { bg = "rgba(23,162,184,0.15)"; color = "#17a2b8"; }
    else if (sessionType === "UNIT_TEST") { bg = "rgba(0,210,255,0.15)"; color = "#00d2ff"; }
    return `<span style="background: ${bg}; color: ${color}; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 11px;">${sessionType}</span>`;
}

function getConnectionBadge(connQuality) {
    connQuality = connQuality || "UNKNOWN";
    let bg = "rgba(108,117,125,0.15)", color = "#6c757d";
    if (connQuality === "GOOD") { bg = "rgba(40,167,69,0.15)"; color = "#28a745"; }
    else if (connQuality === "DEGRADED") { bg = "rgba(253,126,20,0.15)"; color = "#fd7e14"; }
    else if (connQuality === "POOR") { bg = "rgba(220,53,69,0.15)"; color = "#dc3545"; }
    return `<span style="background: ${bg}; color: ${color}; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 11px;">${connQuality}</span>`;
}

function getQualityBadge(qualityScore) {
    const val = parseFloat(qualityScore !== undefined && qualityScore !== null ? qualityScore : 100);
    let color = "#28a745";
    if (val < 50) color = "#ff4a4a";
    else if (val < 80) color = "#fd7e14";
    else if (val < 95) color = "#ffc107";
    return `<span style="color: ${color}; font-weight: bold;">${val.toFixed(0)}</span>`;
}

function renderPhase5Data() {
    if (!rawMLData) return;
    
    // Get filter values
    const filterSession = document.getElementById("filter-session")?.value || "ALL";
    const filterQuality = parseFloat(document.getElementById("filter-quality")?.value || "0");
    const filterVersion = document.getElementById("filter-version")?.value.trim().toLowerCase() || "";
    const filterSource = document.getElementById("filter-source")?.value.trim().toLowerCase() || "";
    
    // Helper filter function
    const filterItem = (item) => {
        if (filterSession !== "ALL" && item.session_type !== filterSession) return false;
        if (filterQuality > 0 && (item.quality_score || 0) < filterQuality) return false;
        if (filterVersion && !String(item.observation_version || "").toLowerCase().includes(filterVersion)) return false;
        if (filterSource && !String(item.data_source || "").toLowerCase().includes(filterSource)) return false;
        return true;
    };
    
    // 1. Update ML Maturity Card
    const maturityLevelEl = document.getElementById("ml-maturity-level");
    const maturitySamplesEl = document.getElementById("ml-maturity-samples");
    
    if (maturityLevelEl && maturitySamplesEl) {
        const levelNames = [
            "Level 0: Data Collection Mode", 
            "Level 1: Initial Modeling Ready", 
            "Level 2: Advanced Validation Mode", 
            "Level 3: Production Candidate Ready"
        ];
        const level = rawMLData.ml_maturity.level || 0;
        maturityLevelEl.textContent = levelNames[level];
        
        const levelColors = ["#ffc107", "#17a2b8", "#00d2ff", "#28a745"];
        maturityLevelEl.style.color = levelColors[level];
        
        maturitySamplesEl.textContent = `${rawMLData.ml_maturity.samples || 0} samples collected`;
    }
    
    // 2. Render Quality Distribution Table
    const qualityDistTbody = document.getElementById("quality-dist-tbody");
    if (qualityDistTbody) {
        const qDist = rawMLData.quality_distribution || {};
        const total = rawMLData.ml_maturity.samples || 1;
        
        const rows = [
            { grade: "Quality 4", desc: "Explosive Gamma Expansion (>= 20%)", count: qDist.quality_4 || 0, color: "#28a745" },
            { grade: "Quality 3", desc: "Clean Gamma Expansion (10-20%)", count: qDist.quality_3 || 0, color: "#a3e144" },
            { grade: "Quality 2", desc: "Small Gamma Expansion (5-10%)", count: qDist.quality_2 || 0, color: "#00d2ff" },
            { grade: "Quality 1", desc: "Failed Breakout / Failed Ignition", count: qDist.quality_1 || 0, color: "#ffc107" },
            { grade: "Quality 0", desc: "Dead Move (Low Volatility Sample <3%)", count: qDist.quality_0 || 0, color: "#6c757d" }
        ];
        
        qualityDistTbody.innerHTML = rows.map(r => {
            const pct = total > 0 ? ((r.count / total) * 100).toFixed(1) : "0.0";
            return `
                <tr>
                    <td style="color: ${r.color}; font-weight: bold;">${r.grade}</td>
                    <td style="color: var(--text-secondary);">${r.desc}</td>
                    <td><strong>${r.count}</strong> <span style="font-size: 11px; color: #888; margin-left: 5px;">(${pct}%)</span></td>
                </tr>
            `;
        }).join("");
    }
    
    // 3. Render Data Quality Stats
    const dqTotalEl = document.getElementById("dq-total");
    const dqBadTicksEl = document.getElementById("dq-bad-ticks");
    const dqLogsTbody = document.getElementById("dq-logs-tbody");
    
    if (rawMLData.data_quality_stats) {
        const dq = rawMLData.data_quality_stats;
        if (dqTotalEl) dqTotalEl.textContent = dq.total_issues || 0;
        if (dqBadTicksEl) dqBadTicksEl.textContent = dq.bad_ticks || 0;
        
        if (dqLogsTbody) {
            const filteredLogs = (dq.recent_logs || []).filter(filterItem);
            if (filteredLogs.length > 0) {
                dqLogsTbody.innerHTML = filteredLogs.map(log => {
                    const dateStr = log.timestamp ? log.timestamp.replace("T", " ") : "--";
                    const statusColor = log.status === "DROPPED" ? "#ff4a4a" : "#ffc107";
                    return `
                        <tr>
                            <td>${dateStr}</td>
                            <td><code>${log.symbol}</code></td>
                            <td><span style="background: rgba(255,255,255,0.07); padding: 2px 6px; border-radius: 4px; font-size:11px;">${log.metric_type}</span></td>
                            <td>${log.value}</td>
                            <td style="color: ${statusColor}; font-weight: bold;">${log.status}</td>
                            <td>${getSessionBadge(log.session_type)}</td>
                            <td>${getQualityBadge(log.quality_score)}</td>
                            <td>${getConnectionBadge(log.connection_quality)}</td>
                            <td><code style="font-size:11px;">${log.observation_version || "--"}</code></td>
                            <td><span style="font-size:11px; color:var(--text-secondary);">${log.data_source || "--"}</span></td>
                        </tr>
                    `;
                }).join("");
            } else {
                dqLogsTbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-secondary);">No data quality issues match the active filters.</td></tr>`;
            }
        }
    }
    
    // 4. Render Failed Ignitions Table (Missed Opportunities)
    const failedIgnitionTbody = document.getElementById("failed-ignition-tbody");
    if (failedIgnitionTbody) {
        const filteredFailures = (rawMLData.recent_failures || []).filter(filterItem);
        if (filteredFailures.length > 0) {
            failedIgnitionTbody.innerHTML = filteredFailures.map(f => {
                const timeStr = f.timestamp ? f.timestamp.replace("T", " ") : "--";
                return `
                    <tr>
                        <td style="color: var(--text-secondary);">${timeStr}</td>
                        <td><strong>${f.symbol}</strong></td>
                        <td style="color: #ffc107; font-weight: bold;">+${f.move.toFixed(1)}%</td>
                        <td style="color: #ff4a4a;">-${f.rejection.toFixed(1)}%</td>
                        <td><span style="color: #ff4a4a; background: rgba(255, 74, 74, 0.1); padding: 2px 6px; border-radius: 4px; font-size: 11px;">${f.reason}</span></td>
                        <td>${getSessionBadge(f.session_type)}</td>
                        <td>${getQualityBadge(f.quality_score)}</td>
                        <td>${getConnectionBadge(f.connection_quality)}</td>
                        <td><code style="font-size:11px;">${f.observation_version || "--"}</code></td>
                        <td><span style="font-size:11px; color:var(--text-secondary);">${f.data_source || "--"}</span></td>
                    </tr>
                `;
            }).join("");
        } else {
            failedIgnitionTbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-secondary);">No failed breakouts match the active filters.</td></tr>`;
        }
    }
    
    // 5. Render Feature Regimes Table
    const featureRegimesTbody = document.getElementById("feature-regimes-tbody");
    if (featureRegimesTbody) {
        if (rawMLData.feature_regimes && rawMLData.feature_regimes.length > 0) {
            featureRegimesTbody.innerHTML = rawMLData.feature_regimes.map(feat => {
                const driftBadge = feat.drift_count > 0 
                    ? `<span style="color: #ff4a4a; background: rgba(255,74,74,0.1); padding: 2px 6px; border-radius: 4px; font-weight: bold;">DRIFT (${feat.drift_count})</span>`
                    : `<span style="color: #28a745;">Stable</span>`;
                return `
                    <tr>
                        <td><code>${feat.feature}</code></td>
                        <td style="font-weight: bold; color: ${feat.regime === "TRENDING" ? "#00d2ff" : "#ffc107"};">${feat.regime}</td>
                        <td><strong>${feat.avg_importance.toFixed(1)}%</strong></td>
                        <td>${driftBadge}</td>
                    </tr>
                `;
            }).join("");
        } else {
            featureRegimesTbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-secondary);">No feature importance records yet. Run training after-hours to populate.</td></tr>`;
        }
    }
    
    // 6. Render Recent Explosive Discoveries & Paths
    const explosiveDiscoveriesTbody = document.getElementById("explosive-discoveries-tbody");
    if (explosiveDiscoveriesTbody) {
        const filteredExplosions = (rawMLData.recent_explosions || []).filter(filterItem);
        if (filteredExplosions.length > 0) {
            explosiveDiscoveriesTbody.innerHTML = filteredExplosions.map(e => {
                const timeStr = e.timestamp ? e.timestamp.replace("T", " ") : "--";
                let pathProgression = "N/A";
                if (e.premium_path && e.premium_path.length > 0) {
                    const startPrice = e.premium_path[0];
                    const maxPrice = Math.max(...e.premium_path);
                    const endPrice = e.premium_path[e.premium_path.length - 1];
                    pathProgression = `₹${startPrice.toFixed(1)} → <span style="color:#28a745;font-weight:bold;">₹${maxPrice.toFixed(1)}</span> (End: ₹${endPrice.toFixed(1)})`;
                }
                return `
                    <tr>
                        <td style="color: var(--text-secondary);">${timeStr}</td>
                        <td><strong>${e.symbol}</strong></td>
                        <td style="color: #28a745; font-weight: bold;">+${e.move.toFixed(1)}%</td>
                        <td>${pathProgression}</td>
                        <td>${getSessionBadge(e.session_type)}</td>
                        <td>${getQualityBadge(e.quality_score)}</td>
                        <td>${getConnectionBadge(e.connection_quality)}</td>
                        <td><code style="font-size:11px;">${e.observation_version || "--"}</code></td>
                        <td><span style="font-size:11px; color:var(--text-secondary);">${e.data_source || "--"}</span></td>
                    </tr>
                `;
            }).join("");
        } else {
            explosiveDiscoveriesTbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-secondary);">No explosive gamma events match the active filters.</td></tr>`;
        }
    }
}

// Bind event listeners for the filter buttons once scripts are loaded
setTimeout(() => {
    const applyBtn = document.getElementById("apply-ml-filters");
    if (applyBtn) {
        applyBtn.addEventListener("click", renderPhase5Data);
        console.log("[Phase5Panels] Successfully bound filter handler.");
    }
}, 1000);
