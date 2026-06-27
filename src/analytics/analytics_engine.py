import sqlite3
import pandas as pd
import time
import os
import numpy as np


from src.utils.logger import get_logger
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import ML_STRIKE_DB_PATH, STRIKE_STRIKE_DB_PATH

logger = get_logger("analytics")

class AnalyticsEngine:
    def __init__(self):
        self._cache = None
        self._cache_time = 0
        self.CACHE_TTL = 15  # 15 seconds caching

    def _get_data(self):
        if not os.path.exists(STRIKE_DB_PATH):
            return pd.DataFrame()
            
        now = time.time()
        if self._cache is not None and (now - self._cache_time) < self.CACHE_TTL:
            return self._cache
            
        conn = get_db_connection(STRIKE_DB_PATH)
        try:
            df = pd.read_sql_query("""
                SELECT
                    st.*,
                    ss.signal_type, ss.strategy, ss.signal_timestamp, ss.time_of_day_bucket,
                    ss.signal_category, ss.rejection_reason, ss.rejection_stage, ss.filter_name,
                    ss.virtual_tracking_completed, ss.vwap_distance_pct, ss.vfi_strength, ss.index_volatility,
                    ss.market_regime, ss.atr_expansion_ratio, ss.ema_vwap_distance, ss.candle_body_avg,
                    ss.net_candle_energy, ss.vfi_price_alignment, ss.trade_quality_score
                FROM strike_tracking st
                JOIN signal_snapshots ss ON st.signal_id = ss.signal_id
                WHERE st.entry_premium > 0 AND ss.virtual_tracking_completed = 1
            """, conn)
            
            if not df.empty:
                def _pct_bucket(premium):
                    if premium < 20: return "₹10-20"
                    elif premium < 40: return "₹20-40"
                    elif premium < 70: return "₹40-70"
                    elif premium < 100: return "₹70-100"
                    else: return "₹100+"
                    df['premium_bucket'] = df['entry_premium'].apply(_pct_bucket)
                df['premium_bucket'] = df['entry_premium'].apply(_pct_bucket)
                self._cache = df
                self._cache_time = now
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            df = pd.DataFrame()
        finally:
            conn.close()
            
        return df

    def clear_cache(self):
        self._cache = None

    def get_overview(self):
        df = self._get_data()
        if df.empty:
            return {"total_signals": 0}
            
        signals_df = df.drop_duplicates(subset=['signal_id'])
        total_signals = len(signals_df)
        executed = len(signals_df[signals_df['signal_category'] == 'EXECUTED'])
        rejected = len(signals_df[signals_df['signal_category'] == 'REJECTED'])
        
        exec_rate = (executed / total_signals * 100) if total_signals > 0 else 0
        
        executed_df = df[df['signal_category'] == 'EXECUTED']
        hits = 0
        avg_time = 0
        median_time = 0
        fastest_time = 0
        avg_adverse = 0
        
        if not executed_df.empty:
            best_strikes = executed_df.loc[executed_df.groupby('signal_id')['max_favorable_pct'].idxmax()]
            hits = best_strikes['hit_target'].sum()
            avg_time = best_strikes[best_strikes['hit_target'] == 1]['time_to_target_sec'].mean()
            median_time = best_strikes[best_strikes['hit_target'] == 1]['time_to_target_sec'].median()
            fastest_time = best_strikes[best_strikes['hit_target'] == 1]['time_to_target_sec'].min()
            avg_adverse = best_strikes['max_adverse_pct'].mean()
            
        success_rate = (hits / executed * 100) if executed > 0 else 0

        best_strategy = "N/A"
        if not executed_df.empty:
            strat_group = executed_df.groupby('strategy')['hit_target'].mean()
            if not strat_group.empty:
                best_strategy = strat_group.idxmax()

        return {
            "total_signals": int(total_signals),
            "executed": int(executed),
            "rejected": int(rejected),
            "execution_quality_pct": round(exec_rate, 1),
            "overall_success_rate": round(success_rate, 1),
            "avg_target_time": round(float(avg_time) if pd.notnull(avg_time) else 0, 1),
            "median_target_time": round(float(median_time) if pd.notnull(median_time) else 0, 1),
            "fastest_time": round(float(fastest_time) if pd.notnull(fastest_time) else 0, 1),
            "avg_adverse_movement": round(float(avg_adverse) if pd.notnull(avg_adverse) else 0, 1),
            "best_setup": str(best_strategy)
        }

    def get_strategy_intelligence(self):
        df = self._get_data()
        if df.empty: return []
        
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return []
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        res = []
        for strategy, group in best_strikes.groupby('strategy'):
            total = len(group)
            hits = group['hit_target'].sum()
            avg_time = group[group['hit_target'] == 1]['time_to_target_sec'].mean()
            avg_drawdown = group['max_adverse_pct'].mean()
            
            res.append({
                "strategy": strategy,
                "occurrences": int(total),
                "target_hit_pct": round((hits / total) * 100, 1) if total > 0 else 0,
                "avg_time": round(avg_time, 1) if hits > 0 else 0,
                "avg_drawdown": round(avg_drawdown, 1) if not pd.isna(avg_drawdown) else 0,
                "failure_pct": round((1 - hits/total) * 100, 1) if total > 0 else 0
            })
        return res

    def get_strike_intelligence(self):
        df = self._get_data()
        if df.empty: return {"strikes": [], "recommendation": "Not enough data"}
        
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {"strikes": [], "recommendation": "Not enough data"}
        
        res = []
        best_score = -999
        recommended = "ATM"
        for distance, group in df_exec.groupby('distance_from_atm'):
            name = "ATM" if distance == 0 else f"{int(distance)} OTM"
            total = len(group)
            hits = group['hit_target'].sum()
            avg_time = group[group['hit_target'] == 1]['time_to_target_sec'].mean()
            median_time = group[group['hit_target'] == 1]['time_to_target_sec'].median()
            avg_score = group['strike_efficiency_score'].mean()
            
            res.append({
                "name": name,
                "observations": int(total),
                "hit_pct": round((hits / total * 100), 1) if total > 0 else 0,
                "median_time": round(median_time, 1) if hits > 0 else 0,
                "max_favorable": round(group['max_favorable_pct'].mean(), 1),
                "max_adverse": round(group['max_adverse_pct'].mean(), 1),
                "liquidity_drop": round(group['liquidity_drop_pct'].mean(), 1),
                "spread_pct": round(group['spread_pct'].mean(), 1),
                "efficiency_score": round(avg_score, 1)
            })
            if avg_score > best_score:
                best_score = avg_score
                recommended = name
                
        return {"strikes": res, "recommendation": f"Based on last signals, {recommended} is optimal"}

    def get_premium_intelligence(self):
        df = self._get_data()
        if df.empty: return []
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return []
        
        res = []
        for bucket, group in df_exec.groupby('premium_bucket'):
            total = len(group)
            hits = group['hit_target'].sum()
            speed = group[group['hit_target']==1]['time_to_target_sec'].mean()
            res.append({
                "bucket": bucket,
                "win_pct": round(hits/total*100, 1) if total > 0 else 0,
                "speed_sec": round(speed, 1) if hits > 0 else 0,
                "slippage": round(group['entry_slippage_est'].mean(), 1),
                "gamma_adv": round(group['strike_efficiency_score'].mean(), 1)
            })
        return res

    def get_time_intelligence(self):
        df = self._get_data()
        if df.empty: return {"distribution": {}, "decay": []}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {"distribution": {}, "decay": []}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        distribution = {"0-30s": 0, "30-60s": 0, "60-120s": 0, "120-180s": 0, "Failed": 0}
        for _, row in best_strikes.iterrows():
            if not row['hit_target']:
                distribution["Failed"] += 1
            else:
                t = row['time_to_target_sec']
                if pd.isna(t): continue
                if t <= 30: distribution["0-30s"] += 1
                elif t <= 60: distribution["30-60s"] += 1
                elif t <= 120: distribution["60-120s"] += 1
                else: distribution["120-180s"] += 1
                
        decay = []
        for t in [30, 60, 120, 180]:
            col = f'return_pct_{t}s'
            if col in best_strikes.columns:
                decay.append({"time": f"{t}s", "avg_return": round(best_strikes[col].mean(), 1)})
                
        return {"distribution": distribution, "decay": decay}

    def get_filter_intelligence(self):
        df = self._get_data()
        if df.empty: return []
        df_rej = df[df['signal_category'] == 'REJECTED']
        if df_rej.empty: return []
        
        signal_perf = df_rej.groupby('signal_id').agg(
            filter_name=('filter_name', 'first'),
            any_valid_hit=('target_hit_while_valid', 'max'),
            avg_missed=('max_favorable_pct', 'max')
        ).reset_index()
        
        res = []
        for f_name, group in signal_perf.groupby('filter_name'):
            total = len(group)
            false_rej = int(group['any_valid_hit'].sum())
            correct = total - false_rej
            protection = (correct / total * 100) if total > 0 else 0
            avg_missed = group['avg_missed'].mean()
            res.append({
                "filter": str(f_name),
                "total_rejected": total,
                "correct_rejected": correct,
                "false_rejected": false_rej,
                "protection_pct": round(protection, 1),
                "opportunity_loss_pct": round(avg_missed, 1) if not pd.isna(avg_missed) else 0
            })
        return res

    def get_order_flow_intelligence(self):
        df = self._get_data()
        if df.empty: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {}
        
        if 'buyer_aggression_score' not in df_exec.columns:
            return {"error": "OFA columns missing"}
            
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        positive_ofa = best_strikes[best_strikes['order_flow_strength'] > 0]
        negative_ofa = best_strikes[best_strikes['order_flow_strength'] <= 0]
        
        pos_win = positive_ofa['hit_target'].sum() / len(positive_ofa) * 100 if len(positive_ofa) > 0 else 0
        neg_fail = (len(negative_ofa) - negative_ofa['hit_target'].sum()) / len(negative_ofa) * 100 if len(negative_ofa) > 0 else 0
        
        return {
            "ofa_positive_success": round(pos_win, 1),
            "ofa_negative_failure_confirm": round(neg_fail, 1),
            "avg_buyer_aggression": round(best_strikes['buyer_aggression_score'].mean(), 1),
            "avg_seller_aggression": round(best_strikes['seller_aggression_score'].mean(), 1)
        }

    def get_execution_intelligence(self):
        df = self._get_data()
        if df.empty: return []
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return []
        
        res = []
        for dist, group in df_exec.groupby('distance_from_atm'):
            name = "ATM" if dist == 0 else f"{int(dist)} OTM"
            res.append({
                "strike": name,
                "avg_spread": round(group['avg_spread_during_trade'].mean(), 2),
                "est_entry_slippage": round(group['entry_slippage_est'].mean(), 2),
                "est_exit_slippage": round(group['exit_slippage_est'].mean(), 2),
                "net_return": round(group['net_after_friction'].mean(), 2)
            })
        return res
        
    def get_scaling_intelligence(self):
        df = self._get_data()
        if df.empty: return []
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return []
        
        res = []
        for dist, group in df_exec.groupby('distance_from_atm'):
            name = "ATM" if dist == 0 else f"{int(dist)} OTM"
            avg_min_bid = group['min_bid_qty'].mean()
            safe_lots = int(avg_min_bid * 0.1) if not pd.isna(avg_min_bid) else 0
            
            res.append({
                "strike": name,
                "avg_min_liquidity": int(avg_min_bid) if not pd.isna(avg_min_bid) else 0,
                "safe_lots": safe_lots
            })
        return res

    def get_market_intelligence(self):
        df = self._get_data()
        if df.empty: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        windows = []
        for tod, group in best_strikes.groupby('time_of_day_bucket'):
            total = len(group)
            hits = group['hit_target'].sum()
            windows.append({
                "window": str(tod),
                "success_pct": round(hits/total*100, 1) if total>0 else 0
            })
            
        best_window = max(windows, key=lambda x: x['success_pct'])['window'] if windows else "N/A"
        
        return {
            "windows": windows,
            "best_window": best_window,
            "avg_vwap_dist": round(best_strikes['vwap_distance_pct'].mean(), 2),
            "avg_vfi": round(best_strikes['vfi_strength'].mean(), 2)
        }

    def get_machine_insights(self):
        over = self.get_overview()
        strike = self.get_strike_intelligence()
        filters = self.get_filter_intelligence()
        
        insights = [
            f"The system has analyzed {over.get('total_signals', 0)} signals historically.",
        ]
        
        if over.get('executed', 0) > 0:
            insights.append(f"The execution edge stands at a {over.get('overall_success_rate', 0)}% success rate overall.")
            
        if strike.get("recommendation") and strike.get("recommendation") != "Not enough data":
            insights.append(strike["recommendation"] + " for fastest target achievement.")
            
        if filters:
            for f in filters:
                insights.append(f"The {f['filter']} filter protected capital {f['protection_pct']}% of the time when triggered.")
                if f['false_rejected'] > 0 and f['protection_pct'] < 70:
                    insights.append(f"WARNING: The {f['filter']} filter is too aggressive, blocking {f['false_rejected']} winning setups.")
        
        return insights

    # =========================================================================
    # Phase 4.1 Advanced Analytics
    # =========================================================================

    def get_ofa_health(self):
        df = self._get_data()
        if df.empty: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty or 'ofa_decay_rate' not in df_exec.columns: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        trends = []
        for trend, group in best_strikes.groupby('ofa_trend'):
            trends.append({
                "trend": str(trend),
                "count": len(group),
                "win_rate": round(group['hit_target'].mean() * 100, 1),
                "avg_decay": round(group['ofa_decay_rate'].mean(), 2)
            })
            
        return {
            "avg_consistency": round(best_strikes['ofa_consistency_score'].mean(), 1),
            "trends": trends
        }

    def get_target_optimization(self):
        df = self._get_data()
        if df.empty: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty or 'target_5_hit' not in df_exec.columns: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        total = len(best_strikes)
        
        def safe_mean(series):
            return round(series.mean(), 1) if not series.empty and not pd.isna(series.mean()) else 0
            
        return {
            "target_5": {
                "hit_rate": round(best_strikes['target_5_hit'].mean() * 100, 1),
                "avg_time": safe_mean(best_strikes[best_strikes['target_5_hit'] == 1]['target_5_hit_time'])
            },
            "target_10": {
                "hit_rate": round(best_strikes['hit_target'].mean() * 100, 1),
                "avg_time": safe_mean(best_strikes[best_strikes['hit_target'] == 1]['time_to_target_sec'])
            },
            "target_15": {
                "hit_rate": round(best_strikes['target_15_hit'].mean() * 100, 1),
                "avg_time": safe_mean(best_strikes[best_strikes['target_15_hit'] == 1]['target_15_hit_time'])
            },
            "target_20": {
                "hit_rate": round(best_strikes['target_20_hit'].mean() * 100, 1),
                "avg_time": safe_mean(best_strikes[best_strikes['target_20_hit'] == 1]['target_20_hit_time'])
            },
            "post_target_runner": round(best_strikes['post_target_max_gain'].mean(), 1) if 'post_target_max_gain' in best_strikes.columns else 0.0
        }

    def get_failure_dna(self):
        df = self._get_data()
        if df.empty: return {}
        df_fails = df[(df['signal_category'] == 'EXECUTED') & (df['hit_target'] == 0)]
        if df_fails.empty or 'maximum_profit_before_failure' not in df_fails.columns: return {}
        
        best_fails = df_fails.loc[df_fails.groupby('signal_id')['maximum_profit_before_failure'].idxmax()]
        
        return {
            "total_failures": len(best_fails),
            "avg_max_profit_before_fail": round(best_fails['maximum_profit_before_failure'].mean(), 1),
            "avg_time_before_fail": round(best_fails['time_before_failure'].mean(), 1),
            "failed_after_positive_move_pct": round(best_fails['failed_after_positive_move'].mean() * 100, 1)
        }

    def get_vfi_edge(self):
        df = self._get_data()
        if df.empty: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty or 'vfi_normalized_strength' not in df_exec.columns: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        # Categorize normalized VFI
        strong = best_strikes[best_strikes['vfi_normalized_strength'] > 1.5]
        normal = best_strikes[(best_strikes['vfi_normalized_strength'] <= 1.5) & (best_strikes['vfi_normalized_strength'] > 0.5)]
        weak = best_strikes[best_strikes['vfi_normalized_strength'] <= 0.5]
        
        def safe_win(group):
            return round(group['hit_target'].mean() * 100, 1) if len(group) > 0 else 0
            
        return {
            "strong_cross_win_rate": safe_win(strong),
            "normal_cross_win_rate": safe_win(normal),
            "weak_cross_win_rate": safe_win(weak),
            "avg_vfi_angle": round(best_strikes['vfi_angle'].mean(), 2)
        }

    # =========================================================================
    # Phase 4.2 Intelligence Lab Reliability
    # =========================================================================

    def get_research_confidence(self):
        df = self._get_data()
        if df.empty:
            return {
                "signals": 0, "executed": 0, "rejected": 0, 
                "confidence_level": "NO DATA", 
                "message": "Collecting early behaviour data. No signals recorded yet."
            }
            
        signals = len(df['signal_id'].unique())
        executed = len(df[df['signal_category'] == 'EXECUTED']['signal_id'].unique())
        rejected = len(df[df['signal_category'] == 'REJECTED']['signal_id'].unique())
        
        if signals < 100:
            level = "LOW CONFIDENCE"
            msg = "Collecting early behaviour data. Avoid optimizing strategy yet."
        elif signals < 300:
            level = "MEDIUM CONFIDENCE"
            msg = "Patterns emerging. Validate before changing execution rules."
        else:
            level = "HIGH CONFIDENCE"
            msg = "Large enough sample available for deeper optimization."
            
        return {
            "signals": signals,
            "executed": executed,
            "rejected": rejected,
            "confidence_level": level,
            "message": msg
        }

    def get_database_freshness(self):
        df = self._get_data()
        if df.empty:
            return {
                "last_updated": "N/A",
                "last_signal_time": "N/A",
                "last_signal_type": "N/A"
            }
            
        try:
            last_sig = df.sort_values('timestamp', ascending=False).iloc[0]
            cat = str(last_sig['signal_category'])
            f_name = str(last_sig.get('filter_name', ''))
            
            sig_type = f"{cat} - {f_name}" if f_name and f_name != 'nan' else cat
            
            # Read file modification time of DB
            mtime = os.path.getmtime(STRIKE_DB_PATH)
            mtime_str = pd.to_datetime(mtime, unit='s').strftime("%Y-%m-%d %H:%M:%S")
            
            return {
                "last_updated": mtime_str,
                "last_signal_time": str(last_sig['timestamp']),
                "last_signal_type": sig_type
            }
        except Exception as e:
            return {
                "last_updated": "Error",
                "last_signal_time": "Error",
                "last_signal_type": str(e)
            }


    # =========================================================================
    # Phase 4.3 Market Regime Intelligence
    # =========================================================================

    def get_market_regime_intelligence(self):
        df = self._get_data()
        if df.empty or 'market_regime' not in df.columns: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        regimes = []
        for regime, group in best_strikes.groupby('market_regime'):
            regimes.append({
                "regime": str(regime),
                "count": len(group),
                "hit_rate": round(group['hit_target'].mean() * 100, 1)
            })
            
        best_regime = max(regimes, key=lambda x: x['hit_rate']) if regimes else {"regime": "N/A", "hit_rate": 0}
        worst_regime = min(regimes, key=lambda x: x['hit_rate']) if regimes else {"regime": "N/A", "hit_rate": 0}
        
        return {
            "regimes": regimes,
            "best_regime": best_regime,
            "worst_regime": worst_regime
        }

    def get_atr_intelligence(self):
        df = self._get_data()
        if df.empty or 'atr_expansion_ratio' not in df.columns: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        def safe_mean(cond):
            g = best_strikes[cond]
            return round(g['hit_target'].mean() * 100, 1) if len(g) > 0 else 0
            
        return {
            "expanding_hit_rate": safe_mean(best_strikes['atr_expansion_ratio'] > 1.3),
            "normal_hit_rate": safe_mean((best_strikes['atr_expansion_ratio'] <= 1.3) & (best_strikes['atr_expansion_ratio'] >= 0.8)),
            "compressed_hit_rate": safe_mean(best_strikes['atr_expansion_ratio'] < 0.8)
        }

    def get_vwap_health(self):
        df = self._get_data()
        if df.empty or 'ema_vwap_distance' not in df.columns: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        distances = best_strikes.copy()
        distances['dist_pct'] = (distances['ema_vwap_distance'].abs() / distances['index_price']) * 100
        
        zones = []
        # Group by 0.05% buckets roughly
        labels = ["0-0.05%", "0.05-0.10%", "0.10-0.15%", ">0.15%"]
        conditions = [
            distances['dist_pct'] <= 0.05,
            (distances['dist_pct'] > 0.05) & (distances['dist_pct'] <= 0.10),
            (distances['dist_pct'] > 0.10) & (distances['dist_pct'] <= 0.15),
            distances['dist_pct'] > 0.15
        ]
        
        for label, cond in zip(labels, conditions):
            group = distances[cond]
            zones.append({
                "zone": label,
                "count": len(group),
                "hit_rate": round(group['hit_target'].mean() * 100, 1) if len(group) > 0 else 0
            })
            
        best_zone = max(zones, key=lambda x: x['hit_rate']) if zones else {"zone": "N/A"}
        
        return {
            "zones": zones,
            "best_zone": best_zone['zone']
        }

    def get_vfi_intelligence_phase43(self):
        df = self._get_data()
        if df.empty or 'vfi_price_alignment' not in df.columns: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        alignments = []
        for align, group in best_strikes.groupby('vfi_price_alignment'):
            alignments.append({
                "alignment": str(align),
                "count": len(group),
                "hit_rate": round(group['hit_target'].mean() * 100, 1)
            })
            
        return {
            "alignments": alignments
        }

    def get_trade_quality_distribution(self):
        df = self._get_data()
        if df.empty or 'trade_quality_score' not in df.columns: return {}
        df_exec = df[df['signal_category'] == 'EXECUTED']
        if df_exec.empty: return {}
        
        best_strikes = df_exec.loc[df_exec.groupby('signal_id')['max_favorable_pct'].idxmax()]
        
        buckets = [
            {"name": "Elite (90-100)", "cond": best_strikes['trade_quality_score'] >= 90},
            {"name": "Good (70-90)", "cond": (best_strikes['trade_quality_score'] >= 70) & (best_strikes['trade_quality_score'] < 90)},
            {"name": "Average (50-70)", "cond": (best_strikes['trade_quality_score'] >= 50) & (best_strikes['trade_quality_score'] < 70)},
            {"name": "Weak (<50)", "cond": best_strikes['trade_quality_score'] < 50}
        ]
        
        res = []
        for b in buckets:
            g = best_strikes[b['cond']]
            res.append({
                "bucket": b['name'],
                "count": len(g),
                "hit_rate": round(g['hit_target'].mean() * 100, 1) if len(g) > 0 else 0
            })
            
        return res

    def get_ml_intelligence(self):
        import sqlite3
        import os
        import json
                
        data = {
            "ml_maturity": {"level": 0, "samples": 0},
            "quality_distribution": {
                "quality_0": 0,
                "quality_1": 0,
                "quality_2": 0,
                "quality_3": 0,
                "quality_4": 0
            },
            "recent_explosions": [],
            "recent_failures": [],
            "feature_regimes": [],
            "data_quality_stats": {
                "total_issues": 0,
                "bad_ticks": 0,
                "timestamp_gaps": 0,
                "low_liquidity": 0,
                "recent_logs": []
            }
        }
        
        if not os.path.exists(ML_DB_PATH):
            return data
            
        try:
            with get_db_connection(ML_DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # 1. Counts for Quality 1-4 (gamma_events) and Quality 0 (non_gamma_events)
                cursor.execute("SELECT gamma_quality, COUNT(*) FROM gamma_events GROUP BY gamma_quality")
                gamma_counts = {r[0]: r[1] for r in cursor.fetchall()}
                
                cursor.execute("SELECT COUNT(*) FROM non_gamma_events WHERE gamma_quality = 0")
                q0_count = cursor.fetchone()[0]
                
                data["quality_distribution"]["quality_0"] = q0_count
                data["quality_distribution"]["quality_1"] = gamma_counts.get(1, 0)
                data["quality_distribution"]["quality_2"] = gamma_counts.get(2, 0)
                data["quality_distribution"]["quality_3"] = gamma_counts.get(3, 0)
                data["quality_distribution"]["quality_4"] = gamma_counts.get(4, 0)
                
                total_samples = q0_count + sum(gamma_counts.values())
                data["ml_maturity"]["samples"] = total_samples
                
                if total_samples >= 1000: data["ml_maturity"]["level"] = 3
                elif total_samples >= 500: data["ml_maturity"]["level"] = 2
                elif total_samples >= 100: data["ml_maturity"]["level"] = 1
                else: data["ml_maturity"]["level"] = 0
                
                # 2. Recent Explosive events (Quality 4)
                cursor.execute("""
                    SELECT option_symbol, timestamp, max_attempted_move, premium_before, premium_after, time_taken_seconds, premium_path, underlying_path, timestamp_sequence,
                           session_type, quality_score, connection_quality, observation_version, data_source
                    FROM gamma_events WHERE gamma_quality = 4
                    ORDER BY timestamp DESC LIMIT 5
                """)
                for row in cursor.fetchall():
                    try:
                        p_path = json.loads(row["premium_path"]) if row["premium_path"] else []
                        u_path = json.loads(row["underlying_path"]) if row["underlying_path"] else []
                        t_seq = json.loads(row["timestamp_sequence"]) if row["timestamp_sequence"] else []
                    except Exception:
                        p_path, u_path, t_seq = [], [], []
                        
                    data["recent_explosions"].append({
                        "symbol": row["option_symbol"],
                        "timestamp": row["timestamp"],
                        "move": round(row["max_attempted_move"] or 0, 1),
                        "premium_before": row["premium_before"],
                        "premium_after": row["premium_after"],
                        "time_taken": row["time_taken_seconds"],
                        "premium_path": p_path,
                        "underlying_path": u_path,
                        "timestamp_sequence": t_seq,
                        "session_type": row["session_type"],
                        "quality_score": row["quality_score"],
                        "connection_quality": row["connection_quality"],
                        "observation_version": row["observation_version"],
                        "data_source": row["data_source"]
                    })
                    
                # 3. Recent Failed Ignitions (Quality 1)
                cursor.execute("""
                    SELECT option_symbol, timestamp, max_attempted_move, rejection_after_move, failure_reason,
                           session_type, quality_score, connection_quality, observation_version, data_source
                    FROM gamma_events WHERE gamma_quality = 1
                    ORDER BY timestamp DESC LIMIT 5
                """)
                for row in cursor.fetchall():
                    data["recent_failures"].append({
                        "symbol": row["option_symbol"],
                        "timestamp": row["timestamp"],
                        "move": round(row["max_attempted_move"] or 0, 1),
                        "rejection": round(row["rejection_after_move"] or 0, 1),
                        "reason": row["failure_reason"],
                        "session_type": row["session_type"],
                        "quality_score": row["quality_score"],
                        "connection_quality": row["connection_quality"],
                        "observation_version": row["observation_version"],
                        "data_source": row["data_source"]
                    })
                    
                # 4. Feature history / regime rankings
                cursor.execute("""
                    SELECT feature_name, market_regime, AVG(importance_score), SUM(drift_detected)
                    FROM feature_importance
                    GROUP BY feature_name, market_regime
                    ORDER BY AVG(importance_score) DESC
                """)
                for row in cursor.fetchall():
                    data["feature_regimes"].append({
                        "feature": row[0],
                        "regime": "TRENDING" if str(row[1]) == "1" else "RANGING",
                        "avg_importance": round(row[2] or 0, 1),
                        "drift_count": row[3]
                    })
                    
                # 5. Data Quality Audit stats
                cursor.execute("SELECT COUNT(*) FROM data_quality_log")
                data["data_quality_stats"]["total_issues"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM data_quality_log WHERE metric_type = 'BAD_TICK'")
                data["data_quality_stats"]["bad_ticks"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM data_quality_log WHERE metric_type = 'TIMESTAMP_GAP'")
                data["data_quality_stats"]["timestamp_gaps"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM data_quality_log WHERE metric_type = 'LOW_LIQUIDITY'")
                data["data_quality_stats"]["low_liquidity"] = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT timestamp, symbol, metric_type, value, status, details,
                           session_type, quality_score, connection_quality, observation_version, data_source
                    FROM data_quality_log
                    ORDER BY timestamp DESC LIMIT 5
                """)
                for row in cursor.fetchall():
                    data["data_quality_stats"]["recent_logs"].append({
                        "timestamp": row["timestamp"],
                        "symbol": row["symbol"],
                        "metric_type": row["metric_type"],
                        "value": round(row["value"] or 0, 2),
                        "status": row["status"],
                        "details": row["details"],
                        "session_type": row["session_type"],
                        "quality_score": row["quality_score"],
                        "connection_quality": row["connection_quality"],
                        "observation_version": row["observation_version"],
                        "data_source": row["data_source"]
                    })
                    
        except Exception as e:
            logger.error(f"[ML Analytics] DB Error: {e}")
            
        return data
