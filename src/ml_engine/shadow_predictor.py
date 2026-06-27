import threading
import sqlite3
import uuid
from datetime import datetime
import os
import sys
from src.core.market_calendar import MarketCalendar
from src.ml_engine.model_manager import ModelManager
from src.ml_engine.ensemble_engine import EnsembleEngine
from src.ml_engine.leakage_detector import LeakageDetector
from src.utils.logger import get_logger
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import ML_DB_PATH as DB_PATH

logger = get_logger("shadow_predictor")


class ShadowPredictor:
    """
    Executes predictions across all models in a non-blocking background thread.
    Zero authority on order placement.
    """
    def __init__(self):
        self.model_manager = ModelManager()
        self.ensemble = EnsembleEngine()

    def predict_all_models_async(self, signal_id, features):
        """Spawns a background thread to calculate and save predictions."""
        thread = threading.Thread(target=self._predict_and_save, args=(signal_id, features), daemon=True)
        thread.start()

    def _predict_and_save(self, signal_id, features):
        try:
            # 1. Leakage Protection Check
            LeakageDetector.validate_features(features, datetime.now())
            
            # 2. Run Predictions (XGBoost Only)
            model_names = ["XGBoost"]
            predictions = {}
            
            for model in model_names:
                raw_preds = self.model_manager.predict(model, features)
                
                # Fetch calibrated probabilities
                cal_5_prob = raw_preds["gamma_5_prob"]
                cal_10_prob = raw_preds["gamma_10_prob"]
                cal_20_prob = raw_preds["gamma_20_prob"]
                
                predictions[model] = {
                    "gamma_5_probability": cal_5_prob,
                    "gamma_10_probability": cal_10_prob,
                    "gamma_20_probability": cal_20_prob,
                    "expected_time": raw_preds["expected_time"],
                    "confidence_score": cal_10_prob # Base confidence on 10% target
                }
            
            # 4. Save to Database
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
            
            for model, preds in predictions.items():
                pred_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO model_predictions (
                        id, timestamp, signal_id, model_name, prediction_time, 
                        gamma_5_probability, gamma_10_probability, gamma_20_probability,
                        expected_time_to_target, confidence_score, created_at,
                        session_type, data_source, quality_score, connection_quality,
                        observation_status, observation_version, exchange_timestamp,
                        local_timestamp, latency_ms, market_state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pred_id, local_ts, signal_id, model, 0.0,
                    preds["gamma_5_probability"], preds["gamma_10_probability"], preds["gamma_20_probability"],
                    preds["expected_time"], preds["confidence_score"], local_ts,
                    session_type, data_source, 100.0, "GOOD",
                    "FINALIZED", "v5.2", local_ts, local_ts, 0.0, "NORMAL"
                ))
                
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"[ShadowPredictor] Error generating predictions: {e}")
