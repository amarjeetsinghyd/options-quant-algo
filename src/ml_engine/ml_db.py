import sqlite3
import os

try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False

from src.utils.logger import get_logger
logger = get_logger("ml_db")
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import ML_DB_PATH as DB_PATH, DUCKDB_PATH



def init_ml_db(recreate=True):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db_connection(DB_PATH)
    cursor = conn.cursor()

    if recreate:
        logger.info("[ML Database] Dropping old tables to recreate clean upgraded schemas...")
        cursor.execute("DROP TABLE IF EXISTS model_predictions")
        cursor.execute("DROP TABLE IF EXISTS model_performance")
        cursor.execute("DROP TABLE IF EXISTS gamma_events")
        cursor.execute("DROP TABLE IF EXISTS non_gamma_events")
        cursor.execute("DROP TABLE IF EXISTS feature_history") # drop old name if exists
        cursor.execute("DROP TABLE IF EXISTS feature_importance")
        cursor.execute("DROP TABLE IF EXISTS data_quality_log")

    # Table 1: Model Predictions with governance metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_predictions (
            id TEXT PRIMARY KEY,
            timestamp TEXT,
            signal_id TEXT,
            model_name TEXT,
            prediction_time REAL,
            gamma_5_probability REAL,
            gamma_10_probability REAL,
            gamma_20_probability REAL,
            expected_time_to_target REAL,
            confidence_score REAL,
            actual_result INTEGER,
            prediction_correct INTEGER,
            model_version TEXT,
            created_at TEXT,
            session_type TEXT,
            data_source TEXT,
            quality_score REAL,
            connection_quality TEXT,
            observation_status TEXT,
            observation_version TEXT,
            exchange_timestamp TEXT,
            local_timestamp TEXT,
            latency_ms REAL,
            market_state TEXT
        )
    """)

    # Table 2: Model Performance
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_performance (
            model_name TEXT,
            version TEXT,
            sample_size INTEGER,
            accuracy REAL,
            precision REAL,
            recall REAL,
            false_positive_rate REAL,
            false_negative_rate REAL,
            last_training_date TEXT,
            status TEXT,
            PRIMARY KEY (model_name, version)
        )
    """)

    # Table 3: Gamma Events with governance metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gamma_events (
            event_id TEXT PRIMARY KEY,
            timestamp TEXT,
            index_name TEXT,
            option_symbol TEXT,
            strike REAL,
            distance_from_atm INTEGER,
            premium_before REAL,
            premium_after REAL,
            percentage_move REAL,
            time_taken_seconds INTEGER,
            dte INTEGER,
            market_conditions_before_event TEXT,
            discovery_source TEXT,
            gamma_quality INTEGER,
            pre_event_snapshot TEXT,
            post_event_snapshot TEXT,
            gamma_timeframe INTEGER,
            max_attempted_move REAL,
            rejection_after_move REAL,
            failure_reason TEXT,
            feature_engine_version TEXT,
            collector_version TEXT,
            calculation_version TEXT,
            timestamp_sequence TEXT,
            premium_path TEXT,
            underlying_path TEXT,
            feature_evolution TEXT,
            liquidity_score REAL,
            spread_before_event REAL,
            session_type TEXT,
            data_source TEXT,
            quality_score REAL,
            connection_quality TEXT,
            observation_status TEXT,
            observation_version TEXT,
            exchange_timestamp TEXT,
            local_timestamp TEXT,
            latency_ms REAL,
            market_state TEXT
        )
    """)

    # Table 4: Non Gamma Events with governance metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS non_gamma_events (
            event_id TEXT PRIMARY KEY,
            timestamp TEXT,
            index_name TEXT,
            option_symbol TEXT,
            strike REAL,
            distance_from_atm INTEGER,
            premium_before REAL,
            premium_after REAL,
            percentage_move REAL,
            time_taken_seconds INTEGER,
            dte INTEGER,
            market_conditions_before_event TEXT,
            discovery_source TEXT,
            gamma_quality INTEGER,
            pre_event_snapshot TEXT,
            post_event_snapshot TEXT,
            gamma_timeframe INTEGER,
            max_attempted_move REAL,
            rejection_after_move REAL,
            failure_reason TEXT,
            feature_engine_version TEXT,
            collector_version TEXT,
            calculation_version TEXT,
            timestamp_sequence TEXT,
            premium_path TEXT,
            underlying_path TEXT,
            feature_evolution TEXT,
            liquidity_score REAL,
            spread_before_event REAL,
            session_type TEXT,
            data_source TEXT,
            quality_score REAL,
            connection_quality TEXT,
            observation_status TEXT,
            observation_version TEXT,
            exchange_timestamp TEXT,
            local_timestamp TEXT,
            latency_ms REAL,
            market_state TEXT
        )
    """)

    # Table 5: Feature Importance with governance metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feature_importance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            feature_name TEXT,
            market_regime TEXT,
            importance_score REAL,
            drift_detected INTEGER,
            model_name TEXT,
            model_version TEXT,
            session_type TEXT,
            data_source TEXT,
            quality_score REAL,
            connection_quality TEXT,
            observation_status TEXT,
            observation_version TEXT,
            exchange_timestamp TEXT,
            local_timestamp TEXT,
            latency_ms REAL,
            market_state TEXT
        )
    """)

    # Table 6: Data Quality Log with governance metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS data_quality_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            event_id TEXT,
            symbol TEXT,
            metric_type TEXT,
            value REAL,
            threshold REAL,
            status TEXT,
            details TEXT,
            session_type TEXT,
            data_source TEXT,
            quality_score REAL,
            connection_quality TEXT,
            observation_status TEXT,
            observation_version TEXT,
            exchange_timestamp TEXT,
            local_timestamp TEXT,
            latency_ms REAL,
            market_state TEXT
        )
    """)

    conn.commit()
    conn.close()
    
    if DUCKDB_AVAILABLE:
        try:
            logger.info("[ML Database] Initializing DuckDB analytics engine...")
            duck_conn = duckdb.connect(DUCKDB_PATH)
            # Attach the sqlite database to duckdb for fast analytics
            duck_conn.execute("INSTALL sqlite;")
            duck_conn.execute("LOAD sqlite;")
            duck_conn.execute(f"ATTACH IF NOT EXISTS '{DB_PATH}' AS sqlite_db (TYPE SQLITE);")
            logger.info("[ML Database] Attached SQLite DB to DuckDB successfully.")
            duck_conn.close()
        except Exception as e:
            logger.error(f"[ML Database] Could not attach SQLite to DuckDB: {e}")

if __name__ == "__main__":
    init_ml_db(recreate=True)
    logger.info(f"ML Database initialized at: {DB_PATH}")
