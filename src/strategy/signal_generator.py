class SignalGenerator:
    def __init__(self):
        pass

    def check_signal(self, df):
        """
        Pure price-action breakout backed by institutional volume (VSA).
        Finds the exact Master Setup Candle.
        """
        if len(df) < 11:
            return None
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # --- Phase 1: The Alignment Trigger ---
        call_aligned = latest['close'] > latest['vwap'] and latest['close'] > latest['ema_9'] and latest['vfi'] > 0
        call_prev_aligned = prev['close'] > prev['vwap'] and prev['close'] > prev['ema_9'] and prev['vfi'] > 0
        
        put_aligned = latest['close'] < latest['vwap'] and latest['close'] < latest['ema_9'] and latest['vfi'] < 0
        put_prev_aligned = prev['close'] < prev['vwap'] and prev['close'] < prev['ema_9'] and prev['vfi'] < 0
        
        trigger_call = call_aligned and not call_prev_aligned
        trigger_put = put_aligned and not put_prev_aligned
        
        if not (trigger_call or trigger_put):
            return None
            
        # Helper: shifted arrays for exact crossover checks over the whole df
        shifted_close = df['close'].shift(1)
        shifted_vwap = df['vwap'].shift(1)
        
        # --- Phase 2 & 3 for CALL ---
        if trigger_call:
            # 10-Minute Anchor Search (Close crosses above VWAP)
            cross_up_mask = (df['close'] > df['vwap']) & (shifted_close <= shifted_vwap)
            cross_up_window = cross_up_mask.iloc[-10:]
            
            if not cross_up_window.any():
                return None # No anchor in the last 10 minutes
                
            # Get the index of the most recent anchor in the window
            anchor_idx_loc = cross_up_window[cross_up_window].index[-1]
            analysis_window = df.loc[anchor_idx_loc:]
            
            # 1. Institutional Presence (Flexible RVOL)
            valid_vsa = analysis_window[(analysis_window['close'] > analysis_window['open']) & 
                                        (analysis_window['rvol'] > 1.5) & 
                                        (analysis_window['body_ratio'] >= 0.60)]
            if valid_vsa.empty:
                return None
                
            # 2. Window Momentum Check
            anchor_candle = df.loc[anchor_idx_loc]
            if len(analysis_window) > 1 and latest['close'] < anchor_candle['high']:
                return None # Momentum faded
                
            # 3. Directional Dominance (Relative Candle Size)
            largest_vol_idx = analysis_window['volume'].idxmax()
            largest_candle = analysis_window.loc[largest_vol_idx]
            if largest_candle['close'] <= largest_candle['open']:
                return None # Largest volume was a red candle!
                
            green_bodies = analysis_window[analysis_window['close'] > analysis_window['open']]['real_body']
            red_bodies = analysis_window[analysis_window['close'] < analysis_window['open']]['real_body']
            
            total_green_body = green_bodies.sum()
            total_red_body = red_bodies.sum()
            
            if total_green_body < total_red_body:
                return None # Red pullbacks are bigger than green pushes
                
            return {
                "type": "CALL",
                "strategy": "WINDOW_ALIGNMENT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp']
            }
            
        # --- Phase 2 & 3 for PUT ---
        if trigger_put:
            # 10-Minute Anchor Search (Close crosses below VWAP)
            cross_dn_mask = (df['close'] < df['vwap']) & (shifted_close >= shifted_vwap)
            cross_dn_window = cross_dn_mask.iloc[-10:]
            
            if not cross_dn_window.any():
                return None
                
            # Get the index of the most recent anchor in the window
            anchor_idx_loc = cross_dn_window[cross_dn_window].index[-1]
            analysis_window = df.loc[anchor_idx_loc:]
            
            # 1. Institutional Presence (Flexible RVOL)
            valid_vsa = analysis_window[(analysis_window['close'] < analysis_window['open']) & 
                                        (analysis_window['rvol'] > 1.5) & 
                                        (analysis_window['body_ratio'] >= 0.60)]
            if valid_vsa.empty:
                return None
                
            # 2. Window Momentum Check
            anchor_candle = df.loc[anchor_idx_loc]
            if len(analysis_window) > 1 and latest['close'] > anchor_candle['low']:
                return None # Momentum faded
                
            # 3. Directional Dominance (Relative Candle Size)
            largest_vol_idx = analysis_window['volume'].idxmax()
            largest_candle = analysis_window.loc[largest_vol_idx]
            if largest_candle['close'] >= largest_candle['open']:
                return None # Largest volume was a green candle!
                
            green_bodies = analysis_window[analysis_window['close'] > analysis_window['open']]['real_body']
            red_bodies = analysis_window[analysis_window['close'] < analysis_window['open']]['real_body']
            
            total_green_body = green_bodies.sum()
            total_red_body = red_bodies.sum()
            
            if total_red_body < total_green_body:
                return None # Green pullbacks are bigger than red pushes
                
            return {
                "type": "PUT",
                "strategy": "WINDOW_ALIGNMENT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp']
            }
            
        return None

    def check_rejection_signal(self, df):
        """
        VWAP Mean Reversion (Rejection / Support) using 5-Minute Window Analysis.
        Finds the exact Rejection Setup by anchoring to a VWAP wick touch and triggering on 9 EMA cross.
        """
        if len(df) < 6:
            return None
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # --- Phase 1: The Reversal Trigger (9 EMA Crossover + VFI Filter) ---
        call_trigger = latest['close'] > latest['ema_9'] and prev['close'] <= prev['ema_9'] and latest['vfi'] > 0 and latest['vfi'] > latest.get('vfi_ema', latest['vfi'])
        put_trigger = latest['close'] < latest['ema_9'] and prev['close'] >= prev['ema_9'] and latest['vfi'] < 0 and latest['vfi'] < latest.get('vfi_ema', latest['vfi'])
        
        if not (call_trigger or put_trigger):
            return None
            
        # Helper arrays for anchor search
        # CALL Anchor: Low touches/pierces VWAP (low <= vwap), but candle closes ABOVE VWAP (close > vwap)
        call_anchor_mask = (df['low'] <= df['vwap']) & (df['close'] > df['vwap'])
        # PUT Anchor: High touches/pierces VWAP (high >= vwap), but candle closes BELOW VWAP (close < vwap)
        put_anchor_mask = (df['high'] >= df['vwap']) & (df['close'] < df['vwap'])
        
        # --- Phase 2 & 3 for CALL (Support Bounce) ---
        if call_trigger:
            # 5-Minute Anchor Search
            anchor_window = call_anchor_mask.iloc[-5:]
            if not anchor_window.any():
                return None
                
            anchor_idx_loc = anchor_window[anchor_window].index[-1]
            analysis_window = df.loc[anchor_idx_loc:]
            
            # 1. Institutional Presence (Moderate effort to support)
            valid_vsa = analysis_window[analysis_window['rvol'] > 1.2]
            if valid_vsa.empty:
                return None
                
            # 2. Directional Dominance (Total Body Method)
            largest_vol_idx = analysis_window['volume'].idxmax()
            largest_candle = analysis_window.loc[largest_vol_idx]
            if largest_candle['close'] <= largest_candle['open']:
                return None # Largest volume was a red candle!
                
            green_bodies = analysis_window[analysis_window['close'] > analysis_window['open']]['real_body']
            red_bodies = analysis_window[analysis_window['close'] < analysis_window['open']]['real_body']
            
            total_green_body = green_bodies.sum()
            total_red_body = red_bodies.sum()
            
            if total_green_body <= total_red_body:
                return None # Red pullbacks are bigger than green pushes
                
            return {
                "type": "CALL",
                "strategy": "REJECTION_WINDOW",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp']
            }
            
        # --- Phase 2 & 3 for PUT (Resistance Rejection) ---
        if put_trigger:
            # 5-Minute Anchor Search
            anchor_window = put_anchor_mask.iloc[-5:]
            if not anchor_window.any():
                return None
                
            anchor_idx_loc = anchor_window[anchor_window].index[-1]
            analysis_window = df.loc[anchor_idx_loc:]
            
            # 1. Institutional Presence (Moderate effort to reject)
            valid_vsa = analysis_window[analysis_window['rvol'] > 1.2]
            if valid_vsa.empty:
                return None
                
            # 2. Directional Dominance (Total Body Method)
            largest_vol_idx = analysis_window['volume'].idxmax()
            largest_candle = analysis_window.loc[largest_vol_idx]
            if largest_candle['close'] >= largest_candle['open']:
                return None # Largest volume was a green candle!
                
            green_bodies = analysis_window[analysis_window['close'] > analysis_window['open']]['real_body']
            red_bodies = analysis_window[analysis_window['close'] < analysis_window['open']]['real_body']
            
            total_green_body = green_bodies.sum()
            total_red_body = red_bodies.sum()
            
            if total_red_body <= total_green_body:
                return None # Green pullbacks are bigger than red pushes
                
            return {
                "type": "PUT",
                "strategy": "REJECTION_WINDOW",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp']
            }
            
        return None
