import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
import pyarrow.parquet as pq

from src.utils.logger import get_logger

logger = get_logger("dataset_health_monitor")

class DatasetHealthMonitor:
    """
    Tier 2: EOD Deep Scan Health Monitor
    Implements the Phase 10 Data Health Monitor.
    """
    SCHEMA_VERSION = "v3.1"
    
    @staticmethod
    def generate_expected_minutes():
        """Generate expected HHMM strings for NSE trading hours (09:15 to 15:30)"""
        expected = set()
        start = datetime.strptime("09:15", "%H:%M")
        end = datetime.strptime("15:30", "%H:%M")
        
        curr = start
        while curr <= end:
            expected.add(curr.strftime("%H%M"))
            curr += timedelta(minutes=1)
        return expected

    @staticmethod
    def verify_daily_partition(partition_dir: Path, date_str: str, file_prefix: str = "state_") -> bool:
        """
        Deep scans a daily partition, checking for missing minutes and file corruption.
        Generates manifest.json with health report.
        """
        if not partition_dir.exists() or not partition_dir.is_dir():
            logger.warning(f"Health Monitor: Partition directory does not exist: {partition_dir}")
            return False
            
        manifest_path = partition_dir / "manifest.json"
        
        total_rows = 0
        file_hashes = {}
        found_minutes = set()
        corrupted_files = []
        
        parquet_files = list(partition_dir.glob("*.parquet"))
        if not parquet_files:
            logger.warning(f"Health Monitor: No Parquet files found in {partition_dir}")
            return False
            
        master_hash = hashlib.sha256()
        
        for pfile in parquet_files:
            try:
                # 1. Corruption Check (can we read metadata?)
                meta = pq.read_metadata(pfile)
                total_rows += meta.num_rows
                
                # 2. Extract timestamp from filename (e.g., state_0915.parquet)
                name = pfile.stem
                if name.startswith(file_prefix):
                    time_str = name[len(file_prefix):]
                    found_minutes.add(time_str)
                    
                # 3. Hash Check
                hasher = hashlib.sha256()
                with open(pfile, 'rb') as f:
                    chunk = f.read(8192)
                    while chunk:
                        hasher.update(chunk)
                        chunk = f.read(8192)
                
                f_hash = hasher.hexdigest()
                file_hashes[pfile.name] = f_hash
                master_hash.update(f_hash.encode('utf-8'))
                
            except Exception as e:
                logger.error(f"Health Monitor: CORRUPTION DETECTED in {pfile.name}: {e}")
                corrupted_files.append(pfile.name)
                
        # 4. Continuity Check
        expected_minutes = DatasetHealthMonitor.generate_expected_minutes()
        # Only check missing minutes up to current time if it's the current day, or all if past day
        # For simplicity in EOD scan, we expect all of them.
        missing_minutes = sorted(list(expected_minutes - found_minutes))
        
        # 5. Generate Manifest with Health Report
        manifest_data = {
            "date": date_str,
            "row_count": total_rows,
            "file_count": len(parquet_files),
            "generated_at": datetime.now().isoformat() + "Z",
            "checksum_sha256": master_hash.hexdigest(),
            "compression": "ZSTD",
            "schema_version": DatasetHealthMonitor.SCHEMA_VERSION,
            "health_report": {
                "corrupted_files": corrupted_files,
                "missing_intervals_count": len(missing_minutes),
                "missing_intervals": missing_minutes,
                "is_healthy": len(corrupted_files) == 0 and len(missing_minutes) == 0
            },
            "files": file_hashes
        }
        
        try:
            with open(manifest_path, 'w') as f:
                json.dump(manifest_data, f, indent=2)
            
            if manifest_data["health_report"]["is_healthy"]:
                logger.info(f"Health Monitor: Partition {partition_dir} is HEALTHY.")
            else:
                logger.warning(f"Health Monitor: Partition {partition_dir} has ERRORS. Missing: {len(missing_minutes)}, Corrupted: {len(corrupted_files)}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to write health manifest: {e}")
            return False

if __name__ == "__main__":
    # Example usage for testing
    import sys
    if len(sys.argv) > 2:
        test_dir = Path(sys.argv[1])
        test_date = sys.argv[2]
        DatasetHealthMonitor.verify_daily_partition(test_dir, test_date)
