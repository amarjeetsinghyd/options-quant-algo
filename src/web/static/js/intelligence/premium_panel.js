async function loadPremium() {
    const res = await fetch('/api/intelligence/premium');
    const data = await res.json();
    const tbody = document.querySelector('#premium-table tbody');
    tbody.innerHTML = data.map(row => `
        <tr>
            <td>${row.bucket}</td><td>${row.win_pct}%</td>
            <td>${row.speed_sec}s</td><td>${row.slippage}%</td>
            <td>${row.gamma_adv}</td>
        </tr>
    `).join('');
}