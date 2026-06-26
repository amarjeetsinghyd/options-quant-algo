async function loadFilters() {
    const res = await fetch('/api/intelligence/filters');
    const data = await res.json();
    const tbody = document.querySelector('#filter-table tbody');
    tbody.innerHTML = data.map(row => `
        <tr>
            <td>${row.filter}</td><td>${row.total_rejected}</td>
            <td style="color:#00e676">${row.correct_rejected}</td>
            <td style="color:#ff4444">${row.false_rejected}</td>
            <td>${row.protection_pct}%</td>
        </tr>
    `).join('');
}