"""
Strike Intelligence Report Generator
=====================================
Run as: python -m src.research.report_generator

Queries data/strike_research.db and prints institutional-level analytics.
"""

import sqlite3
import pandas as pd
from datetime import datetime
import os

DB_PATH = "data/strike_research.db"


def load_data() -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        print(f"[Report] Database not found at {DB_PATH}. No data yet.")
        return pd.DataFrame()

    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query("""
            SELECT
                st.*,
                ss.signal_type,
                ss.strategy,
                ss.index_name,
                ss.signal_timestamp,
                ss.index_price,
                ss.atm_strike,
                ss.traded_token,
                ss.time_of_day_bucket,
                ss.vwap_distance_pct,
                ss.ema_vwap_distance,
                ss.vfi_strength,
                ss.vfi_ema_at_signal,
                ss.momentum_score,
                ss.index_volatility,
                ss.signal_category,
                ss.rejection_reason,
                ss.rejection_stage,
                ss.filter_name,
                ss.virtual_tracking_completed
            FROM strike_tracking st
            JOIN signal_snapshots ss ON st.signal_id = ss.signal_id
            WHERE st.entry_premium > 0
        """, conn)
    except sqlite3.OperationalError as e:
        print(f"[Report] Database schema error (are migrations applied?): {e}")
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def _dte_bucket(dte):
    if dte == 0:
        return "0DTE"
    elif dte == 1:
        return "1DTE"
    else:
        return f"{dte}DTE"


def print_separator(title=""):
    print("\n" + "-" * 80)
    if title:
        print(f"  {title}")
        print("-" * 80)


def generate_report():
    print_separator("STRIKE INTELLIGENCE ANALYTICS REPORT")
    print(f"  Generated: {datetime.now().strftime('%d %b %Y  %H:%M:%S')}")
    print(f"  Database : {DB_PATH}")

    df = load_data()

    if df.empty:
        print("\n  No data available yet. Run the engine and generate signals first.")
        return

    total_signals = df['signal_id'].nunique()
    total_rows = len(df)
    print(f"\n  Total Signals Tracked : {total_signals}")
    print(f"  Total Strike Rows     : {total_rows}")

    # Ensure premium_bucket exists (fallback if migration is fresh and some rows lack it)
    if 'premium_bucket' not in df.columns:
        def _pct_bucket(premium):
            if premium < 20: return "₹10-20"
            elif premium < 40: return "₹20-40"
            elif premium < 70: return "₹40-70"
            elif premium < 100: return "₹70-100"
            else: return "₹100+"
        df['premium_bucket'] = df['entry_premium'].apply(_pct_bucket)
    else:
        # Fill NA just in case
        df['premium_bucket'] = df['premium_bucket'].fillna("UNKNOWN")

    df['dte_bucket'] = df['dte'].apply(_dte_bucket)

    # ──────────────────────────────────────────────
    # 1. Best Premium Bucket Ranking
    # ──────────────────────────────────────────────
    print_separator("1. Best Premium Bucket Ranking")
    bucket_order = ["₹10-20", "₹20-40", "₹40-70", "₹70-100", "₹100+", "UNKNOWN"]
    prem_df = (
        df.groupby('premium_bucket')
        .agg(
            total=('hit_target', 'count'),
            hits=('hit_target', 'sum'),
            avg_time=('time_to_target_sec', 'mean'),
            avg_score=('strike_efficiency_score', 'mean'),
            avg_spread_pct=('spread_pct', 'mean'),
            avg_liq_drop=('liquidity_drop_pct', 'mean')
        )
        .reindex(bucket_order)
        .dropna(subset=['total'])
        .reset_index()
    )
    prem_df['success_rate'] = (prem_df['hits'] / prem_df['total'] * 100).round(1)
    prem_df['avg_time'] = prem_df['avg_time'].round(1)
    prem_df['avg_score'] = prem_df['avg_score'].round(1)
    prem_df['avg_spread_pct'] = prem_df['avg_spread_pct'].round(2)
    prem_df['avg_liq_drop'] = prem_df['avg_liq_drop'].round(1)
    
    prem_df = prem_df.sort_values('avg_score', ascending=False)
    prem_df.columns = ['Premium Bucket', 'Total', 'Hits', 'Avg Time(s)', 'Avg Score', 'Avg Spread%', 'Avg Liq Drop%', 'Success%']
    print(prem_df.to_string(index=False))

    # ──────────────────────────────────────────────
    # 2. Fastest Strike Category (Distance)
    # ──────────────────────────────────────────────
    print_separator("2. Fastest Strike Category")
    dist_df = (
        df.groupby('distance_from_atm')
        .agg(
            total=('hit_target', 'count'),
            hits=('hit_target', 'sum'),
            avg_time=('time_to_target_sec', 'mean'),
            avg_score=('strike_efficiency_score', 'mean'),
        )
        .reset_index()
    )
    dist_df['success_rate'] = (dist_df['hits'] / dist_df['total'] * 100).round(1)
    dist_df['avg_time'] = dist_df['avg_time'].round(1)
    dist_df['avg_score'] = dist_df['avg_score'].round(1)
    dist_df.columns = ['Distance', 'Total', 'Hits', 'Avg Time(s)', 'Avg Score', 'Success%']
    dist_df['Distance'] = dist_df['Distance'].apply(lambda x: 'ATM' if x == 0 else f'OTM{x}')
    
    dist_df = dist_df.sort_values('Avg Time(s)', ascending=True)
    print(dist_df.to_string(index=False))

    # ──────────────────────────────────────────────
    # 3. Multi-Time Acceleration Analysis
    # ──────────────────────────────────────────────
    print_separator("3. Multi-Time Acceleration Analysis")
    if 'return_pct_30s' in df.columns:
        time_df = (
            df.groupby('premium_bucket')
            .agg(
                avg_ret_30s=('return_pct_30s', 'mean'),
                avg_ret_60s=('return_pct_60s', 'mean'),
                avg_ret_120s=('return_pct_120s', 'mean'),
                avg_ret_180s=('return_pct_180s', 'mean'),
            )
            .reindex(bucket_order)
            .dropna(how='all')
            .reset_index()
        )
        time_df = time_df.round(2)
        time_df.columns = ['Premium Bucket', 'Ret 30s (%)', 'Ret 60s (%)', 'Ret 120s (%)', 'Ret 180s (%)']
        print(time_df.to_string(index=False))
    else:
        print("  Multi-time snapshots not available in dataset yet.")

    # ──────────────────────────────────────────────
    # 4. Time of Day Analysis
    # ──────────────────────────────────────────────
    print_separator("4. Time of Day Analysis")
    if 'time_of_day_bucket' in df.columns:
        tod_df = (
            df.groupby('time_of_day_bucket')
            .agg(
                total=('hit_target', 'count'),
                hits=('hit_target', 'sum'),
                avg_time=('time_to_target_sec', 'mean'),
                avg_score=('strike_efficiency_score', 'mean')
            )
            .reset_index()
        )
        tod_df['success_rate'] = (tod_df['hits'] / tod_df['total'] * 100).round(1)
        tod_df['avg_time'] = tod_df['avg_time'].round(1)
        tod_df['avg_score'] = tod_df['avg_score'].round(1)
        tod_df.columns = ['Session', 'Total', 'Hits', 'Avg Time(s)', 'Avg Score', 'Success%']
        print(tod_df.to_string(index=False))
    else:
        print("  Time of day data not available.")

    # ──────────────────────────────────────────────
    # 5. Strategy Type Analysis
    # ──────────────────────────────────────────────
    print_separator("5. Strategy Type Analysis")
    strat_df = (
        df.groupby('strategy')
        .agg(
            total=('hit_target', 'count'),
            hits=('hit_target', 'sum'),
            avg_time=('time_to_target_sec', 'mean'),
            avg_score=('strike_efficiency_score', 'mean')
        )
        .reset_index()
    )
    strat_df['success_rate'] = (strat_df['hits'] / strat_df['total'] * 100).round(1)
    strat_df['avg_time'] = strat_df['avg_time'].round(1)
    strat_df['avg_score'] = strat_df['avg_score'].round(1)
    strat_df.columns = ['Strategy', 'Total', 'Hits', 'Avg Time(s)', 'Avg Score', 'Success%']
    print(strat_df.to_string(index=False))

    # ──────────────────────────────────────────────
    # 6. Strategy Validity Report
    # ──────────────────────────────────────────────
    print_separator("6. Strategy Validity Report")
    if 'target_hit_while_valid' in df.columns and 'strategy_alive_duration_sec' in df.columns:
        val_df = (
            df.groupby('strategy')
            .agg(
                total_hits=('hit_target', 'sum'),
                hits_while_valid=('target_hit_while_valid', 'sum'),
                avg_alive_sec=('strategy_alive_duration_sec', 'mean')
            )
            .reset_index()
        )
        val_df['valid_hits_pct'] = (val_df['hits_while_valid'] / val_df['total_hits'] * 100).round(1)
        val_df['avg_alive_sec'] = val_df['avg_alive_sec'].round(1)
        val_df.columns = ['Strategy', 'Total Hits', 'Hits while Valid', 'Avg Alive Duration(s)', 'Valid Hits%']
        print(val_df.to_string(index=False))
    else:
        print("  Strategy validity data not available.")

    # ──────────────────────────────────────────────
    # 7. Enhanced Missed Opportunity Analysis
    # ──────────────────────────────────────────────
    print_separator("7. Enhanced Missed Opportunity Analysis")

    comparison_rows = []
    for signal_id, group in df.groupby('signal_id'):
        traded = group[group['was_traded'] == 1]
        others = group[group['was_traded'] == 0]

        if traded.empty or others.empty:
            continue

        traded_row = traded.iloc[0]
        best_available = group.sort_values('strike_efficiency_score', ascending=False).iloc[0]

        traded_score = traded_row['strike_efficiency_score']
        best_score = best_available['strike_efficiency_score']

        if best_score > traded_score:
            comparison_rows.append({
                'Signal ID': signal_id[:8],
                'Type': traded_row['signal_type'],
                'Traded Strike': f"₹{traded_row['entry_premium']:.0f} "
                                 f"({'ATM' if traded_row['distance_from_atm']==0 else 'OTM'+str(traded_row['distance_from_atm'])})",
                'Traded Score': f"{traded_score:.1f}",
                'Best Strike': f"₹{best_available['entry_premium']:.0f} "
                               f"({'ATM' if best_available['distance_from_atm']==0 else 'OTM'+str(best_available['distance_from_atm'])})",
                'Best Score': f"{best_score:.1f}",
                'Delta Score': f"+{best_score - traded_score:.1f}",
                'Best Bucket': best_available.get('premium_bucket', '-'),
                'Fill Quality (Traded/Best)': f"{traded_row.get('entry_fill_quality', 0):.1f}% / {best_available.get('entry_fill_quality', 0):.1f}%"
            })

    if len(comparison_rows) > 0:
        missed_df = pd.DataFrame(comparison_rows)
        missed_df.columns = ['Strategy', 'Traded Strike', 'Best Strike', 'Score Delta', 'Best Bucket', 'Fill Quality (Traded/Best)']
        print(missed_df.to_string(index=False))
        print(f"\n  Total sub-optimal strike selections: {len(missed_df)}")
    else:
        print("  No sub-optimal selections found.")

    # ──────────────────────────────────────────────
    # 8. Filter Intelligence Report (Phase 3)
    # ──────────────────────────────────────────────
    print_separator("8. Filter Intelligence Report")
    if 'signal_category' in df.columns and 'virtual_tracking_completed' in df.columns:
        completed_df = df[df['virtual_tracking_completed'] == 1]
        
        signal_perf = completed_df.groupby('signal_id').agg(
            category=('signal_category', 'first'),
            filter_name=('filter_name', 'first'),
            rejection_stage=('rejection_stage', 'first'),
            any_valid_hit=('target_hit_while_valid', 'max'),
            best_missed_return=('max_favorable_pct', 'max')
        ).reset_index()
        
        rejected_signals = signal_perf[signal_perf['category'] == 'REJECTED']
        
        if rejected_signals.empty:
            print("  No rejected signals logged yet.")
        else:
            print(f"  Total Rejected Signals Tracked: {len(rejected_signals)}\n")
            
            filters = rejected_signals.groupby(['filter_name', 'rejection_stage']).agg(
                total=('signal_id', 'count'),
                false_rejects=('any_valid_hit', 'sum'),
                avg_missed_return=('best_missed_return', 'mean')
            ).reset_index()
            
            filters['correct_rejects'] = filters['total'] - filters['false_rejects']
            filters['protection_rate'] = (filters['correct_rejects'] / filters['total'] * 100).round(1)
            filters['false_reject_rate'] = (filters['false_rejects'] / filters['total'] * 100).round(1)
            filters['avg_missed_return'] = filters['avg_missed_return'].round(1)
            
            disp_df = filters[['filter_name', 'rejection_stage', 'total', 'correct_rejects', 'false_rejects', 'protection_rate', 'avg_missed_return']]
            disp_df.columns = ['Filter', 'Stage', 'Total', 'Correct Rej', 'False Rej', 'Protection%', 'Avg Missed Ret%']
            print(disp_df.to_string(index=False))
            
            print("\n  Danger Alerts:")
            alerts_found = False
            for _, row in filters.iterrows():
                if row['false_reject_rate'] > 30 and row['total'] >= 3:
                    print(f"  [WARNING] Filter '{row['filter_name']}' has a {row['false_reject_rate']}% false rejection rate!")
                    print(f"            It rejected {row['total']} signals, but {row['false_rejects']} of them reached 10% target.")
                    alerts_found = True
                    
            if not alerts_found:
                print("  No warnings. Filters are performing within acceptable bounds.")
    else:
        print("  Filter intelligence data not available yet (schema update required).")

    print_separator()
    print("  End of Report")
    print("-" * 80 + "\n")


if __name__ == "__main__":
    generate_report()
