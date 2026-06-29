import pandas as pd
import sqlite3
import os
from pathlib import Path

def export_to_csv():
    export_dir = Path("data/csv_exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created export folder: {export_dir.absolute()}")

    # 1. Export decision_history.parquet
    print("Exporting decision_history...")
    try:
        df_decisions = pd.read_parquet("data/decision_history.parquet")
        df_decisions.to_csv(export_dir / "decision_history_export.csv", index=False)
        print("[SUCCESS] decision_history_export.csv")
    except Exception as e:
        print("[ERROR] exporting decision_history:", e)

    # 2. Export Gamma events from SQLite
    print("\nExporting gamma_events from database...")
    try:
        conn = sqlite3.connect("data/ml_research.db")
        df_gamma = pd.read_sql_query("SELECT * FROM gamma_events", conn)
        df_gamma.to_csv(export_dir / "gamma_events_export.csv", index=False)
        conn.close()
        print("[SUCCESS] gamma_events_export.csv")
    except Exception as e:
        print("[ERROR] exporting gamma_events:", e)

    # 3. Export state_0930.parquet (from the screenshot)
    print("\nExporting state_0930.parquet...")
    try:
        # Find the specific file recursively
        base_dir = Path("data/institutional_memory/canonical_observations")
        found_files = list(base_dir.rglob("state_0930.parquet"))
        if found_files:
            target_file = found_files[0]
            df_0930 = pd.read_parquet(target_file)
            df_0930.to_csv(export_dir / "state_0930_export.csv", index=False)
            print(f"[SUCCESS] state_0930_export.csv (Found at {target_file})")
        else:
            print("[ERROR] Could not find state_0930.parquet")
    except Exception as e:
        print("[ERROR] exporting state_0930:", e)

    print("\nAll requested exports complete! Check the 'data/csv_exports' folder.")

if __name__ == "__main__":
    export_to_csv()
