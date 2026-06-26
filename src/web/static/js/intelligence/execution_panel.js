async function loadExecution() {
    const res = await fetch('/api/intelligence/execution');
    const data1 = await res.json();
    const res2 = await fetch('/api/intelligence/scaling');
    const data2 = await res2.json();
    
    const tbody = document.querySelector('#execution-table tbody');
    let rows = '';
    for(let i=0; i<data1.length; i++){
        let d1 = data1[i];
        let d2 = data2.find(x => x.strike == d1.strike) || {avg_min_liquidity: 0, safe_lots: 0};
        rows += `<tr>
            <td>${d1.strike}</td><td>${d1.avg_spread}</td><td>${d1.est_entry_slippage}%</td>
            <td>${d1.est_exit_slippage}%</td><td>${d2.avg_min_liquidity}</td><td style="color:#f39c12; font-weight:bold">${d2.safe_lots}</td>
        </tr>`;
    }
    tbody.innerHTML = rows;
}