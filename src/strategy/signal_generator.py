class SignalGenerator:
    def __init__(self):
        pass

    def check_signal(self, df):
        """
        Pure price-action breakout backed by institutional volume (VSA).
        Finds the exact Master Setup Candle.
        """
        if len(df) < 2:
            return None
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # --- 1. CALL Master Setup ---
        # Did price just cross ABOVE VWAP?
        if latest['close'] > latest['vwap'] and prev['close'] <= prev['vwap']:
            # VSA Gatekeeper
            if latest['rvol'] > 1.5 and latest['body_ratio'] >= 0.60:
                # Institutional Alignment
                if latest['vfi'] > 0:
                    return {
                        "type": "CALL",
                        "master_high": float(latest['high']),
                        "master_low": float(latest['low']),
                        "timestamp": latest['timestamp']
                    }
                    
        # --- 2. PUT Master Setup ---
        # Did price just cross BELOW VWAP?
        if latest['close'] < latest['vwap'] and prev['close'] >= prev['vwap']:
            # VSA Gatekeeper
            if latest['rvol'] > 1.5 and latest['body_ratio'] >= 0.60:
                # Institutional Alignment
                if latest['vfi'] < 0:
                    return {
                        "type": "PUT",
                        "master_high": float(latest['high']),
                        "master_low": float(latest['low']),
                        "timestamp": latest['timestamp']
                    }
                    
        return None
