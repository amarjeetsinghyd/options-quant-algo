async function loadStrike() {
    const res = await fetch('/api/intelligence/strike');
    const data = await res.json();
    const tbody = document.querySelector('#strike-table tbody');
    tbody.innerHTML = data.strikes.map(row => `
        <tr>
            <td>${row.name}</td><td>${row.observations}</td><td>${row.hit_pct}%</td>
            <td>${row.median_time}s</td><td>${row.max_favorable}%</td>
            <td style="color:#ff4444">-${row.max_adverse}%</td><td>${row.efficiency_score}</td>
        </tr>
    `).join('');
}