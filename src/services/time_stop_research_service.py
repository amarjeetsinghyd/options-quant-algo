# C:\Quant\src\services\time_stop_research_service.py
# QOT v1.0.0 — Standalone Time-Stop Research Service for post-exit monitoring

import os
import json
import time
import threading
import polars as pl
from pathlib import Path
from datetime import datetime
from src.core.market_data_cache import MarketDataCache
from src.utils.logger import get_logger
from src.utils.file_utils import write_envelope_json_atomic
from src.utils.provenance import get_provenance_metadata

logger = get_logger("time_stop_research")

class TimeStopResearchService:
    """
    Manages post-exit trade tracking for 10 minutes to analyze time stop effectiveness.
    Reads/writes queue state from runtime/research_queue.json for crash recovery.
    """
    def __init__(self, data_cache: MarketDataCache, exec_pub=None):
        self.cache = data_cache
        self.queue_file = Path("runtime/research_queue.json")
        self.parquet_file = Path("data/research/time_stop_analysis.parquet")
        
        if exec_pub is not None:
            self.exec_pub = exec_pub
        else:
            from src.core.message_bus import MessageBusPublisher, EXEC_PORT
            self.exec_pub = MessageBusPublisher(EXEC_PORT)
        
        self.queue_lock = threading.Lock()
        self.active_queue = []
        self._stop_event = threading.Event()
        self.worker_thread = None
        
        # Load persisted queue on start
        self._load_queue()
        
    def start(self):
        """Starts the 5-second polling scheduler thread."""
        logger.info("[TimeStopResearch] Starting TimeStopResearchService scheduler...")
        self._stop_event.clear()
        self.worker_thread = threading.Thread(target=self._scheduler_loop, name="TimeStopResearchLoop", daemon=True)
        self.worker_thread.start()
        
    def stop(self):
        """Stops the scheduler thread."""
        logger.info("[TimeStopResearch] Stopping TimeStopResearchService...")
        self._stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
            
    def register_trade_entry(self, trade_setup: dict) -> None:
        """Called when a sniper trade is executed to start passive research tracking."""
        with self.queue_lock:
            # Check if already in queue
            if any(q["signal_id"] == trade_setup.get("decision_uuid") for q in self.active_queue):
                return
                
            now_ts = time.time()
            prov = get_provenance_metadata()
            
            # Extract entry market parameters
            decision_payload = trade_setup.get("decision_payload", {})
            market_state = decision_payload.get("market_state", {})
            machine_state = decision_payload.get("machine_state", {})
            rule_evals = decision_payload.get("rule_evaluations", [])
            
            # Find signal score if present
            signal_score = 100.0
            for r in rule_evals:
                if r.get("rule_id") == "SIGNAL_SCORE":
                    signal_score = float(r.get("input_values", {}).get("score", 100.0))
                    break
            
            entry_item = {
                "signal_id": trade_setup.get("decision_uuid"),
                "strategy": trade_setup.get("strategy", "UNKNOWN"),
                "symbol": trade_setup.get("symbol"),
                "token": trade_setup.get("token"),
                "exch_seg": trade_setup.get("exch_seg"),
                "lot_size": int(trade_setup.get("params", {}).get("lot_size", 50)),
                "entry_time_ts": now_ts,
                "entry_time_str": datetime.now().isoformat(),
                "entry_price": float(trade_setup.get("entry_price", 0.0)),
                "type": trade_setup.get("type", "CALL"),
                
                # Exit parameters (will be populated on exit)
                "live_exit_time_ts": 0.0,
                "live_exit_time_str": "",
                "live_exit_price": 0.0,
                "live_exit_reason": "",
                "live_pnl": 0.0,
                
                # Collected premiums at minute marks
                "premiums": {
                    "4m": 0.0, "5m": 0.0, "6m": 0.0, "7m": 0.0,
                    "8m": 0.0, "9m": 0.0, "10m": 0.0
                },
                
                # Post-exit bounds
                "best_price_after_exit": 0.0,
                "worst_price_after_exit": 999999.0,
                "best_time_after_exit": "",
                "worst_time_after_exit": "",
                
                # Market Context
                "market_regime": int(market_state.get("market_regime", 0)),
                "compression": float(market_state.get("compression", 0.0)),
                "vfi": float(market_state.get("vfi", 0.0)),
                "atr": float(market_state.get("atr", 0.0)),
                "iv": 0.0,  # Reserved
                "days_to_expiry": int(trade_setup.get("dte", 0)) if isinstance(trade_setup.get("dte"), (int, float)) else 0,
                "entry_signal_score": signal_score,
                
                # Provenance / Versioning
                "research_epoch": 1,
                "engine_version": "1.0.0",
                "strategy_version": prov.get("strategy_version", "1.0.0"),
                "parameter_version": "1.0.0",
                "git_commit": prov.get("git_commit", "UNKNOWN")
            }
            
            self.active_queue.append(entry_item)
            logger.info(f"[TimeStopResearch] Registered trade entry for {entry_item['symbol']}")
            self._save_queue()
            
    def register_trade_exit(self, signal_id: str, exit_price: float, reason: str, net_pl: float) -> None:
        """Called when a live trade exits to mark the start of post-exit observation."""
        with self.queue_lock:
            for item in self.active_queue:
                if item["signal_id"] == signal_id:
                    item["live_exit_time_ts"] = time.time()
                    item["live_exit_time_str"] = datetime.now().isoformat()
                    item["live_exit_price"] = float(exit_price)
                    item["live_exit_reason"] = reason
                    item["live_pnl"] = float(net_pl)
                    logger.info(f"[TimeStopResearch] Registered trade exit for {item['symbol']} (Exit Price: {exit_price})")
                    self._save_queue()
                    break

    def get_observed_tokens(self) -> list:
        """Returns all option tokens currently active in the observation queue."""
        with self.queue_lock:
            return [q["token"] for q in self.active_queue]

    def _scheduler_loop(self):
        """Worker thread processing the queue every 5 seconds."""
        while not self._stop_event.is_set():
            try:
                self._update_observations()
            except Exception as e:
                logger.error(f"[TimeStopResearch] Error in scheduler loop: {e}")
            time.sleep(5)

    def _update_observations(self):
        """Updates the active observations by reading current prices from the cache."""
        now = time.time()
        completed_items = []
        changed = False
        
        with self.queue_lock:
            for item in self.active_queue:
                token = item["token"]
                ltp = self.cache.get_ltp(token)
                
                if ltp <= 0.0:
                    continue  # Wait for a valid tick
                    
                elapsed = now - item["entry_time_ts"]
                
                # 1. Capture premiums at minute marks (4m to 10m)
                for minutes in range(4, 11):
                    key = f"{minutes}m"
                    # Capture premium close to the minute mark if not already recorded
                    if elapsed >= (minutes * 60) and item["premiums"][key] == 0.0:
                        item["premiums"][key] = ltp
                        changed = True
                        
                # 2. Track post-exit bounds
                if item["live_exit_time_ts"] > 0.0 and now > item["live_exit_time_ts"]:
                    # Best Price (Maximum premium)
                    if ltp > item["best_price_after_exit"]:
                        item["best_price_after_exit"] = ltp
                        item["best_time_after_exit"] = datetime.now().isoformat()
                        changed = True
                    # Worst Price (Minimum premium)
                    if ltp < item["worst_price_after_exit"]:
                        item["worst_price_after_exit"] = ltp
                        item["worst_time_after_exit"] = datetime.now().isoformat()
                        changed = True
                        
                # 3. Check for completion (10 minutes/600 seconds)
                if elapsed >= 600:
                    completed_items.append(item)
                    
            # Process completed items
            for item in completed_items:
                self.active_queue.remove(item)
                changed = True
                self._finalize_observation(item)
                
            if changed:
                self._save_queue()

    def _finalize_observation(self, item: dict):
        """Calculates final time-stop metrics and saves the completed row to Parquet."""
        logger.info(f"[TimeStopResearch] Finalizing observation for {item['symbol']}")
        
        try:
            import uuid
            try:
                git_commit = get_provenance_metadata().get("git_commit", "unknown")[:7]
            except Exception:
                git_commit = "unknown"
                
            envelope = {
                "schema_version": "1.0",
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "engine_version": "1.1.0",
                "git_commit": git_commit,
                "event": {
                    "notification_id": str(uuid.uuid4()),
                    "event_type": "RESEARCH_COMPLETED",
                    "severity": "RESEARCH",
                    "title": "Research Completed",
                    "description": f"Observation Completed: {item['symbol']} // Final PnL ₹{item['live_pnl']:.2f}",
                    "timestamp": int(time.time() * 1000),
                    "correlation_id": (item.get("signal_id") or '')[:8],
                    "strategy": item.get('strategy', 'Strategy 1'),
                    "instrument": item.get('symbol', '--'),
                    "premium": None,
                    "pnl": item.get('live_pnl'),
                    "status": "Generated"
                }
            }
            self.exec_pub.publish("EXEC.EVENT", envelope)
        except Exception as e:
            logger.debug(f"Event publish failed: {e}")
        
        # Safe fallback for bounds
        best_price = item["best_price_after_exit"] if item["best_price_after_exit"] > 0.0 else item["live_exit_price"]
        worst_price = item["worst_price_after_exit"] if item["worst_price_after_exit"] < 999999.0 else item["live_exit_price"]
        
        # Calculate additional profit/loss possible
        add_profit = max(0.0, (best_price - item["live_exit_price"]) * item["lot_size"])
        add_loss = max(0.0, (item["live_exit_price"] - worst_price) * item["lot_size"])
        
        row_dict = {
            "signal_id": [item["signal_id"]],
            "strategy": [item["strategy"]],
            "entry_time": [item["entry_time_str"]],
            "entry_price": [item["entry_price"]],
            "live_exit_time": [item["live_exit_time_str"]],
            "live_exit_price": [item["live_exit_price"]],
            "live_exit_reason": [item["live_exit_reason"]],
            "live_pnl": [item["live_pnl"]],
            
            # Post-exit premiums
            "premium_4m": [item["premiums"]["4m"] if item["premiums"]["4m"] > 0.0 else item["live_exit_price"]],
            "premium_5m": [item["premiums"]["5m"] if item["premiums"]["5m"] > 0.0 else item["live_exit_price"]],
            "premium_6m": [item["premiums"]["6m"] if item["premiums"]["6m"] > 0.0 else item["live_exit_price"]],
            "premium_7m": [item["premiums"]["7m"] if item["premiums"]["7m"] > 0.0 else item["live_exit_price"]],
            "premium_8m": [item["premiums"]["8m"] if item["premiums"]["8m"] > 0.0 else item["live_exit_price"]],
            "premium_9m": [item["premiums"]["9m"] if item["premiums"]["9m"] > 0.0 else item["live_exit_price"]],
            "premium_10m": [item["premiums"]["10m"] if item["premiums"]["10m"] > 0.0 else item["live_exit_price"]],
            
            # Bounds
            "best_price_after_exit": [best_price],
            "worst_price_after_exit": [worst_price],
            "best_time_after_exit": [item["best_time_after_exit"] or item["live_exit_time_str"]],
            "worst_time_after_exit": [item["worst_time_after_exit"] or item["live_exit_time_str"]],
            "additional_profit_possible": [add_profit],
            "additional_loss_possible": [add_loss],
            
            # Context
            "market_regime": [item["market_regime"]],
            "compression": [item["compression"]],
            "vfi": [item["vfi"]],
            "atr": [item["atr"]],
            "premium_decay": [item["live_exit_price"] - item["entry_price"]],
            "iv": [item["iv"]],
            "days_to_expiry": [item["days_to_expiry"]],
            "entry_signal_score": [item["entry_signal_score"]],
            
            # Versioning
            "research_epoch": [item["research_epoch"]],
            "engine_version": [item["engine_version"]],
            "strategy_version": [item["strategy_version"]],
            "parameter_version": [item["parameter_version"]],
            "git_commit": [item["git_commit"]]
        }
        
        # Write to Parquet atomically using Polars
        try:
            self.parquet_file.parent.mkdir(parents=True, exist_ok=True)
            new_df = pl.DataFrame(row_dict)
            
            if self.parquet_file.exists():
                try:
                    existing_df = pl.read_parquet(str(self.parquet_file))
                    # Align schemas
                    combined = pl.concat([existing_df, new_df])
                    combined.write_parquet(str(self.parquet_file))
                except Exception as e:
                    logger.warning(f"Failed to concat to existing parquet: {e}. Rewriting.")
                    new_df.write_parquet(str(self.parquet_file))
            else:
                new_df.write_parquet(str(self.parquet_file))
            logger.info(f"[TimeStopResearch] Saved research record to {self.parquet_file}")
        except Exception as e:
            logger.error(f"[TimeStopResearch] Error writing Parquet: {e}")

    def _save_queue(self) -> None:
        """Persists the active observations queue to disk atomically."""
        try:
            # We use our atomic helper
            write_envelope_json_atomic(str(self.queue_file), self.active_queue)
        except Exception as e:
            logger.error(f"[TimeStopResearch] Error saving queue: {e}")
            
    def _load_queue(self) -> None:
        """Loads the active observations queue from disk if present."""
        if self.queue_file.exists():
            try:
                with open(self.queue_file, 'r', encoding='utf-8') as f:
                    envelope = json.load(f)
                # Unwrap envelope
                if "payload" in envelope:
                    self.active_queue = envelope["payload"]
                    logger.info(f"[TimeStopResearch] Restored {len(self.active_queue)} active observations from queue file")
            except Exception as e:
                logger.warning(f"[TimeStopResearch] Could not restore research queue: {e}")
                
    def get_queue_health(self) -> dict:
        """Returns statistics on the research queue (Waiting, Observing, Completed, Failed)."""
        with self.queue_lock:
            observing = len(self.active_queue)
            waiting = len([q for q in self.active_queue if q.get("live_exit_time_ts", 0.0) > 0.0])
            
        completed = self.get_completed_count()
        return {
            "waiting": waiting,
            "observing": observing,
            "completed": completed,
            "failed": 0
        }
        
    def get_completed_count(self) -> int:
        """Returns the total completed samples count inside today's parquet analysis."""
        if not self.parquet_file.exists():
            return 0
        try:
            df = pl.read_parquet(str(self.parquet_file))
            return len(df)
        except Exception:
            return 0
