import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
import pyarrow.parquet as pq
from src.utils.logger import get_logger

logger = get_logger("dataset_manifest")

class DatasetManifest:
    """
    Implements the Dataset Integrity Layer for Canonical Observation Dataset v3.1.
    Generates a cryptographic manifest for daily partitions.
    """
    SCHEMA_VERSION = "v3.1"
    
    @staticmethod
    def generate_manifest(partition_dir: Path, date_str: str) -> bool:
        """
        Scans a daily partition directory (e.g., data/institutional_memory/.../2026/06/27)
        and generates a manifest.json.
        """
        if not partition_dir.exists() or not partition_dir.is_dir():
            logger.warning(f"Partition directory does not exist: {partition_dir}")
            return False
            
        manifest_path = partition_dir / "manifest.json"
        
        total_rows = 0
        symbols_seen = set()
        file_hashes = {}
        
        parquet_files = list(partition_dir.glob("*.parquet"))
        if not parquet_files:
            return False
            
        # Combine all file hashes into a master hash
        master_hash = hashlib.sha256()
        
        start_ts = None
        end_ts = None
        
        for pfile in parquet_files:
            try:
                # Calculate file hash
                hasher = hashlib.sha256()
                with open(pfile, 'rb') as f:
                    chunk = f.read(8192)
                    while chunk:
                        hasher.update(chunk)
                        chunk = f.read(8192)
                
                f_hash = hasher.hexdigest()
                file_hashes[pfile.name] = f_hash
                master_hash.update(f_hash.encode('utf-8'))
                
                # Read metadata without loading data
                meta = pq.read_metadata(pfile)
                total_rows += meta.num_rows
                
                # We could extract symbols and timestamps if we read the table, 
                # but reading the whole table just for the manifest could be memory intensive.
                # Since we know the collector appends chronologically, we will just record the file metadata.
                
            except Exception as e:
                logger.error(f"Error processing {pfile.name} for manifest: {e}")
                
        manifest_data = {
            "date": date_str,
            "row_count": total_rows,
            "file_count": len(parquet_files),
            "generated_at": datetime.now().isoformat() + "Z",
            "checksum_sha256": master_hash.hexdigest(),
            "compression": "ZSTD",
            "schema_version": DatasetManifest.SCHEMA_VERSION,
            "files": file_hashes
        }
        
        try:
            with open(manifest_path, 'w') as f:
                json.dump(manifest_data, f, indent=2)
            logger.info(f"Manifest generated successfully for {partition_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to write manifest: {e}")
            return False
