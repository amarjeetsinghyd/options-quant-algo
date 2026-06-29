import os
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

def analyze_layer_1():
    print("--- Layer 1: Canonical Observational Data (Institutional Memory) ---")
    data_dir = Path("data/institutional_memory/canonical_observations")
    if not data_dir.exists():
        print("Directory not found.")
        return
        
    files = list(data_dir.rglob("*.parquet"))
    print(f"Total Parquet Files found: {len(files)}")
    
    if not files: return
    
    # Analyze the most recent file
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    latest_file = files[0]
    
    try:
        df = pd.read_parquet(latest_file)
        print(f"Latest File: {latest_file.name}")
        print(f"Total rows in latest file: {len(df)}")
        if 'local_observation_timestamp' in df.columns:
            print(f"Time Range in latest file: {df['local_observation_timestamp'].min()} to {df['local_observation_timestamp'].max()}")
    except Exception as e:
        print(f"Error reading {latest_file.name}: {e}")

def analyze_layer_2():
    print("\n--- Layer 2: Machine Learning Data (Gamma & XGBoost) ---")
    db_path = Path("data/ml_research.db")
    if not db_path.exists():
        print("Database not found.")
        return
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Gamma Events
        cursor.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM gamma_events")
        g_count, g_min, g_max = cursor.fetchone()
        print(f"Gamma Events Recorded: {g_count}")
        if g_count > 0:
            print(f"Time Range: {g_min} to {g_max}")
            
        # Non-Gamma Events
        cursor.execute("SELECT COUNT(*) FROM non_gamma_events")
        ng_count = cursor.fetchone()[0]
        print(f"Non-Gamma Events Recorded: {ng_count}")
        
        # Shadow Predictions
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_predictions'")
        if cursor.fetchone():
            cursor.execute("SELECT COUNT(*) FROM shadow_predictions")
            sp_count = cursor.fetchone()[0]
            print(f"XGBoost Shadow Predictions: {sp_count}")
        else:
            print("XGBoost Shadow Predictions table not created yet.")
            
        conn.close()
    except Exception as e:
        print(f"Error analyzing DB: {e}")

def analyze_layer_3():
    print("\n--- Layer 3: Decision Journal (AI Strategy Engine) ---")
    file_path = Path("data/decision_history.parquet")
    if not file_path.exists():
        print("File not found.")
        return
        
    try:
        df = pd.read_parquet(file_path)
        print(f"Total Decisions Evaluated: {len(df)}")
        if 'timestamp' in df.columns:
            print(f"Time Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        if 'decision' in df.columns:
            accepted = len(df[df['decision'] != 'REJECT'])
            rejected = len(df[df['decision'] == 'REJECT'])
            print(f"Accepted Signals: {accepted}")
            print(f"Rejected Signals: {rejected}")
    except Exception as e:
        print(f"Error reading decision history: {e}")

if __name__ == "__main__":
    print(f"Data Analysis Report generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    analyze_layer_1()
    analyze_layer_2()
    analyze_layer_3()
    print("="*60)
