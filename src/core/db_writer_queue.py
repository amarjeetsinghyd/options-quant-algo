import os
import threading
import queue
import time
from src.utils.logger import get_logger
from src.utils.instrumentation import get_db_connection

logger = get_logger("db_writer")

class DBWriterQueue:
    """
    Dedicated database writer to solve SQLite lock contention.
    Spawns one worker thread per database file and batches inserts.
    """
    _instances = {}
    _lock = threading.Lock()

    def __init__(self, db_path):
        self.db_path = db_path
        self.q = queue.Queue()
        self.running = True
        
        # Use simple basename for thread name
        db_name = os.path.basename(db_path)
        self.worker_thread = threading.Thread(
            target=self._worker_loop, 
            daemon=True, 
            name=f"DBWriter-{db_name}"
        )
        self.worker_thread.start()

    @classmethod
    def get_instance(cls, db_path):
        with cls._lock:
            if db_path not in cls._instances:
                cls._instances[db_path] = cls(db_path)
            return cls._instances[db_path]

    def enqueue(self, sql, parameters=()):
        self.q.put((sql, parameters))

    def _worker_loop(self):
        logger.info(f"Started dedicated DB writer for {self.db_path}")
        
        try:
            # Persistent connection for the worker thread
            conn = get_db_connection(self.db_path, check_same_thread=False)
            cursor = conn.cursor()
            
            # Enable WAL mode for high concurrency (writers don't block readers)
            cursor.execute("PRAGMA journal_mode=WAL;")
            conn.commit()
            
            while self.running:
                try:
                    # Batch processing logic
                    batch = []
                    while True:
                        try:
                            # If batch is empty, wait up to 0.5s for new item
                            # If batch has items, drain the queue quickly (0.01s wait)
                            item = self.q.get(timeout=0.5 if not batch else 0.01)
                            if item is None:  # Poison pill
                                self.running = False
                                break
                            batch.append(item)
                        except queue.Empty:
                            break
                            
                    if batch:
                        try:
                            cursor.execute("BEGIN TRANSACTION")
                            for sql, params in batch:
                                cursor.execute(sql, params)
                            conn.commit()
                        except Exception as e:
                            logger.error(f"Batch write error on {self.db_path}: {e}")
                            conn.rollback()
                        finally:
                            for _ in batch:
                                self.q.task_done()
                                
                except Exception as loop_e:
                    logger.error(f"Writer loop error: {loop_e}")
                    time.sleep(1) # Prevent tight loop on fatal error
                    
        finally:
            if 'conn' in locals():
                conn.close()
            logger.info(f"Writer thread for {self.db_path} terminated.")

    def stop(self):
        self.running = False
        self.q.put(None)
        self.worker_thread.join(timeout=2.0)
