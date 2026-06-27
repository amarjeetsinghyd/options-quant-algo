import sqlite3
import os
import sys
from datetime import datetime
from src.core.market_calendar import MarketCalendar
from src.utils.logger import get_logger
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import ML_DB_PATH as DB_PATH

logger = get_logger("feature_monitor")


class FeatureStabilityMonitor:
    """
    Monitors feature stability over time.
    Saves and reads feature importance from the feature_importance table,
    segmenting results by market_regime to detect structural market changes.
    """

    def __init__(self):
        pass

    def log_feature_importance(self, model_name, model_version, feature_name, market_regime, importance_score, drift_detected=0):
        """Saves a single feature importance score to the DB."""
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
                INSERT INTO feature_importance (
                    timestamp, feature_name, market_regime, importance_score, drift_detected, model_name, model_version,
                    session_type, data_source, quality_score, connection_quality,
                    observation_status, observation_version, exchange_timestamp,
                    local_timestamp, latency_ms, market_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                local_ts, feature_name, str(market_regime), importance_score, drift_detected, model_name, model_version,
                session_type, data_source, 100.0, "GOOD",
                "FINALIZED", "v5.2", local_ts, local_ts, 0.0, "NORMAL"
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[FeatureStabilityMonitor] DB Write Error: {e}")

    def check_drift_and_log(self, model_name, model_version, market_regime, current_feature_importances):
        """
        Compares current feature importance scores with historical baselines
        for the same model and market regime.
        Logs values to DB and returns a list of warnings.
        """
        warnings = []
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
            
            for feature, current_score in current_feature_importances.items():
                # Get the last 5 importance scores for this feature and regime
                cursor.execute("""
                    SELECT importance_score FROM feature_importance
                    WHERE model_name = ? AND feature_name = ? AND market_regime = ?
                    ORDER BY timestamp DESC LIMIT 5
                """, (model_name, feature, str(market_regime)))
                rows = cursor.fetchall()
                
                drift_detected = 0
                if rows:
                    past_scores = [r[0] for r in rows]
                    avg_past = sum(past_scores) / len(past_scores)
                    
                    # If feature importance dropped by >50% relative to past baseline
                    if avg_past > 0 and (current_score / avg_past) < 0.5:
                        drift_detected = 1
                        warning_msg = f"WARNING: Feature Importance Drift! Model {model_name} feature {feature} importance dropped from {avg_past:.2f}% to {current_score:.2f}% in regime {market_regime}."
                        warnings.append(warning_msg)
                        
                # Log to DB
                cursor.execute("""
                    INSERT INTO feature_importance (
                        timestamp, feature_name, market_regime, importance_score, drift_detected, model_name, model_version,
                        session_type, data_source, quality_score, connection_quality,
                        observation_status, observation_version, exchange_timestamp,
                        local_timestamp, latency_ms, market_state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    local_ts, feature, str(market_regime), current_score, drift_detected, model_name, model_version,
                    session_type, data_source, 100.0, "GOOD",
                    "FINALIZED", "v5.2", local_ts, local_ts, 0.0, "NORMAL"
                ))
                
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"[FeatureStabilityMonitor] Error checking drift: {e}")
            
        return warnings
