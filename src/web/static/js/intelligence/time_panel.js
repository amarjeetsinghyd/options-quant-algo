let timeChartInst = null;
async function loadTime() {
    const res = await fetch('/api/intelligence/time');
    const data = await res.json();
    const dist = data.distribution;
    if(!dist) return;
    
    const ctx = document.getElementById('timeChart').getContext('2d');
    if(timeChartInst) timeChartInst.destroy();
    
    timeChartInst = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(dist),
            datasets: [{
                data: Object.values(dist),
                backgroundColor: ['#00d2ff', '#3a7bd5', '#f39c12', '#e74c3c', '#555'],
                borderWidth: 0
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
}