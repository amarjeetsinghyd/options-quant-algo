async function loadInsights() {
    const res = await fetch('/api/intelligence/summary');
    const data = await res.json();
    const c = document.getElementById('insights-list');
    c.innerHTML = data.map(txt => `<li><ion-icon name="information-circle-outline"></ion-icon> ${txt}</li>`).join('');
}