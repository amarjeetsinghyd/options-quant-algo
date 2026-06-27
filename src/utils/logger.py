import logging
import sys
import threading

class StructuredMetadataFormatter(logging.Formatter):
    """
    Custom formatter that dynamically appends structured metadata:
    thread, worker, signal_id, trade_id, event_id, latency_ms, database_name
    to the log message prefix if they are provided in logging calls (via the extra dict).
    """
    def format(self, record):
        meta_parts = []
        
        # Automatically capture thread name if it's not the MainThread
        t_name = threading.current_thread().name
        if t_name and t_name != 'MainThread':
            meta_parts.append(f"thread={t_name}")
            
        # Capture specific metadata fields if they exist in the log record extra dict
        metadata_fields = [
            'worker_name', 
            'signal_id', 
            'trade_id', 
            'event_id', 
            'latency_ms', 
            'database_name'
        ]
        for field in metadata_fields:
            val = getattr(record, field, None)
            if val is not None:
                # Format latency nicely
                if field == 'latency_ms':
                    meta_parts.append(f"{field}={val:.2f}ms")
                else:
                    meta_parts.append(f"{field}={val}")
                    
        meta_str = f"[{', '.join(meta_parts)}]" if meta_parts else ""
        
        # Prepend metadata to the message if present
        original_msg = record.msg
        if meta_str:
            if isinstance(original_msg, str):
                record.msg = f"{meta_str} {original_msg}"
            else:
                record.msg = f"{meta_str} {str(original_msg)}"
                
        res = super().format(record)
        
        # Restore message to avoid side effects
        record.msg = original_msg
        return res

def get_logger(name):
    """
    Returns a standard logger with unified formatting:
    [Timestamp] [Level] [Module] Message
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = StructuredMetadataFormatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        logger.propagate = False
    return logger
