async function loadOrderFlow() {
    const res = await fetch('/api/intelligence/orderflow');
    const data = await res.json();
    if(data.error) return;
    const c = document.getElementById('orderflow-metrics');
    c.innerHTML = `
        <div class="metric-card"><h3>+OFA Success Rate</h3><div class="val" style="color:#00e676">${data.ofa_positive_success}%</div></div>
        <div class="metric-card"><h3>-OFA Failure Confirm</h3><div class="val">${data.ofa_negative_failure_confirm}%</div></div>
        <div class="metric-card"><h3>Avg Buyer Aggression</h3><div class="val">${data.avg_buyer_aggression}</div></div>
        <div class="metric-card"><h3>Avg Seller Aggression</h3><div class="val">${data.avg_seller_aggression}</div></div>
    `;
}