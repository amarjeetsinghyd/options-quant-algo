import os
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path
from src.utils.logger import get_logger
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import ML_DB_PATH, STRIKE_DB_PATH, DATA_DIR

logger = get_logger("parquet_archiver")

def archive_ml_database(date_str=None):
    """
    Archives gamma_events and non_gamma_events for a specific date (or all dates before today).
    Reads from SQLite, exports to Parquet, and deletes from SQLite.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        
    archive_dir = os.path.join(DATA_DIR, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    
    conn = get_db_connection(ML_DB_PATH)
    
    try:
        for table in ["gamma_events", "non_gamma_events"]:
            # Query all finalized records that belong to dates < today
            # Assuming local_timestamp is in YYYY-MM-DD HH:MM:SS
            query = f"SELECT * FROM {table} WHERE date(local_timestamp) < date(?)"
            df = pd.read_sql_query(query, conn, params=(date_str,))
            
            if not df.empty:
                # Group by date and save Parquet
                df['date_only'] = pd.to_datetime(df['local_timestamp']).dt.date
                for d, group in df.groupby('date_only'):
                    parquet_file = os.path.join(archive_dir, f"{table}_{d}.parquet")
                    
                    # Append if exists, else write
                    if os.path.exists(parquet_file):
                        existing_df = pd.read_parquet(parquet_file)
                        combined = pd.concat([existing_df, group.drop(columns=['date_only'])]).drop_duplicates(subset=['event_id'])
                        combined.to_parquet(parquet_file, index=False)
                    else:
                        group.drop(columns=['date_only']).to_parquet(parquet_file, index=False)
                
                # Delete archived records from SQLite
                event_ids = df['event_id'].tolist()
                placeholders = ",".join("?" * len(event_ids))
                delete_query = f"DELETE FROM {table} WHERE event_id IN ({placeholders})"
                
                cursor = conn.cursor()
                cursor.execute(delete_query, event_ids)
                conn.commit()
                
                logger.info(f"Archived {len(df)} records from {table} to Parquet.")
            else:
                logger.info(f"No records to archive for {table}.")
                
    except Exception as e:
        logger.error(f"Error during Parquet archival: {e}")
    finally:
        try:
            logger.info("Running VACUUM to shrink ML Database...")
            conn.execute("VACUUM")
        except Exception as ve:
            logger.error(f"VACUUM failed: {ve}")
        conn.close()

def compress_institutional_memory():
    """
    Compresses the 1-minute Parquet files in institutional_memory into a single daily file.
    Deletes the individual minute files after successful compression.
    """
    inst_mem_dir = Path(DATA_DIR) / "institutional_memory"
    
    for base_folder in ["canonical_observations", "raw_ticks"]:
        base_path = inst_mem_dir / base_folder
        if not base_path.exists(): continue
            
        all_parquets = list(base_path.rglob("*.parquet"))
        dir_groups = {}
        for p in all_parquets:
            if "full_day" in p.name or (len(p.stem) == 8 and p.stem.isdigit()): continue
            dir_groups.setdefault(p.parent, []).append(p)
            
        for day_dir, files in dir_groups.items():
            if len(files) < 2: continue # Nothing to merge
            
            logger.info(f"Compressing {len(files)} files in {day_dir}")
            try:
                dfs = [pd.read_parquet(f) for f in files]
                merged_df = pd.concat(dfs, ignore_index=True)
                
                day_str = day_dir.name
                month_str = day_dir.parent.name
                year_str = day_dir.parent.parent.name
                
                new_filename = f"{day_str}{month_str}{year_str}.parquet"
                out_path = day_dir.parent / new_filename
                
                merged_df.to_parquet(out_path, index=False, compression="ZSTD")
                
                for f in files:
                    try:
                        f.unlink()
                    except Exception as e:
                        logger.error(f"Failed to delete {f}: {e}")
                        
                try:
                    day_dir.rmdir()
                except OSError:
                    pass
                        
                logger.info(f"Successfully compressed {day_dir} into {out_path.name}")
            except Exception as e:
                logger.error(f"Failed to compress {day_dir}: {e}")

if __name__ == "__main__":
    logger.info("Starting Daily Parquet Archival Job...")
    archive_ml_database()
    compress_institutional_memory()
    logger.info("Archival Complete.")
