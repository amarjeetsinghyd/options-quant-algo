async function loadAllPanels() {
    try {
        await Promise.all([
            loadOverview(),
            loadInsights(),
            loadStrike(),
            loadPremium(),
            loadTime(),
            loadFilters(),
            loadOrderFlow(),
            loadExecution(),
            loadMarket(),
            loadPhase41Data(),
            fetchPhase42Panels(),
            fetchPhase43Panels(),
            loadPhase5Data()
        ]);
    } catch (e) { console.error("Error loading panels:", e); }
}

document.addEventListener("DOMContentLoaded", () => {
    loadAllPanels();
    document.getElementById("refresh-lab").addEventListener("click", loadAllPanels);
});