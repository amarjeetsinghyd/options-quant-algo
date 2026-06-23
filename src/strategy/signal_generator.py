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
                        "strategy": "VWAP_BREAKOUT",
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
                        "strategy": "VWAP_BREAKOUT",
                        "master_high": float(latest['high']),
                        "master_low": float(latest['low']),
                        "timestamp": latest['timestamp']
                    }
                    
        return None

    def check_rejection_signal(self, df):
        """
        VWAP Mean Reversion (Rejection / Support).
        Finds the exact Rejection Master Setup Candle.
        """
        if len(df) < 2:
            return None
            
        latest = df.iloc[-1]
        
        # We define a "touch" if the wick comes within 0.05% of the VWAP
        vwap = float(latest['vwap'])
        touch_margin = vwap * 0.0005
        
        # --- 1. CALL Support Setup (Bouncing off VWAP from above) ---
        if latest['vfi'] > 0 and latest['close'] > vwap:
            if latest['low'] <= (vwap + touch_margin) and latest['low'] >= (vwap - touch_margin):
                if latest['rvol'] > 1.0: # Moderate to high effort needed to support
                    return {
                        "type": "CALL",
                        "strategy": "VWAP_SUPPORT",
                        "master_high": float(latest['high']),
                        "master_low": float(latest['low']),
                        "timestamp": latest['timestamp']
                    }
                    
        # --- 2. PUT Rejection Setup (Failing to break VWAP from below) ---
        if latest['vfi'] < 0 and latest['close'] < vwap:
            if latest['high'] >= (vwap - touch_margin) and latest['high'] <= (vwap + touch_margin):
                if latest['rvol'] > 1.0: # Moderate to high effort needed to reject
                    return {
                        "type": "PUT",
                        "strategy": "VWAP_REJECTION",
                        "master_high": float(latest['high']),
                        "master_low": float(latest['low']),
                        "timestamp": latest['timestamp']
                    }
                    
        return None
