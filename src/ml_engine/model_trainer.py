import os
import json
from datetime import datetime
import sqlite3
import pandas as pd

from src.ml_engine.data_validator import DataValidator
from src.ml_engine.leakage_detector import LeakageDetector
from src.ml_engine.walk_forward_validator import WalkForwardValidator

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models")
REGISTRY_PATH = os.path.join(MODELS_DIR, "registry.json")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ml_research.db")

class ModelTrainer:
    def __init__(self):
        os.makedirs(MODELS_DIR, exist_ok=True)
        self.validator = WalkForwardValidator()
        self.registry = self._load_registry()

    def _load_registry(self):
        if os.path.exists(REGISTRY_PATH):
            with open(REGISTRY_PATH, 'r') as f:
                return json.load(f)
        return {"models": []}

    def _save_registry(self):
        with open(REGISTRY_PATH, 'w') as f:
            json.dump(self.registry, f, indent=4)

    def _check_hardware_protection(self):
        """Ensures training only runs outside market hours to protect VPS/laptop."""
        now = datetime.now().time()
        market_open = datetime.strptime("09:15", "%H:%M").time()
        market_close = datetime.strptime("15:30", "%H:%M").time()
        if market_open <= now <= market_close:
            raise RuntimeError("Hardware Protection Active: Training is blocked during market hours (09:15 - 15:30).")

    def run_training_pipeline(self):
        print("Starting ML Training Pipeline...")
        self._check_hardware_protection()
        
        # 1. Load Data
        conn = sqlite3.connect(DB_PATH)
        # We would pull from gamma_events, non_gamma_events, and model_predictions
        df = pd.DataFrame() # Placeholder for actual historical query
        conn.close()
        
        if len(df) < 500:
            print("Not enough samples yet. Need 500+ events to train. Currently at Level 0 (Collection Data).")
            return

        # 2. Data Quality Layer
        df, drop_report = DataValidator.validate_training_batch(df)
        print("Data Validation Report:", drop_report)
        
        # 3. Leakage Protection
        df = LeakageDetector.filter_leaky_columns(df)
        
        # 4. Train Models
        models_to_train = ["LightGBM", "XGBoost", "RandomForest", "CatBoost"]
        for model_name in models_to_train:
            print(f"Training {model_name}...")
            
            # 5. Walk Forward Validation
            metrics = self.validator.validate(model_name, df)
            
            # 6. Save to Registry
            version = "v1"
            self.registry["models"].append({
                "model_name": model_name,
                "version": version,
                "training_samples": len(df),
                "created_date": datetime.now().isoformat(),
                "accuracy": metrics["accuracy"],
                "status": "Production Candidate" if metrics["accuracy"] > 75 else "Research",
                "production_candidate": metrics["accuracy"] > 75
            })
            
        self._save_registry()
        print("Training pipeline completed successfully.")

if __name__ == "__main__":
    trainer = ModelTrainer()
    try:
        trainer.run_training_pipeline()
    except Exception as e:
        print(f"Training failed: {e}")
