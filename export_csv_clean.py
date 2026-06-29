import pandas as pd
import sqlite3
import json
import ast
from pathlib import Path

def safe_parse_json(val):
    if pd.isna(val): return {}
    if isinstance(val, dict): return val
    if isinstance(val, str):
        val = val.strip()
        # Some SQL saves strings with single quotes instead of double quotes
        val = val.replace("'", '"') 
        try:
            return json.loads(val)
        except:
            try:
                # Fallback to ast if json fails
                return ast.literal_eval(val)
            except:
                return {}
    return {}

def flatten_dataframe(df):
    """Finds columns with JSON strings and flattens them into separate columns."""
    cols_to_drop = []
    new_dfs = [df]
    
    for col in df.columns:
        # Check if the column contains JSON-like strings
        valid_samples = df[col].dropna()
        if not valid_samples.empty:
            sample = str(valid_samples.iloc[0]).strip()
            if sample.startswith('{') and sample.endswith('}'):
                print(f"  -> Unpacking complex column: {col}")
                parsed_series = df[col].apply(safe_parse_json)
                flattened = pd.json_normalize(parsed_series)
                # Prefix the new columns with the original column name to avoid clashes
                flattened.columns = [f"{col}__{str(c).replace(' ', '_')}" for c in flattened.columns]
                new_dfs.append(flattened)
                cols_to_drop.append(col)
            
    if cols_to_drop:
        # Concatenate original df (minus dropped cols) with the new flattened cols
        result = pd.concat(new_dfs, axis=1)
        result = result.drop(columns=cols_to_drop)
        return result
    return df

def run_clean_export():
    export_dir = Path("data/csv_exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Clean Gamma Events
    print("Cleaning Gamma Events...")
    try:
        conn = sqlite3.connect("data/ml_research.db")
        df_gamma = pd.read_sql_query("SELECT * FROM gamma_events", conn)
        df_gamma_clean = flatten_dataframe(df_gamma)
        
        # Replace newlines in ALL string columns just to be safe for Excel
        df_gamma_clean = df_gamma_clean.replace({r'\n': ' ', r'\r': ''}, regex=True)
        
        df_gamma_clean.to_csv(export_dir / "gamma_events_clean.csv", index=False)
        conn.close()
        print("[SUCCESS] gamma_events_clean.csv generated!")
    except Exception as e:
        print("[ERROR] Gamma Events:", e)

    # 2. Clean state_0930
    print("\nCleaning state_0930...")
    try:
        target_files = list(Path("data/institutional_memory/canonical_observations").rglob("state_0930.parquet"))
        if target_files:
            df_0930 = pd.read_parquet(target_files[0])
            df_0930_clean = flatten_dataframe(df_0930)
            
            df_0930_clean = df_0930_clean.replace({r'\n': ' ', r'\r': ''}, regex=True)
            
            df_0930_clean.to_csv(export_dir / "state_0930_clean.csv", index=False)
            print("[SUCCESS] state_0930_clean.csv generated!")
    except Exception as e:
        print("[ERROR] state_0930:", e)

if __name__ == "__main__":
    run_clean_export()
