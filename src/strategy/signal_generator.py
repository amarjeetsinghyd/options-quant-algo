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
        
        strategy_state = {
            "bars": len(df),
            "call_aligned": call_aligned,
            "call_prev_aligned": call_prev_aligned,
            "put_aligned": put_aligned,
            "put_prev_aligned": put_prev_aligned,
            "trigger_call": trigger_call,
            "trigger_put": trigger_put,
            "latest_close": float(latest['close']),
            "latest_ema_9": float(latest['ema_9']),
            "latest_vwap": float(latest['vwap']),
            "latest_vfi": float(latest['vfi']),
            "reason_trace": []
        }
        decision_state["machine_state"].update(strategy_state)
        decision_state["machine_state"]["strategy_1_state"] = strategy_state
        
        if not (trigger_call or trigger_put):
            decision_state["human_reason"] = "Conditions not aligned for trigger"
            strategy_state["reason_trace"].append(
                f"trigger_call={trigger_call}, trigger_put={trigger_put}, call_aligned={call_aligned}, put_aligned={put_aligned}"
            )
            return None, decision_state
            
        shifted_close = df['close'].shift(1)
        shifted_vwap = df['vwap'].shift(1)
        
        if trigger_call:
            cross_up_mask = (df['close'] > df['vwap']) & (shifted_close <= shifted_vwap)
            cross_up_window = cross_up_mask.iloc[-10:]
            strategy_state["anchor_count"] = int(cross_up_window.sum())
            
            if not cross_up_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                strategy_state["anchor_found"] = False
                decision_state["human_reason"] = "No bullish VWAP crossover anchor in last 10 minutes"
                strategy_state["reason_trace"].append("No bullish VWAP crossover anchor in last 10 minutes")
                return None, decision_state
                
            decision_state["machine_state"]["anchor_found"] = True
            strategy_state["anchor_found"] = True
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
            strategy_state["total_green_body"] = float(total_green_body)
            strategy_state["total_red_body"] = float(total_red_body)
            
            if total_green_body <= total_red_body:
                decision_state["machine_state"]["momentum_passed"] = False
                strategy_state["momentum_passed"] = False
                decision_state["human_reason"] = "Failed momentum check: Red bodies dominated"
                strategy_state["reason_trace"].append("Failed momentum check: Red bodies dominated")
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            strategy_state["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for CALL breakout"
            strategy_state["reason_trace"].append("Conditions met for CALL breakout")
            
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
            strategy_state["anchor_count"] = int(cross_dn_window.sum())
            
            if not cross_dn_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                strategy_state["anchor_found"] = False
                decision_state["human_reason"] = "No bearish VWAP crossover anchor in last 10 minutes"
                strategy_state["reason_trace"].append("No bearish VWAP crossover anchor in last 10 minutes")
                return None, decision_state
                
            decision_state["machine_state"]["anchor_found"] = True
            strategy_state["anchor_found"] = True
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
            strategy_state["total_green_body"] = float(total_green_body)
            strategy_state["total_red_body"] = float(total_red_body)
            
            if total_red_body <= total_green_body:
                decision_state["machine_state"]["momentum_passed"] = False
                strategy_state["momentum_passed"] = False
                decision_state["human_reason"] = "Failed momentum check: Green bodies dominated"
                strategy_state["reason_trace"].append("Failed momentum check: Green bodies dominated")
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            strategy_state["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for PUT breakout"
            strategy_state["reason_trace"].append("Conditions met for PUT breakout")
            
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
        latest_vfi_ema = float(latest.get('vfi_ema', latest['vfi']))
        
        call_trigger = bool(
            latest['close'] > latest['ema_9'] and
            prev['close'] <= prev['ema_9'] and
            latest['vfi'] > 0 and
            latest['vfi'] > latest_vfi_ema
        )
        put_trigger = bool(
            latest['close'] < latest['ema_9'] and
            prev['close'] >= prev['ema_9'] and
            latest['vfi'] < 0 and
            latest['vfi'] < latest_vfi_ema
        )
        
        strategy_state = {
            "bars": len(df),
            "call_trigger": call_trigger,
            "put_trigger": put_trigger,
            "latest_close": float(latest['close']),
            "latest_ema_9": float(latest['ema_9']),
            "latest_vwap": float(latest['vwap']),
            "latest_vfi": float(latest['vfi']),
            "latest_vfi_ema": latest_vfi_ema,
            "reason_trace": []
        }
        decision_state["machine_state"].update(strategy_state)
        decision_state["machine_state"]["strategy_2_state"] = strategy_state
        
        if not (call_trigger or put_trigger):
            decision_state["human_reason"] = "Conditions not aligned for rejection trigger"
            strategy_state["reason_trace"].append(
                f"call_trigger={call_trigger}, put_trigger={put_trigger}, latest_vfi={latest['vfi']}, latest_vfi_ema={latest_vfi_ema}"
            )
            return None, decision_state
            
        call_anchor_mask = (df['low'] <= df['vwap']) & (df['close'] > df['vwap'])
        put_anchor_mask = (df['high'] >= df['vwap']) & (df['close'] < df['vwap'])
        
        if call_trigger:
            anchor_window = call_anchor_mask.iloc[-5:]
            strategy_state["anchor_count"] = int(anchor_window.sum())
            if not anchor_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                strategy_state["anchor_found"] = False
                decision_state["human_reason"] = "No bullish rejection anchor in last 5 minutes"
                strategy_state["reason_trace"].append("No bullish rejection anchor in last 5 minutes")
                return None, decision_state
                
            decision_state["machine_state"]["anchor_found"] = True
            strategy_state["anchor_found"] = True
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
            strategy_state["total_green_body"] = float(total_green_body)
            strategy_state["total_red_body"] = float(total_red_body)
            
            if total_green_body <= total_red_body:
                decision_state["machine_state"]["momentum_passed"] = False
                strategy_state["momentum_passed"] = False
                decision_state["human_reason"] = "Failed momentum check: Red bodies dominated"
                strategy_state["reason_trace"].append("Failed momentum check: Red bodies dominated")
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            strategy_state["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for CALL rejection"
            strategy_state["reason_trace"].append("Conditions met for CALL rejection")
            
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
            strategy_state["anchor_count"] = int(anchor_window.sum())
            if not anchor_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                strategy_state["anchor_found"] = False
                decision_state["human_reason"] = "No bearish rejection anchor in last 5 minutes"
                strategy_state["reason_trace"].append("No bearish rejection anchor in last 5 minutes")
                return None, decision_state
                
            decision_state["machine_state"]["anchor_found"] = True
            strategy_state["anchor_found"] = True
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
            strategy_state["total_green_body"] = float(total_green_body)
            strategy_state["total_red_body"] = float(total_red_body)
            
            if total_red_body <= total_green_body:
                decision_state["machine_state"]["momentum_passed"] = False
                strategy_state["momentum_passed"] = False
                decision_state["human_reason"] = "Failed momentum check: Green bodies dominated"
                strategy_state["reason_trace"].append("Failed momentum check: Green bodies dominated")
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            strategy_state["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for PUT rejection"
            strategy_state["reason_trace"].append("Conditions met for PUT rejection")
            
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
        
        call_required_close = latest['vwap_low'] + 0.30 * (latest['vwap'] - latest['vwap_low'])
        prev_below_vwap_low = prev['close'] <= latest['vwap_low']
        vfi_positive = latest['vfi'] > 0
        call_trigger = bool(
            latest['close'] >= call_required_close and 
            prev_below_vwap_low and 
            vfi_positive
        )
        
        put_required_close = latest['vwap_high'] - 0.30 * (latest['vwap_high'] - latest['vwap'])
        prev_above_vwap_high = prev['close'] >= latest['vwap_high']
        vfi_negative = latest['vfi'] < 0
        put_trigger = bool(
            latest['close'] <= put_required_close and 
            prev_above_vwap_high and 
            vfi_negative
        )
        
        strategy_state = {
            "bars": len(df),
            "call_trigger_attempt": call_trigger,
            "put_trigger_attempt": put_trigger,
            "latest_close": float(latest['close']),
            "latest_vwap_low": float(latest['vwap_low']),
            "latest_vwap_high": float(latest['vwap_high']),
            "latest_vfi": float(latest['vfi']),
            "call_required_close": float(call_required_close),
            "put_required_close": float(put_required_close),
            "prev_below_vwap_low": prev_below_vwap_low,
            "prev_above_vwap_high": prev_above_vwap_high,
            "vfi_positive": vfi_positive,
            "vfi_negative": vfi_negative,
            "reason_trace": []
        }
        decision_state["machine_state"].update(strategy_state)
        decision_state["machine_state"]["strategy_3_state"] = strategy_state
        
        if not (call_trigger or put_trigger):
            decision_state["human_reason"] = "Conditions not aligned for VWAP band breakout"
            if not call_trigger:
                strategy_state["reason_trace"].append(
                    f"CALL fail: close={latest['close']} < required={call_required_close} or prev_above_vwap_low={not prev_below_vwap_low} or vfi_positive={vfi_positive}"
                )
            if not put_trigger:
                strategy_state["reason_trace"].append(
                    f"PUT fail: close={latest['close']} > required={put_required_close} or prev_above_vwap_high={not prev_above_vwap_high} or vfi_negative={vfi_negative}"
                )
            return None, decision_state
            
        if call_trigger:
            decision_state["human_reason"] = "Conditions met for CALL VWAP Band Breakout"
            strategy_state["reason_trace"].append("Conditions met for CALL VWAP Band Breakout")
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
            strategy_state["reason_trace"].append("Conditions met for PUT VWAP Band Breakout")
            signal = {
                "type": "PUT",
                "strategy": "VWAP_BAND_BREAKOUT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        return None, decision_state
