from datetime import datetime
import json
import os

from src.utils.logger import get_logger
logger = get_logger("leakage_detector")


REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "feature_registry.json")

def load_whitelist():
    try:
        with open(REGISTRY_PATH, 'r') as f:
            features = json.load(f).get("features", {})
            # Return list of feature names where allowed_for_training is True
            return [name for name, details in features.items() if details.get("allowed_for_training", False)]
    except Exception as e:
        logger.error(f"[LeakageDetector] Error loading feature registry: {e}")
        return []

class LeakageDetector:
    """
    Prevents Data Leakage by enforcing strict timing validation and column whitelists.
    The model must never accidentally see future information during training.
    """
    @staticmethod
    def validate_features(features, event_timestamp):
        """
        Validates that all features provided were generated strictly ON OR BEFORE
        the event_timestamp (the time the signal or prediction was triggered).
        """
        if "feature_timestamp" not in features:
            raise ValueError("[LeakageDetector] CRITICAL: Missing feature_timestamp. Feature row rejected.")
            
        try:
            feat_time = datetime.fromisoformat(features["feature_timestamp"])
            evt_time = datetime.fromisoformat(event_timestamp) if isinstance(event_timestamp, str) else event_timestamp
            
            if feat_time > evt_time:
                raise ValueError(f"[LeakageDetector] CRITICAL: Feature timestamp ({feat_time}) is from the FUTURE relative to event ({evt_time}).")
        except ValueError as e:
            if "CRITICAL" in str(e): raise
            logger.warning(f"[LeakageDetector] Warning: Timestamp parsing issue. {e}")
            
        return True

    @staticmethod
    def filter_leaky_columns(df):
        """
        Filters columns based on a strict whitelist from feature_registry.json.
        Any column not explicitly marked allowed_for_training=True (except targets/keys) is dropped.
        """
        whitelist = load_whitelist()
        
        # Meta columns that are required for training flow (e.g. target outputs, IDs)
        meta_columns = ["event_id", "timestamp", "gamma_quality", "actual_result", "gamma_5_actual", "gamma_10_actual", "gamma_20_actual"]
        
        safe_columns = [col for col in df.columns if col in whitelist or col in meta_columns]
        
        dropped = [col for col in df.columns if col not in safe_columns]
        if dropped:
            logger.info(f"[LeakageDetector] Dropped {len(dropped)} non-whitelisted columns: {dropped}")
            
        return df[safe_columns]
