import subprocess
import hashlib
import os
from pathlib import Path

# Cache for provenance info to avoid repeated disk/process overhead
_provenance_cache = None

def compute_file_sha256(filepath: Path) -> str:
    """Computes the SHA256 hash of a file's content."""
    if not filepath.exists():
        return "FILE_NOT_FOUND"
    sha256_hash = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception:
        return "ERROR_COMPUTING_HASH"

def get_git_info() -> dict:
    """Pulls git branch, commit hash, and dirty status using subprocess."""
    info = {
        "git_commit": "UNKNOWN",
        "git_branch": "UNKNOWN",
        "git_dirty": False
    }
    
    # Check if we are in a git repo
    base_dir = Path(__file__).resolve().parent.parent.parent
    if not (base_dir / ".git").exists():
        return info

    try:
        # Commit hash
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], 
            cwd=str(base_dir), 
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        info["git_commit"] = commit
        
        # Branch
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
            cwd=str(base_dir), 
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        info["git_branch"] = branch
        
        # Dirty status
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], 
            cwd=str(base_dir), 
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        info["git_dirty"] = bool(status)
    except Exception:
        pass
        
    return info

def get_provenance_metadata() -> dict:
    """
    Returns the complete code provenance and schema versioning metadata.
    This call is cached after the first execution to ensure zero runtime impact.
    """
    global _provenance_cache
    if _provenance_cache is not None:
        return _provenance_cache

    git_info = get_git_info()
    base_dir = Path(__file__).resolve().parent.parent.parent
    
    # Strategy Files hashing
    sig_gen_path = base_dir / "src" / "strategy" / "signal_generator.py"
    ind_path = base_dir / "src" / "strategy" / "indicators.py"
    
    hash_sig_gen = compute_file_sha256(sig_gen_path)
    hash_ind = compute_file_sha256(ind_path)
    
    # Combined strategy hash
    combined = (hash_sig_gen + hash_ind).encode("utf-8")
    strategy_hash = hashlib.sha256(combined).hexdigest()
    
    # Define features metadata and schemas
    _provenance_cache = {
        "git_commit": git_info["git_commit"],
        "git_branch": git_info["git_branch"],
        "git_dirty": git_info["git_dirty"],
        "strategy_hash": strategy_hash,
        "strategy_hash_details": {
            "signal_generator_sha256": hash_sig_gen,
            "indicators_sha256": hash_ind
        },
        "schema_version": "1.0",
        "migration_version": "1.0.0",
        "compatible_reader_version": "1.0.0",
        "feature_schema_version": "1.0.0",
        "dataset_schema_version": "1.0.0",
        "feature_lineage": {
            "vwap": {
                "name": "vwap",
                "source_columns": ["high", "low", "close", "volume"],
                "transformation": "CumSum(typical_price * valid_vol) / CumSum(valid_vol)",
                "version": "1.0"
            },
            "vwap_high": {
                "name": "vwap_high",
                "source_columns": ["high", "volume"],
                "transformation": "CumSum(high * valid_vol) / CumSum(valid_vol)",
                "version": "1.0"
            },
            "vwap_low": {
                "name": "vwap_low",
                "source_columns": ["low", "volume"],
                "transformation": "CumSum(low * valid_vol) / CumSum(valid_vol)",
                "version": "1.0"
            },
            "ema_9": {
                "name": "ema_9",
                "source_columns": ["close"],
                "transformation": "ExponentialMovingAverage(close, period=9)",
                "version": "1.0"
            },
            "rvol": {
                "name": "rvol",
                "source_columns": ["volume"],
                "transformation": "volume / SMA(volume, period=20)",
                "version": "1.0"
            },
            "atr": {
                "name": "atr",
                "source_columns": ["high", "low", "close"],
                "transformation": "SMA(TrueRange(high, low, close), period=14)",
                "version": "1.0"
            },
            "atr_expansion": {
                "name": "atr_expansion",
                "source_columns": ["atr"],
                "transformation": "atr / SMA(atr, period=20)",
                "version": "1.0"
            },
            "compression": {
                "name": "compression",
                "source_columns": ["atr_expansion"],
                "transformation": "atr_expansion < 0.85",
                "version": "1.0"
            },
            "market_regime": {
                "name": "market_regime",
                "source_columns": ["close", "vwap"],
                "transformation": "RollingSum(close > vwap) == 5 OR RollingSum(close < vwap) == 5",
                "version": "1.0"
            },
            "vfi": {
                "name": "vfi",
                "source_columns": ["typical_price", "volume", "close"],
                "transformation": "RollingSum(DirectionalVolume) / AverageVolume",
                "version": "1.0"
            },
            "vfi_ema": {
                "name": "vfi_ema",
                "source_columns": ["vfi"],
                "transformation": "ExponentialMovingAverage(vfi, period=5)",
                "version": "1.0"
            }
        }
    }
    
    return _provenance_cache
