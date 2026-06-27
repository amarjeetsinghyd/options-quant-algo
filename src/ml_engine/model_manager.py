import os
import pickle
import pandas as pd
import numpy as np
from src.ml_engine.calibration_engine import ProbabilityCalibrationEngine

from src.utils.logger import get_logger
logger = get_logger("model_manager")


MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models")

class ModelManager:
    """
    Loads and manages the 4 competing machine learning models.
    Converts input dictionaries into DataFrames for prediction.
    """
    def __init__(self):
        self.models = {}
        self.calibrator = ProbabilityCalibrationEngine()
        self.load_models()

    def load_models(self):
        """Loads available models from the models directory."""
        os.makedirs(MODELS_DIR, exist_ok=True)
        model_files = {
            "XGBoost": "xgboost_v1.pkl"
        }
        
        for name, filename in model_files.items():
            filepath = os.path.join(MODELS_DIR, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'rb') as f:
                        self.models[name] = pickle.load(f)
                except Exception as e:
                    logger.error(f"[ModelManager] Error loading {name}: {e}")
            else:
                self.models[name] = None

    def predict(self, model_name, features):
        """
        Takes a raw feature dictionary, converts it to a DataFrame row,
        runs model prediction, and applies probability calibration for
        multiple gamma targets (5%, 10%, 20%).
        """
        model = self.models.get(model_name)
        
        if not model:
            # Shadow Mode: return safe default indicators during initial collection
            return {
                "gamma_5_prob": 0.05,
                "gamma_10_prob": 0.02,
                "gamma_20_prob": 0.005,
                "expected_time": 180.0
            }

        try:
            # Convert feature dict into 2D DataFrame for matching model schemas
            # Exclude metadata like timestamps
            excl_cols = ["feature_timestamp", "meta_versions", "signal_type"]
            input_dict = {k: v for k, v in features.items() if k not in excl_cols}
            df = pd.DataFrame([input_dict])
            
            # Predict raw probabilities (assumes classifier has predict_proba)
            # Model predicts probabilities for multiple targets if multi-output,
            # or separate model instances would be used.
            # Here we simulate/call raw prediction and calibrate.
            raw_probs = model.predict_proba(df)[0]
            
            # If model is binary, it outputs probability of class 1.
            # For multi-target, we map them:
            raw_5 = raw_probs[1] if len(raw_probs) > 1 else 0.05
            raw_10 = raw_5 * 0.4  # Proportional proxy if single model
            raw_20 = raw_5 * 0.1
            
            # Calibrate raw probabilities
            g5_cal = self.calibrator.calibrate_prediction(model_name, "gamma_5", raw_5)
            g10_cal = self.calibrator.calibrate_prediction(model_name, "gamma_10", raw_10)
            g20_cal = self.calibrator.calibrate_prediction(model_name, "gamma_20", raw_20)
            
            return {
                "gamma_5_prob": float(g5_cal),
                "gamma_10_prob": float(g10_cal),
                "gamma_20_prob": float(g20_cal),
                "expected_time": 120.0 # Expected time to target in seconds
            }
            
        except Exception as e:
            logger.error(f"[ModelManager] Prediction error for {model_name}: {e}")
            return {
                "gamma_5_prob": 0.05,
                "gamma_10_prob": 0.02,
                "gamma_20_prob": 0.005,
                "expected_time": 180.0
            }
