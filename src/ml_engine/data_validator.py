import sqlite3
from datetime import datetime
import os
import sys
from src.core.market_calendar import MarketCalendar
import pandas as pd
from src.utils.logger import get_logger
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import ML_DB_PATH as DB_PATH

logger = get_logger("data_validator")


class DataValidator:
    """
    Data Quality Layer.
    Before ML training and during collector scans, check for:
    - Bad ticks (excessive price jump without volume)
    - Candle gaps (missing minutes in market data)
    - Liquidity failures (abnormal spreads, low volume)
    """

    @staticmethod
    def log_quality_issue(event_id, symbol, metric_type, value, threshold, status, details):
        """Logs quality metrics and rejections to the data_quality_log table."""
        try:
            local_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session_type = MarketCalendar.get_session_type()
            if "unittest" in sys.modules or any("test" in arg.lower() for arg in sys.argv):
                session_type = "UNIT_TEST"
                
            if session_type == "LIVE":
                data_source = "LIVE_WEBSOCKET"
            elif session_type == "REPLAY":
                data_source = "REPLAY_ENGINE"
            elif session_type == "SIMULATION":
                data_source = "SIMULATION"
            elif session_type == "UNIT_TEST":
                data_source = "UNIT_TEST"
            else:
                data_source = "UNKNOWN"
                
            conn = get_db_connection(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO data_quality_log (
                    timestamp, event_id, symbol, metric_type, value, threshold, status, details,
                    session_type, data_source, quality_score, connection_quality,
                    observation_status, observation_version, exchange_timestamp,
                    local_timestamp, latency_ms, market_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                local_ts, event_id, symbol, metric_type, value, threshold, status, details,
                session_type, data_source, 100.0, "GOOD",
                "FINALIZED", "v5.2", local_ts, local_ts, 0.0, "NORMAL"
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[DataValidator] Error writing to data_quality_log: {e}")

    @classmethod
    def validate_sample(cls, features, event_id, symbol):
        """
        Validates a single option feature snapshot.
        Returns (is_valid, reason)
        """
        # 1. Bad Tick Detector: Premium jump > 300% without matching volume/OFA spike
        premium = features.get("premium", 0.0)
        p_change_10s = features.get("premium_change_10s", 0.0)
        ofa_score = features.get("ofa_score", 0.0)
        
        if premium <= 0:
            cls.log_quality_issue(event_id, symbol, "BAD_TICK", premium, 0.0, "DROPPED", "Premium is zero or negative.")
            return False, "Premium is zero or negative."
            
        if p_change_10s > 300.0 and ofa_score < 1.0:
            cls.log_quality_issue(event_id, symbol, "BAD_TICK", p_change_10s, 300.0, "DROPPED", 
                                  f"Premium jumped {p_change_10s:.1f}% without corresponding order flow volume (OFA score {ofa_score:.2f}).")
            return False, f"Premium jump >300% without volume spike (OFA Score: {ofa_score})."

        # 2. Liquidity Validation: Reject massive spreads or virtually zero volume
        spread_pct = features.get("spread_percentage", 0.0)
        # If not present in features, check spread_before_event if passed
        if spread_pct > 20.0:
            cls.log_quality_issue(event_id, symbol, "LOW_LIQUIDITY", spread_pct, 20.0, "DROPPED", 
                                  f"Spread percentage ({spread_pct:.1f}%) exceeds maximum threshold.")
            return False, f"Spread too wide ({spread_pct:.1f}%)."
            
        return True, ""

    @classmethod
    def check_candle_gaps(cls, df, event_id, symbol):
        """
        Checks for gaps in candle timestamps for the index.
        E.g. missing 09:22 between 09:21 and 09:23.
        Returns (has_gaps, gap_details)
        """
        if df is None or len(df) < 2:
            return False, ""
            
        try:
            timestamps = pd.to_datetime(df["timestamp"]).sort_values()
            diffs = timestamps.diff().dropna()
            
            # 1-minute interval expected. Check for differences > 65 seconds
            gaps = diffs[diffs > pandas_minute_delta()]
            if not gaps.empty:
                gap_count = len(gaps)
                max_gap_seconds = gaps.max().total_seconds()
                cls.log_quality_issue(event_id, symbol, "TIMESTAMP_GAP", max_gap_seconds, 60.0, "WARNING",
                                      f"Found {gap_count} timestamp gaps. Max gap: {max_gap_seconds}s.")
                return True, f"Found {gap_count} gaps, max gap: {max_gap_seconds}s."
        except Exception as e:
            logger.error(f"[DataValidator] Gap detection error: {e}")
            
        return False, ""

    @classmethod
    def validate_training_batch(cls, df):
        """
        Takes a Pandas DataFrame of historical features and filters it.
        Returns the cleaned DataFrame and a report.
        """
        report = {
            "initial_rows": len(df),
            "dropped_missing": 0,
            "dropped_bad_ticks": 0,
            "dropped_abnormal_spreads": 0
        }
        
        if df.empty:
            return df, report
            
        # 1. Drop Missing Values
        initial = len(df)
        df = df.dropna()
        report["dropped_missing"] = initial - len(df)
        
        # 2. Drop Bad Ticks (e.g. premium <= 0)
        if "premium" in df.columns:
            initial = len(df)
            df = df[df["premium"] > 0]
            # Check for excessive jumps without OFA volume
            if "premium_change_10s" in df.columns and "ofa_score" in df.columns:
                df = df[~((df["premium_change_10s"] > 300.0) & (df["ofa_score"] < 1.0))]
            report["dropped_bad_ticks"] = initial - len(df)
            
        # 3. Abnormal spreads (if spread percentage exists and is > 20%)
        if "spread_before_event" in df.columns and "premium_before" in df.columns:
            initial = len(df)
            # Calculate spread percentage
            spread_pct = (df["spread_before_event"] / df["premium_before"]) * 100
            df = df[spread_pct <= 20.0]
            report["dropped_abnormal_spreads"] = initial - len(df)
            
        return df, report

def pandas_minute_delta():
    import pandas as pd
    return pd.Timedelta(minutes=1, seconds=5)
