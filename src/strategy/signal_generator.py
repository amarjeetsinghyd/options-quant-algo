import pandas as pd
from dataclasses import dataclass, asdict
from typing import Dict, Any, List
from src.strategy.registry import STRATEGY_CONSTANTS

@dataclass
class RuleEvaluation:
    rule_id: str
    rule_category: str
    input_values: Dict[str, Any]
    threshold_values: Dict[str, Any]
    result: bool
    human_explanation: str

@dataclass
class StrategyEvaluation:
    strategy_name: str
    rule_evaluations: List[RuleEvaluation]
    overall_result: bool


class SignalGenerator:
    def __init__(self):
        pass

    def check_signal(self, df, generate_trace: bool = False):
        """
        10-Minute Window Breakout Strategy.
        Returns: (Signal_Dict, Decision_State_Dict)
        """
        params = STRATEGY_CONSTANTS["WINDOW_ALIGNMENT"]
        min_bars = params["min_data_bars"]
        lookback = params["crossover_lookup_window"]

        decision_state = {
            "human_reason": "Not enough data",
            "machine_state": {"bars": len(df)},
            "rule_evaluations": []
        }

        if len(df) < min_bars:
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S1_DATA_LENGTH",
                        rule_category="FILTER",
                        input_values={"bars": len(df)},
                        threshold_values={"min_bars": min_bars},
                        result=False,
                        human_explanation=f"Data length {len(df)} is less than required {min_bars} bars"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
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
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S1_DATA_LENGTH",
                        rule_category="FILTER",
                        input_values={"bars": len(df)},
                        threshold_values={"min_bars": min_bars},
                        result=True,
                        human_explanation=f"Data length {len(df)} >= required {min_bars} bars"
                    ),
                    RuleEvaluation(
                        rule_id="S1_TRIGGER_ALIGNMENT",
                        rule_category="TRIGGER",
                        input_values={
                            "call_aligned": call_aligned, "call_prev_aligned": call_prev_aligned,
                            "put_aligned": put_aligned, "put_prev_aligned": put_prev_aligned
                        },
                        threshold_values={},
                        result=False,
                        human_explanation="No bullish or bearish crossover crossover trigger detected on the current bar"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
            return None, decision_state
            
        shifted_close = df['close'].shift(1)
        shifted_vwap = df['vwap'].shift(1)
        
        if trigger_call:
            cross_up_mask = (df['close'] > df['vwap']) & (shifted_close <= shifted_vwap)
            cross_up_window = cross_up_mask.iloc[-lookback:]
            strategy_state["anchor_count"] = int(cross_up_window.sum())
            
            if not cross_up_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                strategy_state["anchor_found"] = False
                decision_state["human_reason"] = f"No bullish VWAP crossover anchor in last {lookback} minutes"
                strategy_state["reason_trace"].append(f"No bullish VWAP crossover anchor in last {lookback} minutes")
                if generate_trace:
                    rule_evals = [
                        RuleEvaluation(
                            rule_id="S1_DATA_LENGTH", rule_category="FILTER",
                            input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                            result=True, human_explanation="Data length meets criteria"
                        ),
                        RuleEvaluation(
                            rule_id="S1_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                            input_values={"trigger_call": True, "trigger_put": False}, threshold_values={},
                            result=True, human_explanation="Crossover trigger aligned for CALL"
                        ),
                        RuleEvaluation(
                            rule_id="S1_ANCHOR_CHECK", rule_category="TREND",
                            input_values={"crossovers_in_window": int(cross_up_window.sum())},
                            threshold_values={"lookback": lookback},
                            result=False, human_explanation=f"No VWAP crossover anchor bar found in the last {lookback} bars"
                        )
                    ]
                    decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
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
                if generate_trace:
                    rule_evals = [
                        RuleEvaluation(
                            rule_id="S1_DATA_LENGTH", rule_category="FILTER",
                            input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                            result=True, human_explanation="Data length meets criteria"
                        ),
                        RuleEvaluation(
                            rule_id="S1_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                            input_values={"trigger_call": True}, threshold_values={},
                            result=True, human_explanation="Crossover trigger aligned for CALL"
                        ),
                        RuleEvaluation(
                            rule_id="S1_ANCHOR_CHECK", rule_category="TREND",
                            input_values={"crossovers_in_window": int(cross_up_window.sum())},
                            threshold_values={"lookback": lookback},
                            result=True, human_explanation="VWAP crossover anchor bar verified"
                        ),
                        RuleEvaluation(
                            rule_id="S1_MOMENTUM_CHECK", rule_category="MOMENTUM",
                            input_values={"green_body": float(total_green_body), "red_body": float(total_red_body)},
                            threshold_values={},
                            result=False, human_explanation=f"Bullish real body sum ({total_green_body}) did not exceed bearish sum ({total_red_body})"
                        )
                    ]
                    decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            strategy_state["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for CALL breakout"
            strategy_state["reason_trace"].append("Conditions met for CALL breakout")
            
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S1_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=True, human_explanation="Data length meets criteria"
                    ),
                    RuleEvaluation(
                        rule_id="S1_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                        input_values={"trigger_call": True}, threshold_values={},
                        result=True, human_explanation="Crossover trigger aligned for CALL"
                    ),
                    RuleEvaluation(
                        rule_id="S1_ANCHOR_CHECK", rule_category="TREND",
                        input_values={"crossovers_in_window": int(cross_up_window.sum())},
                        threshold_values={"lookback": lookback},
                        result=True, human_explanation="VWAP crossover anchor bar verified"
                    ),
                    RuleEvaluation(
                        rule_id="S1_MOMENTUM_CHECK", rule_category="MOMENTUM",
                        input_values={"green_body": float(total_green_body), "red_body": float(total_red_body)},
                        threshold_values={},
                        result=True, human_explanation=f"Bullish real body sum ({total_green_body}) exceeds bearish sum ({total_red_body})"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]

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
            cross_dn_window = cross_dn_mask.iloc[-lookback:]
            strategy_state["anchor_count"] = int(cross_dn_window.sum())
            
            if not cross_dn_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                strategy_state["anchor_found"] = False
                decision_state["human_reason"] = f"No bearish VWAP crossover anchor in last {lookback} minutes"
                strategy_state["reason_trace"].append(f"No bearish VWAP crossover anchor in last {lookback} minutes")
                if generate_trace:
                    rule_evals = [
                        RuleEvaluation(
                            rule_id="S1_DATA_LENGTH", rule_category="FILTER",
                            input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                            result=True, human_explanation="Data length meets criteria"
                        ),
                        RuleEvaluation(
                            rule_id="S1_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                            input_values={"trigger_put": True}, threshold_values={},
                            result=True, human_explanation="Crossover trigger aligned for PUT"
                        ),
                        RuleEvaluation(
                            rule_id="S1_ANCHOR_CHECK", rule_category="TREND",
                            input_values={"crossovers_in_window": int(cross_dn_window.sum())},
                            threshold_values={"lookback": lookback},
                            result=False, human_explanation=f"No VWAP crossover anchor bar found in the last {lookback} bars"
                        )
                    ]
                    decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
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
                if generate_trace:
                    rule_evals = [
                        RuleEvaluation(
                            rule_id="S1_DATA_LENGTH", rule_category="FILTER",
                            input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                            result=True, human_explanation="Data length meets criteria"
                        ),
                        RuleEvaluation(
                            rule_id="S1_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                            input_values={"trigger_put": True}, threshold_values={},
                            result=True, human_explanation="Crossover trigger aligned for PUT"
                        ),
                        RuleEvaluation(
                            rule_id="S1_ANCHOR_CHECK", rule_category="TREND",
                            input_values={"crossovers_in_window": int(cross_dn_window.sum())},
                            threshold_values={"lookback": lookback},
                            result=True, human_explanation="VWAP crossover anchor bar verified"
                        ),
                        RuleEvaluation(
                            rule_id="S1_MOMENTUM_CHECK", rule_category="MOMENTUM",
                            input_values={"green_body": float(total_green_body), "red_body": float(total_red_body)},
                            threshold_values={},
                            result=False, human_explanation=f"Bearish real body sum ({total_red_body}) did not exceed bullish sum ({total_green_body})"
                        )
                    ]
                    decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            strategy_state["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for PUT breakout"
            strategy_state["reason_trace"].append("Conditions met for PUT breakout")
            
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S1_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=True, human_explanation="Data length meets criteria"
                    ),
                    RuleEvaluation(
                        rule_id="S1_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                        input_values={"trigger_put": True}, threshold_values={},
                        result=True, human_explanation="Crossover trigger aligned for PUT"
                    ),
                    RuleEvaluation(
                        rule_id="S1_ANCHOR_CHECK", rule_category="TREND",
                        input_values={"crossovers_in_window": int(cross_dn_window.sum())},
                        threshold_values={"lookback": lookback},
                        result=True, human_explanation="VWAP crossover anchor bar verified"
                    ),
                    RuleEvaluation(
                        rule_id="S1_MOMENTUM_CHECK", rule_category="MOMENTUM",
                        input_values={"green_body": float(total_green_body), "red_body": float(total_red_body)},
                        threshold_values={},
                        result=True, human_explanation=f"Bearish real body sum ({total_red_body}) exceeds bullish sum ({total_green_body})"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]

            signal = {
                "type": "PUT",
                "strategy": "WINDOW_ALIGNMENT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        return None, decision_state

    def check_rejection_signal(self, df, generate_trace: bool = False):
        """
        5-Minute Rejection Strategy.
        Returns: (Signal_Dict, Decision_State_Dict)
        """
        params = STRATEGY_CONSTANTS["REJECTION_WINDOW"]
        min_bars = params["min_data_bars"]
        lookback = params["rejection_lookup_window"]

        decision_state = {
            "human_reason": "Not enough data",
            "machine_state": {"bars": len(df)},
            "rule_evaluations": []
        }

        if len(df) < min_bars:
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S2_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=False, human_explanation=f"Data length {len(df)} is less than required {min_bars} bars"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
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
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S2_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=True, human_explanation="Data length meets criteria"
                    ),
                    RuleEvaluation(
                        rule_id="S2_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                        input_values={"close": float(latest['close']), "prev_close": float(prev['close']), "ema": float(latest['ema_9']), "vfi": float(latest['vfi']), "vfi_ema": latest_vfi_ema},
                        threshold_values={}, result=False, human_explanation="Price did not cross the 9 EMA or VFI momentum not aligned"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
            return None, decision_state
            
        call_anchor_mask = (df['low'] <= df['vwap']) & (df['close'] > df['vwap'])
        put_anchor_mask = (df['high'] >= df['vwap']) & (df['close'] < df['vwap'])
        
        if call_trigger:
            anchor_window = call_anchor_mask.iloc[-lookback:]
            strategy_state["anchor_count"] = int(anchor_window.sum())
            if not anchor_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                strategy_state["anchor_found"] = False
                decision_state["human_reason"] = f"No bullish rejection anchor in last {lookback} minutes"
                strategy_state["reason_trace"].append(f"No bullish rejection anchor in last {lookback} minutes")
                if generate_trace:
                    rule_evals = [
                        RuleEvaluation(
                            rule_id="S2_DATA_LENGTH", rule_category="FILTER",
                            input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                            result=True, human_explanation="Data length meets criteria"
                        ),
                        RuleEvaluation(
                            rule_id="S2_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                            input_values={"trigger_call": True}, threshold_values={},
                            result=True, human_explanation="EMA 9 crossover and VFI confirmed for CALL"
                        ),
                        RuleEvaluation(
                            rule_id="S2_ANCHOR_CHECK", rule_category="TREND",
                            input_values={"anchors_in_window": int(anchor_window.sum())},
                            threshold_values={"lookback": lookback},
                            result=False, human_explanation=f"No VWAP touch anchor low <= VWAP found in last {lookback} bars"
                        )
                    ]
                    decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
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
                if generate_trace:
                    rule_evals = [
                        RuleEvaluation(
                            rule_id="S2_DATA_LENGTH", rule_category="FILTER",
                            input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                            result=True, human_explanation="Data length meets criteria"
                        ),
                        RuleEvaluation(
                            rule_id="S2_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                            input_values={"trigger_call": True}, threshold_values={},
                            result=True, human_explanation="EMA 9 crossover and VFI confirmed for CALL"
                        ),
                        RuleEvaluation(
                            rule_id="S2_ANCHOR_CHECK", rule_category="TREND",
                            input_values={"anchors_in_window": int(anchor_window.sum())},
                            threshold_values={"lookback": lookback},
                            result=True, human_explanation="VWAP touch anchor verified"
                        ),
                        RuleEvaluation(
                            rule_id="S2_MOMENTUM_CHECK", rule_category="MOMENTUM",
                            input_values={"green_body": float(total_green_body), "red_body": float(total_red_body)},
                            threshold_values={},
                            result=False, human_explanation=f"Bullish real body sum ({total_green_body}) did not exceed bearish sum ({total_red_body})"
                        )
                    ]
                    decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            strategy_state["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for CALL rejection"
            strategy_state["reason_trace"].append("Conditions met for CALL rejection")
            
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S2_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=True, human_explanation="Data length meets criteria"
                    ),
                    RuleEvaluation(
                        rule_id="S2_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                        input_values={"trigger_call": True}, threshold_values={},
                        result=True, human_explanation="EMA 9 crossover and VFI confirmed for CALL"
                    ),
                    RuleEvaluation(
                        rule_id="S2_ANCHOR_CHECK", rule_category="TREND",
                        input_values={"anchors_in_window": int(anchor_window.sum())},
                        threshold_values={"lookback": lookback},
                        result=True, human_explanation="VWAP touch anchor verified"
                    ),
                    RuleEvaluation(
                        rule_id="S2_MOMENTUM_CHECK", rule_category="MOMENTUM",
                        input_values={"green_body": float(total_green_body), "red_body": float(total_red_body)},
                        threshold_values={},
                        result=True, human_explanation=f"Bullish real body sum ({total_green_body}) exceeds bearish sum ({total_red_body})"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]

            signal = {
                "type": "CALL",
                "strategy": "REJECTION_WINDOW",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        if put_trigger:
            anchor_window = put_anchor_mask.iloc[-lookback:]
            strategy_state["anchor_count"] = int(anchor_window.sum())
            if not anchor_window.any():
                decision_state["machine_state"]["anchor_found"] = False
                strategy_state["anchor_found"] = False
                decision_state["human_reason"] = f"No bearish rejection anchor in last {lookback} minutes"
                strategy_state["reason_trace"].append(f"No bearish rejection anchor in last {lookback} minutes")
                if generate_trace:
                    rule_evals = [
                        RuleEvaluation(
                            rule_id="S2_DATA_LENGTH", rule_category="FILTER",
                            input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                            result=True, human_explanation="Data length meets criteria"
                        ),
                        RuleEvaluation(
                            rule_id="S2_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                            input_values={"trigger_put": True}, threshold_values={},
                            result=True, human_explanation="EMA 9 crossover and VFI confirmed for PUT"
                        ),
                        RuleEvaluation(
                            rule_id="S2_ANCHOR_CHECK", rule_category="TREND",
                            input_values={"anchors_in_window": int(anchor_window.sum())},
                            threshold_values={"lookback": lookback},
                            result=False, human_explanation=f"No VWAP touch anchor high >= VWAP found in last {lookback} bars"
                        )
                    ]
                    decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
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
                if generate_trace:
                    rule_evals = [
                        RuleEvaluation(
                            rule_id="S2_DATA_LENGTH", rule_category="FILTER",
                            input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                            result=True, human_explanation="Data length meets criteria"
                        ),
                        RuleEvaluation(
                            rule_id="S2_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                            input_values={"trigger_put": True}, threshold_values={},
                            result=True, human_explanation="EMA 9 crossover and VFI confirmed for PUT"
                        ),
                        RuleEvaluation(
                            rule_id="S2_ANCHOR_CHECK", rule_category="TREND",
                            input_values={"anchors_in_window": int(anchor_window.sum())},
                            threshold_values={"lookback": lookback},
                            result=True, human_explanation="VWAP touch anchor verified"
                        ),
                        RuleEvaluation(
                            rule_id="S2_MOMENTUM_CHECK", rule_category="MOMENTUM",
                            input_values={"green_body": float(total_green_body), "red_body": float(total_red_body)},
                            threshold_values={},
                            result=False, human_explanation=f"Bearish real body sum ({total_red_body}) did not exceed bullish sum ({total_green_body})"
                        )
                    ]
                    decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
                return None, decision_state
                
            decision_state["machine_state"]["momentum_passed"] = True
            strategy_state["momentum_passed"] = True
            decision_state["human_reason"] = "Conditions met for PUT rejection"
            strategy_state["reason_trace"].append("Conditions met for PUT rejection")
            
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S2_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=True, human_explanation="Data length meets criteria"
                    ),
                    RuleEvaluation(
                        rule_id="S2_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                        input_values={"trigger_put": True}, threshold_values={},
                        result=True, human_explanation="EMA 9 crossover and VFI confirmed for PUT"
                    ),
                    RuleEvaluation(
                        rule_id="S2_ANCHOR_CHECK", rule_category="TREND",
                        input_values={"anchors_in_window": int(anchor_window.sum())},
                        threshold_values={"lookback": lookback},
                        result=True, human_explanation="VWAP touch anchor verified"
                    ),
                    RuleEvaluation(
                        rule_id="S2_MOMENTUM_CHECK", rule_category="MOMENTUM",
                        input_values={"green_body": float(total_green_body), "red_body": float(total_red_body)},
                        threshold_values={},
                        result=True, human_explanation=f"Bearish real body sum ({total_red_body}) exceeds bullish sum ({total_green_body})"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]

            signal = {
                "type": "PUT",
                "strategy": "REJECTION_WINDOW",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        return None, decision_state



    def check_vwap_band_breakout_signal(self, df, generate_trace: bool = False):
        """
        VWAP Band Breakout Strategy (Strategy 3).
        CALL: Price crosses above vwap_low AND vfi > 0.
        PUT: Price crosses below vwap_high AND vfi < 0.
        """
        params = STRATEGY_CONSTANTS["VWAP_BAND_BREAKOUT"]
        min_bars = params["min_data_bars"]
        ratio = params["band_proximity_ratio"]
 
        decision_state = {
            "human_reason": "Not enough data",
            "machine_state": {"bars": len(df)},
            "rule_evaluations": []
        }

        if len(df) < min_bars:
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S3_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=False, human_explanation=f"Data length {len(df)} is less than required {min_bars} bars"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
            return None, decision_state
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        call_required_close = latest['vwap_low'] + ratio * (latest['vwap'] - latest['vwap_low'])
        prev_below_vwap_low = prev['close'] <= latest['vwap_low']
        vfi_positive = latest['vfi'] > 0
        call_trigger = bool(
            latest['close'] >= call_required_close and 
            prev_below_vwap_low and 
            vfi_positive
        )
        
        put_required_close = latest['vwap_high'] - ratio * (latest['vwap_high'] - latest['vwap'])
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
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S3_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=True, human_explanation="Data length meets criteria"
                    ),
                    RuleEvaluation(
                        rule_id="S3_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                        input_values={
                            "close": float(latest['close']), "prev_close": float(prev['close']),
                            "vwap_low": float(latest['vwap_low']), "vwap_high": float(latest['vwap_high']),
                            "vfi": float(latest['vfi'])
                        },
                        threshold_values={"ratio": ratio},
                        result=False, human_explanation="VWAP SD-band boundary close breakout conditions not met"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]
            return None, decision_state
            
        if call_trigger:
            decision_state["human_reason"] = "Conditions met for CALL VWAP Band Breakout"
            strategy_state["reason_trace"].append("Conditions met for CALL VWAP Band Breakout")
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S3_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=True, human_explanation="Data length meets criteria"
                    ),
                    RuleEvaluation(
                        rule_id="S3_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                        input_values={
                            "close": float(latest['close']), "prev_close": float(prev['close']),
                            "vwap_low": float(latest['vwap_low']), "vfi": float(latest['vfi'])
                        },
                        threshold_values={"ratio": ratio},
                        result=True, human_explanation="Price breakout past inner SD VWAP-low band confirmed with positive VFI flow"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]

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
            if generate_trace:
                rule_evals = [
                    RuleEvaluation(
                        rule_id="S3_DATA_LENGTH", rule_category="FILTER",
                        input_values={"bars": len(df)}, threshold_values={"min_bars": min_bars},
                        result=True, human_explanation="Data length meets criteria"
                    ),
                    RuleEvaluation(
                        rule_id="S3_TRIGGER_ALIGNMENT", rule_category="TRIGGER",
                        input_values={
                            "close": float(latest['close']), "prev_close": float(prev['close']),
                            "vwap_high": float(latest['vwap_high']), "vfi": float(latest['vfi'])
                        },
                        threshold_values={"ratio": ratio},
                        result=True, human_explanation="Price breakout past inner SD VWAP-high band confirmed with negative VFI flow"
                    )
                ]
                decision_state["rule_evaluations"] = [asdict(r) for r in rule_evals]

            signal = {
                "type": "PUT",
                "strategy": "VWAP_BAND_BREAKOUT",
                "master_high": float(latest['high']),
                "master_low": float(latest['low']),
                "timestamp": latest['timestamp'].isoformat() if hasattr(latest['timestamp'], 'isoformat') else str(latest['timestamp'])
            }
            return signal, decision_state
            
        return None, decision_state
