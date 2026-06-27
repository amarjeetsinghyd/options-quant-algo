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

# Performance & Profiling Instrumentation
PROFILING_ENABLED = False
SYSTEM_METRICS_INTERVAL = 5  # seconds
