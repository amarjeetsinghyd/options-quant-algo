class SignalGenerator:
    def __init__(self):
        pass

    def check_signal(self, df):
        """
        10-Minute Window Breakout Strategy.
        Returns: (Signal_Dict, Decision_State_Dict)
        """
        decision_state = {
            "human_reason": "Not enough data",
            "machine_state": {"bars": len(df)}
        }
        if len(df) < 11:
            return None, decision_state
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        call_aligned = bool(latest['close'] > latest['vwap'] and latest['ema_9'] > latest['vwap'] and latest['vfi'] > 0)
        call_prev_aligned = bool(prev['close'] > prev['vwap'] and prev['ema_9'] > prev['vwap'] and prev['vfi'] > 0)
        
        put_aligned = bool(latest['close'] < latest['vwap'] and latest['ema_9'] < latest['vwap'] and latest['vfi'] < 0)
        put_prev_aligned = bool(prev['close'] < prev['vwap'] and prev['ema_9'] < prev['vwap'] and prev['vfi'] < 0)
        
        trigger_call = call_aligned and not call_prev_aligned
        trigger_put = put_aligned and not put_prev_aligned
        
        decision_state["machine_state"].update({
            "call_trigger_attempt": trigger_call,
            "put_trigger_attempt": trigger_put,
            "latest_close": float(latest['close']),
            "latest_ema_9": float(latest['ema_9']),
            "latest_vwap": float(latest['vwap']),
            "latest_vfi": float(latest['vfi'])
        })
        
        if not (trigger_call or trigger_put):
            decision_state["human_reason"] = "Conditions not aligned for trigger"
            return None, decision_state
            
        shifted_close = df['close'].shift(1)
        shifted_vwap = df['vwap'].shift(1)
        
        if trigger_call:
            cross_up_mask = (df['close'] > df['vwap']) & (shifted_close <= shifted_vwap)
            cross_up_window = cross_up_mask.iloc[-10:]
            
            if not cross_up_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                decision_state["human_reason"] = "No bullish VWAP crossover anchor in last 10 minutes"
                return None, decision_state
                
            decision_state["machine_state"]["anchor_found"] = True
            anchor_idx_loc = cross_up_window[cross_up_window].index[-1]
            analysis_window = df.iloc[df.index.get_loc(anchor_idx_loc):]
            
            green_bodies = analysis_window[analysis_window['close'] > analysis_window['open']]['real_body']
            red_bodies = analysis_window[analysis_window['close'] < analysis_window['open']]['real_body']
            
            total_green_body = green_bodies.sum()
            total_red_body = red_bodies.sum()
            
            decision_state["machine_state"].update({
                "total_green_body": float(total_green_body),
                "total_red_body": float(total_red_body)
            })
            
            if total_green_body <= total_red_body:
                decision_state["machine_state"]["momentum_passed"] = False
                decision_state["human_reason"] = "Failed momentum check: Red bodies dominated"
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for CALL breakout"
            
            signal = {
                "type": "CALL",
                "strategy": "WINDOW_ALIGNMENT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        if trigger_put:
            cross_dn_mask = (df['close'] < df['vwap']) & (shifted_close >= shifted_vwap)
            cross_dn_window = cross_dn_mask.iloc[-10:]
            
            if not cross_dn_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                decision_state["human_reason"] = "No bearish VWAP crossover anchor in last 10 minutes"
                return None, decision_state
                
            decision_state["machine_state"]["anchor_found"] = True
            anchor_idx_loc = cross_dn_window[cross_dn_window].index[-1]
            analysis_window = df.iloc[df.index.get_loc(anchor_idx_loc):]
            
            green_bodies = analysis_window[analysis_window['close'] > analysis_window['open']]['real_body']
            red_bodies = analysis_window[analysis_window['close'] < analysis_window['open']]['real_body']
            
            total_green_body = green_bodies.sum()
            total_red_body = red_bodies.sum()
            
            decision_state["machine_state"].update({
                "total_green_body": float(total_green_body),
                "total_red_body": float(total_red_body)
            })
            
            if total_red_body <= total_green_body:
                decision_state["machine_state"]["momentum_passed"] = False
                decision_state["human_reason"] = "Failed momentum check: Green bodies dominated"
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for PUT breakout"
            
            signal = {
                "type": "PUT",
                "strategy": "WINDOW_ALIGNMENT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        return None, decision_state

    def check_rejection_signal(self, df):
        """
        5-Minute Rejection Strategy.
        Returns: (Signal_Dict, Decision_State_Dict)
        """
        decision_state = {
            "human_reason": "Not enough data",
            "machine_state": {"bars": len(df)}
        }
        if len(df) < 6:
            return None, decision_state
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        call_trigger = bool(latest['close'] > latest['ema_9'] and prev['close'] <= prev['ema_9'] and latest['vfi'] > 0 and latest['vfi'] > latest.get('vfi_ema', latest['vfi']))
        put_trigger = bool(latest['close'] < latest['ema_9'] and prev['close'] >= prev['ema_9'] and latest['vfi'] < 0 and latest['vfi'] < latest.get('vfi_ema', latest['vfi']))
        
        decision_state["machine_state"].update({
            "call_trigger_attempt": call_trigger,
            "put_trigger_attempt": put_trigger,
            "latest_close": float(latest['close']),
            "latest_ema_9": float(latest['ema_9']),
            "latest_vwap": float(latest['vwap']),
            "latest_vfi": float(latest['vfi'])
        })
        
        if not (call_trigger or put_trigger):
            decision_state["human_reason"] = "Conditions not aligned for rejection trigger"
            return None, decision_state
            
        call_anchor_mask = (df['low'] <= df['vwap']) & (df['close'] > df['vwap'])
        put_anchor_mask = (df['high'] >= df['vwap']) & (df['close'] < df['vwap'])
        
        if call_trigger:
            anchor_window = call_anchor_mask.iloc[-5:]
            if not anchor_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                decision_state["human_reason"] = "No bullish rejection anchor in last 5 minutes"
                return None, decision_state
                
            decision_state["machine_state"]["anchor_found"] = True
            anchor_idx_loc = anchor_window[anchor_window].index[-1]
            analysis_window = df.iloc[df.index.get_loc(anchor_idx_loc):]
            
            green_bodies = analysis_window[analysis_window['close'] > analysis_window['open']]['real_body']
            red_bodies = analysis_window[analysis_window['close'] < analysis_window['open']]['real_body']
            
            total_green_body = green_bodies.sum()
            total_red_body = red_bodies.sum()
            
            decision_state["machine_state"].update({
                "total_green_body": float(total_green_body),
                "total_red_body": float(total_red_body)
            })
            
            if total_green_body <= total_red_body:
                decision_state["machine_state"]["momentum_passed"] = False
                decision_state["human_reason"] = "Failed momentum check: Red bodies dominated"
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for CALL rejection"
            
            signal = {
                "type": "CALL",
                "strategy": "REJECTION_WINDOW",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        if put_trigger:
            anchor_window = put_anchor_mask.iloc[-5:]
            if not anchor_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                decision_state["human_reason"] = "No bearish rejection anchor in last 5 minutes"
                return None, decision_state
                
            decision_state["machine_state"]["anchor_found"] = True
            anchor_idx_loc = anchor_window[anchor_window].index[-1]
            analysis_window = df.iloc[df.index.get_loc(anchor_idx_loc):]
            
            green_bodies = analysis_window[analysis_window['close'] > analysis_window['open']]['real_body']
            red_bodies = analysis_window[analysis_window['close'] < analysis_window['open']]['real_body']
            
            total_green_body = green_bodies.sum()
            total_red_body = red_bodies.sum()
            
            decision_state["machine_state"].update({
                "total_green_body": float(total_green_body),
                "total_red_body": float(total_red_body)
            })
            
            if total_red_body <= total_green_body:
                decision_state["machine_state"]["momentum_passed"] = False
                decision_state["human_reason"] = "Failed momentum check: Green bodies dominated"
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for PUT rejection"
            
            signal = {
                "type": "PUT",
                "strategy": "REJECTION_WINDOW",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        return None, decision_state

    def check_vwap_band_breakout_signal(self, df):
        """
        VWAP Band Breakout Strategy (Strategy 3).
        CALL: Price crosses above vwap_low AND vfi > 0.
        PUT: Price crosses below vwap_high AND vfi < 0.
        """
        decision_state = {
            "human_reason": "Not enough data",
            "machine_state": {"bars": len(df)}
        }
        if len(df) < 2:
            return None, decision_state
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Check CALL: Cross above vwap_low, cover 30% of band, and vfi > 0
        call_required_close = latest['vwap_low'] + 0.30 * (latest['vwap'] - latest['vwap_low'])
        call_trigger = bool(
            latest['close'] >= call_required_close and 
            prev['close'] <= latest['vwap_low'] and 
            latest['vfi'] > 0
        )
        
        # Check PUT: Cross below vwap_high, cover 30% of band, and vfi < 0
        put_required_close = latest['vwap_high'] - 0.30 * (latest['vwap_high'] - latest['vwap'])
        put_trigger = bool(
            latest['close'] <= put_required_close and 
            prev['close'] >= latest['vwap_high'] and 
            latest['vfi'] < 0
        )
        
        decision_state["machine_state"].update({
            "call_trigger_attempt": call_trigger,
            "put_trigger_attempt": put_trigger,
            "latest_close": float(latest['close']),
            "latest_vwap_low": float(latest['vwap_low']),
            "latest_vwap_high": float(latest['vwap_high']),
            "latest_vfi": float(latest['vfi'])
        })
        
        if not (call_trigger or put_trigger):
            decision_state["human_reason"] = "Conditions not aligned for VWAP band breakout"
            return None, decision_state
            
        if call_trigger:
            decision_state["human_reason"] = "Conditions met for CALL VWAP Band Breakout"
            signal = {
                "type": "CALL",
                "strategy": "VWAP_BAND_BREAKOUT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        if put_trigger:
            decision_state["human_reason"] = "Conditions met for PUT VWAP Band Breakout"
            signal = {
                "type": "PUT",
                "strategy": "VWAP_BAND_BREAKOUT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        return None, decision_state
