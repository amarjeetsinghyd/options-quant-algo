import os

# Base Directory (Project Root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# Data & Logs Directories
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Database Paths
ML_DB_PATH = os.path.join(DATA_DIR, "ml_research.db")
STRIKE_DB_PATH = os.path.join(DATA_DIR, "strike_research.db")
DUCKDB_PATH = os.path.join(DATA_DIR, "ml_analytics.duckdb")
INSTITUTIONAL_MEMORY_DIR = os.path.join(DATA_DIR, "institutional_memory")

# Market Time
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

# Premium Bounds
NIFTY_PREMIUM_MIN = 22
NIFTY_PREMIUM_MAX = 27
SENSEX_PREMIUM_MIN = 60
SENSEX_PREMIUM_MAX = 70

# Performance & Profiling Instrumentation
PROFILING_ENABLED = False
SYSTEM_METRICS_INTERVAL = 5  # seconds

# ─── SERVICE FEATURE FLAGS (per DOC-1.2 ASD v1) ─────────────────────────────────
# DO NOT change without updating DOC-1.2 version

# Core services
STRATEGY_VERSION = "3.1"
ENABLE_TRADING_BOT = True
ENABLE_RESEARCH_COLLECTOR = True
ENABLE_ZMQ_BUS = True
ENABLE_WEB_DASHBOARD = True

# Shadow ML predictor — DISABLED until Version 2
ENABLE_SHADOW_SERVICE = False

# ML engine flags
ENABLE_XGBOOST_SCORER = True
ENABLE_ENSEMBLE_ENGINE = False  # lightgbm/catboost removed
ENABLE_LSTM = False              # reserved for Version 2
ENABLE_RL_OPTIMIZER = False      # reserved for Version 2

# Data layer
ENABLE_PARQUET_JOURNAL = True
ENABLE_DUCKDB = False           # duckdb removed from deps

# Resource limits
MAX_RAM_MB = 400
LOG_RETENTION_DAYS = 7
PARQUET_WRITE_INTERVAL_SECONDS = 60

# Parquet storage path
PARQUET_DIR = os.path.join(DATA_DIR, "research_journal")

# ─── FUTURE INTEGRATION FLAGS (NOT THIS PHASE) ───────────────────────────
# Must remain False until Version 2 is explicitly approved
ENABLE_LIVE_BROKERAGE_EXECUTION = False
ENABLE_INSTITUTIONAL_REPORTS = False
ENABLE_MULTI_INSTRUMENT = False
ENABLE_AUTO_STRATEGY_DISCOVERY = False
