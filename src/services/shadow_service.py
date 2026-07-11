# ─── SHADOW SERVICE ────────────────────────────────────────────────────────
# This service is disabled by default via the feature flag in engineering_config.
# Toggle: src/config/engineering_config.py → ENABLE_SHADOW_SERVICE
import sys as _sys
try:
    from src.config.engineering_config import ENABLE_SHADOW_SERVICE
except ImportError:
    ENABLE_SHADOW_SERVICE = False


import time
import threading
import sys
import os
import pandas as pd

# Ensure project root is on PYTHONPATH when run as a script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.research.strike_intelligence import StrikeIntelligenceModule
from src.ml_engine.shadow_predictor import ShadowPredictor
from src.ml_engine.feature_builder import extract_features
from src.ml_engine.gamma_event_collector import GammaEventCollector
from src.core.message_bus import MessageBusSubscriber, FEED_PORT, EXEC_PORT
from src.utils.logger import get_logger

logger = get_logger("shadow_service")

class ShadowService:
    def __init__(self):
        self.intelligence = StrikeIntelligenceModule()
        self.gamma_collector = GammaEventCollector()
        try:
            self.shadow_predictor = ShadowPredictor()
        except Exception as e:
            logger.error(f"[ShadowService] ML Predictor disabled: {e}")
            self.shadow_predictor = None

        # ZMQ Subscribers
        self.feed_sub = MessageBusSubscriber(FEED_PORT, topics=["TICK."])
        self.exec_sub = MessageBusSubscriber(EXEC_PORT, topics=[
            "EXEC.SIGNAL_RESOLVED",
            "EXEC.OPTION_TICK",
        ])

        # Service state
        self.market_state = {}

    def on_feed_message(self, topic, payload):
        token = str(payload.get('token', ''))
        if token:
            self.intelligence.on_tick(token, payload)

    def on_exec_message(self, topic, payload):
        try:
            if topic == "EXEC.OPTION_TICK":
                self.gamma_collector.feed_tick(
                    symbol=payload["symbol"],
                    price=payload["price"],
                    index_price=payload["index_price"],
                    market_state=payload["market_state"],
                    option_details=payload["option_details"],
                    exchange_timestamp=payload["exchange_timestamp"],
                )
            elif topic == "EXEC.SIGNAL_RESOLVED":
                signal = payload.get("signal", {})
                price = payload.get("price", 0.0)
                recent_candles = payload.get("recent_candles")
                market_state = payload.get("market_state", {})
                telemetry = payload.get("telemetry", {})
                self.market_state = market_state
                simulated_state = {"market_state": market_state, "telemetry": telemetry}
                signal_id, _ = self.intelligence.register_signal(
                    signal,
                    price,
                    None,
                    None,
                    recent_candles,
                    signal_category=signal.get('signal_category', 'EXECUTED'),
                    rejection_reason=signal.get('rejection_reason'),
                    rejection_stage=signal.get('rejection_stage'),
                    filter_name=signal.get('filter_name'),
                    filter_value=signal.get('filter_value'),
                    would_have_entered_price=signal.get('would_have_entered_price'),
                )
                if signal_id:
                    self.intelligence.schedule_finalization(signal_id, delay=180.0)
                    if self.shadow_predictor:
                        try:
                            features = extract_features(simulated_state, signal)
                            self.shadow_predictor.predict_all_models_async(signal_id, features)
                        except Exception as ml_err:
                            logger.error(f"[ShadowService] Prediction error: {ml_err}")
        except Exception as e:
            logger.error(f"[ShadowService] Error processing EXEC message: {e}")

    def start(self):
        logger.info("=== STARTING SHADOW SERVICE (Intelligence & ML) ===")
        feed_thread = threading.Thread(target=self.feed_sub.listen, args=(self.on_feed_message,), daemon=True)
        feed_thread.start()
        self.exec_sub.listen(self.on_exec_message)

if __name__ == "__main__":
    service = ShadowService()
    try:
        service.start()
    except KeyboardInterrupt:
        logger.info("Shadow Service shutting down...")
        service.feed_sub.close()
        service.exec_sub.close()
