import sqlite3
import json
import os
import pandas as pd

from src.ml_engine.leakage_detector import LeakageDetector

from src.utils.logger import get_logger
logger = get_logger("dataset_builder")
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import ML_DB_PATH as DB_PATH



class DatasetBuilder:
    """
    Dataset Builder Layer.
    Fetches raw events from SQLite, parses pre-event JSON feature snapshots,
    filters them for specific experiments, and returns a clean DataFrame.
    """

    @staticmethod
    def _fetch_raw_events():
        """Fetches all raw gamma and non-gamma events from the database."""
        if not os.path.exists(DB_PATH):
            return pd.DataFrame()
            
        try:
            conn = get_db_connection(DB_PATH)
            # Query both tables
            gamma_df = pd.read_sql_query("SELECT * FROM gamma_events", conn)
            non_gamma_df = pd.read_sql_query("SELECT * FROM non_gamma_events", conn)
            conn.close()
            
            # Combine them
            df = pd.concat([gamma_df, non_gamma_df], ignore_index=True)
            return df
        except Exception as e:
            logger.error(f"[DatasetBuilder] Database read error: {e}")
            return pd.DataFrame()

    @classmethod
    def build_training_dataframe(cls, experiment_name=None, custom_filters=None):
        """
        Parses pre_event_snapshot JSON strings into columns.
        Applies experiment-specific filters.
        Enforces whitelisting via LeakageDetector.
        Returns (features_df, targets_df) or combined DataFrame.
        """
        raw_df = cls._fetch_raw_events()
        if raw_df.empty:
            logger.warning("[DatasetBuilder] Warning: No events found in database.")
            return pd.DataFrame()

        processed_rows = []
        for _, row in raw_df.iterrows():
            snapshot_str = row.get("pre_event_snapshot")
            if not snapshot_str:
                continue
                
            try:
                # Load features from JSON snapshot
                features = json.loads(snapshot_str)
                
                # Add base columns for filtering / metadata
                features["event_id"] = row.get("event_id")
                features["timestamp"] = row.get("timestamp")
                features["gamma_quality"] = row.get("gamma_quality")
                features["index_name"] = row.get("index_name")
                features["option_symbol"] = row.get("option_symbol")
                features["strike"] = row.get("strike")
                features["distance_from_atm"] = row.get("distance_from_atm")
                features["dte"] = row.get("dte")
                features["market_regime"] = features.get("market_regime", 0)
                
                # Add targets for multi-target calibration
                max_move = row.get("max_attempted_move", 0.0)
                features["gamma_5_actual"] = 1 if max_move >= 5.0 else 0
                features["gamma_10_actual"] = 1 if max_move >= 10.0 else 0
                features["gamma_20_actual"] = 1 if max_move >= 20.0 else 0
                
                processed_rows.append(features)
            except Exception as e:
                logger.error(f"[DatasetBuilder] Error parsing snapshot for event {row.get('event_id')}: {e}")

        if not processed_rows:
            return pd.DataFrame()

        df = pd.DataFrame(processed_rows)

        # Apply Experiment Filtering
        if experiment_name:
            experiment_name = experiment_name.upper()
            initial_len = len(df)
            
            if experiment_name == "EXPIRY_ONLY":
                # Train only on expiry days (DTE = 0)
                df = df[df["dte"] == 0]
                logger.info(f"[DatasetBuilder] Applied EXPIRY_ONLY filter: {initial_len} -> {len(df)} samples.")
                
            elif experiment_name == "TRENDING_DAYS":
                # Train only on trending days (regime == 1)
                df = df[df["market_regime"] == 1]
                logger.info(f"[DatasetBuilder] Applied TRENDING_DAYS filter: {initial_len} -> {len(df)} samples.")
                
            elif experiment_name == "ATM_ONLY":
                # Train only on At-The-Money options (distance == 0)
                df = df[df["distance_from_atm"] == 0]
                logger.info(f"[DatasetBuilder] Applied ATM_ONLY filter: {initial_len} -> {len(df)} samples.")
                
            else:
                logger.warning(f"[DatasetBuilder] Warning: Unknown experiment name '{experiment_name}'. No filters applied.")

        # Apply Custom Filters (e.g. {"index_name": "SENSEX", "strike": 75000})
        if custom_filters and isinstance(custom_filters, dict):
            for col, val in custom_filters.items():
                if col in df.columns:
                    df = df[df[col] == val]
                    
        # Apply strict Leakage Whitelist
        df = LeakageDetector.filter_leaky_columns(df)
        
        return df

if __name__ == "__main__":
    # Test harness
    df = DatasetBuilder.build_training_dataframe()
    if not df.empty:
        logger.info("Tabular training columns:", df.columns.tolist())
        logger.info("Sample size:", len(df))
    else:
        logger.info("Database is empty or could not be read.")
