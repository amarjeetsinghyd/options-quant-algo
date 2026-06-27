# Current State

Repository structure is frozen after Architectural Refinement.

## Live Strategy Logic (As of June 27, 2026)

### 1. Window Alignment Strategy (Breakout)
*   **Anchor:** Price Close crosses the VWAP (Upside for CALL, Downside for PUT). No volume or size constraints.
*   **Waiting Window:** 10 minutes.
*   **Trigger:** 9 EMA crosses VWAP *and* VFI crosses Zero. All three conditions (Price, 9 EMA, VFI) must align on the correct side of VWAP/Zero.
*   **Momentum Check:** Within the 10-minute window, the sum of bodies in the trade direction must exceed the opposite direction (e.g. Total Green Body > Total Red Body for CALL).
*   **Stop Loss:** 9 EMA closes back across the VWAP in the wrong direction, or 3-minute Time Stop.

### 2. VWAP Rejection Strategy (Mean Reversion)
*   **Anchor:** Candle wick touches VWAP but closes on the rejection side (High >= VWAP and Close < VWAP for PUT).
*   **Waiting Window:** 5 minutes.
*   **Trigger:** Price crosses and closes beyond the 9 EMA in the trade direction. VFI must confirm (e.g. VFI < 0 and VFI < VFI_EMA for PUT).
*   **Momentum Check:** Within the 5-minute window, sum of bodies in the trade direction must exceed the opposite direction.
*   **Stop Loss:** Price closes back across the VWAP in the wrong direction, or 3-minute Time Stop.

### 3. Execution Rules (Shared)
*   Trades only occur between 10:00 AM and 3:15 PM.
*   Requires Positive Option Delta for execution (Sniper Mode).
*   10% Profit Target.
