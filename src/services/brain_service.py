import time
import threading
import sys
import os
import uuid
import numpy as np
from pathlib import Path
os.environ["POLARS_IGNORE_TIMEZONE_PARSE_ERROR"] = "1"
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
# Added timedelta import for cleanup routine
from datetime import datetime, timedelta

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.broker import get_broker_adapter
from src.core.data_fetcher import DataFetcher
from src.strategy.indicators import append_all_indicators
from src.strategy.signal_generator import SignalGenerator
from src.execution.execution_manager import ExecutionManager
from src.core.message_bus import MessageBusPublisher, MessageBusSubscriber, FEED_PORT, CMD_PORT, EXEC_PORT
from src.utils.logger import get_logger
from src.ml_engine.gamma_event_collector import GammaEventCollector
from src.research.strike_intelligence import StrikeIntelligenceModule
from src.config.engineering_config import STRATEGY_VERSION
from src.core.decision_lifecycle import DecisionLifecycle
from src.core.market_data_cache import MarketDataCache
from src.services.time_stop_research_service import TimeStopResearchService

logger = get_logger("brain_service")

class BrainService:
    def __init__(self):
        # Initialise broker abstraction
        try:
            self.broker = get_broker_adapter()
        except Exception as e:
            logger.critical(f"[BrainService] Failed to initialise broker: {e}")
            sys.exit(1)

        # DataFetcher expects the full IBrokerGateway to be API-agnostic
        self.fetcher = DataFetcher(self.broker)
        self.signal_gen = SignalGenerator()
        
        from src.config.engineering_config import ENABLE_LIVE_BROKERAGE_EXECUTION
        if ENABLE_LIVE_BROKERAGE_EXECUTION and hasattr(self.broker, "get_order_lifecycle"):
            order_lifecycle = self.broker.get_order_lifecycle()
        else:
            from src.execution.order_lifecycle import PaperOrderLifecycle
            order_lifecycle = PaperOrderLifecycle()
            
        self.trader = ExecutionManager(self.broker, self.fetcher, [], order_lifecycle=order_lifecycle)
        self.strategy_stats = {
            "Strategy 1": {"observed": 0, "candidate": 0, "filtered": 0, "executed": 0, "rejected": 0, "expired": 0},
            "Strategy 2": {"observed": 0, "candidate": 0, "filtered": 0, "executed": 0, "rejected": 0, "expired": 0},
            "Strategy 3": {"observed": 0, "candidate": 0, "filtered": 0, "executed": 0, "rejected": 0, "expired": 0},
        }
        self.gamma_collector = GammaEventCollector()
        self.strike_intelligence = StrikeIntelligenceModule()
        
        self.anchor_token, self.anchor_symbol, self.anchor_exch = self.fetcher.get_cash_index_token()
        self.active_tokens = self.fetcher.get_active_constituents()
        self.token_list = list(self.active_tokens.values())
        
        # ZeroMQ Setup
        self.cmd_pub = MessageBusPublisher(CMD_PORT)
        self.exec_pub = MessageBusPublisher(EXEC_PORT)
        
        # Subscribe to Index and Options (and optionally all constituents if we calculate volume here)
        self.feed_sub = MessageBusSubscriber(FEED_PORT, topics=[f"TICK.{t}" for t in self.token_list] + [f"TICK.{self.anchor_token}"])
        
        # State
        self.cached_volume_df = None
        self.cached_price_df = None
        self.current_df = None
        
        # Async Fetch Architecture
        self._df_lock = threading.RLock()
        self._last_fetch_time = 0
        
        self.current_minute_volume_tracker = {}
        self.last_known_vtt = {}
        self.live_volume_minute = datetime.now().minute
        self.live_tracking_minute = datetime.now().minute
        
        self.live_ltp = None
        self.live_open = None
        self.live_high = None
        self.live_low = None
        
        self.order_flow = {
            "token": None, "buy_vol": 0, "sell_vol": 0, "delta": 0, "last_price": 0, "last_was_buy": True
        }
        
        self.subscribed_option = None
        self.subscribed_options_set = set()
        self.market_data_cache = MarketDataCache()
        self.research_service = TimeStopResearchService(self.market_data_cache, exec_pub=self.exec_pub)
        self.tick_seq_counter = 0
        self.prev_ltp_cache = {}
        self.logic_eval_times = []
        self.feed_active_logged = False
        
        self.tracked_options = {}
        self.last_option_refresh = 0
        self.last_saved_indicator_minute = -1  # Tracks last minute we archived indicators

    def publish_notification(self, event_type, severity, title, description, correlation_id="", strategy="--", instrument="--", premium=None, pnl=None):
        try:
            import uuid
            from src.utils.provenance import get_provenance_metadata
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
                    "event_type": event_type,
                    "severity": severity,
                    "title": title,
                    "description": description,
                    "timestamp": int(time.time() * 1000),
                    "correlation_id": correlation_id,
                    "strategy": strategy,
                    "instrument": instrument,
                    "premium": premium,
                    "pnl": pnl,
                    "status": "Generated"
                }
            }
            self.exec_pub.publish("EXEC.EVENT", envelope)
        except Exception as e:
            logger.error(f"[BrainService] Failed to publish notification: {e}")

    def boot_sequence(self):
        logger.info("=== BOOT: Bootstrapping Brain from Local Disk Cache (Trailing 2-Day Indicator Stream) ===")
        try:
            from src.ml_engine.ml_db import init_ml_db
            init_ml_db(recreate=False)

            from src.config.engineering_config import INSTITUTIONAL_MEMORY_DIR
            from pathlib import Path
            import pyarrow.parquet as pq
            import pandas as pd

            stream_dir = Path(INSTITUTIONAL_MEMORY_DIR) / "indicator_stream"

            dfs = []
            if stream_dir.exists():
                all_files = sorted(list(stream_dir.rglob("*.parquet")))
                for pf in all_files:
                    try:
                        df = pd.read_parquet(pf)
                        dfs.append(df)
                    except Exception as e:
                        logger.warning(f"Failed to read parquet file {pf}: {e}")

            if dfs:
                boot_df = pd.concat(dfs, ignore_index=True)
                boot_df['timestamp'] = pd.to_datetime(boot_df['timestamp'])
                boot_df = boot_df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
                
                # Keep only last 2 days of trading data (~750 minutes)
                boot_df = boot_df.tail(750).reset_index(drop=True)
                
                # 1GB Memory Optimization: Downcast 64-bit to 32-bit types
                fcols = boot_df.select_dtypes('float').columns
                icols = boot_df.select_dtypes('integer').columns
                boot_df[fcols] = boot_df[fcols].astype('float32')
                boot_df[icols] = boot_df[icols].astype('int32')
                
                logger.info(f"=== BOOT: Loaded {len(boot_df)} historical rows from local disk ===")
                
                self.cached_volume_df = boot_df.set_index('timestamp')[['synth_vol']]
                self.cached_price_df = boot_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                
                with self._df_lock:
                    self.current_df = boot_df
                
                logger.info("=== BOOT COMPLETE: Engine Online from Local Disk ===")
                
                # Run an initial cleanup on boot
                self._cleanup_old_indicator_streams(datetime.now())
            else:
                logger.warning("=== BOOT WARNING: No local disk cache found. Checking if REST fetch is needed... ===")
                # Guard: Only fetch from REST API ONCE per calendar day.
                # If the machine reboots mid-session, the indicator_stream will already
                # have today's candles saved to disk (from the previous session run), so
                # the `if dfs:` branch above will handle it. This path only runs on the
                # VERY FIRST boot of the day (e.g., pre-market or after overnight cleanup).
                # Calling get_historical_candles_with_synthetic_volume fetches 50+ REST
                # calls (all Nifty constituents). Doing this on every reboot would starve
                # the exit strategy of its API quota.
                today_str = datetime.now().strftime("%Y-%m-%d")
                boot_stamp_file = Path(INSTITUTIONAL_MEMORY_DIR) / "indicator_stream" / f".boot_fetched_{today_str}"

                if boot_stamp_file.exists():
                    logger.warning(f"=== BOOT: REST fetch already done today ({today_str}). Skipping to protect exit strategy API quota. Starting with empty warmup. ===")
                    # The session had data earlier but it's been cleaned/lost mid-session.
                    # Start blank — indicators warm up over 130 bars from live ticks.
                    empty_df = pd.DataFrame({
                        'timestamp': pd.Series(dtype='datetime64[ns]'),
                        'open': pd.Series(dtype='float32'),
                        'high': pd.Series(dtype='float32'),
                        'low': pd.Series(dtype='float32'),
                        'close': pd.Series(dtype='float32'),
                        'synth_vol': pd.Series(dtype='int32')
                    })
                    self.cached_volume_df = empty_df.set_index('timestamp')[['synth_vol']]
                    self.cached_price_df = empty_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                    with self._df_lock:
                        self.current_df = empty_df
                    logger.info("=== BOOT COMPLETE: Engine Online (Warmup Mode — REST quota protected) ===")
                else:
                    # First boot of the day — safe to make the 50-constituent REST fetch.
                    logger.warning("=== BOOT: First boot of day. Fetching full historical data from broker REST API (runs once/day only)... ===")
                    try:
                        live_df = self.fetcher.get_historical_candles_with_synthetic_volume(days_back=2)
                        if not live_df.empty:
                            live_df['timestamp'] = pd.to_datetime(live_df['timestamp'])
                            live_df = live_df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
                            live_df = live_df.tail(750).reset_index(drop=True)

                            if 'volume' in live_df.columns and 'synth_vol' not in live_df.columns:
                                live_df['synth_vol'] = live_df['volume']
                            elif 'synth_vol' not in live_df.columns:
                                live_df['synth_vol'] = 0

                            fcols = live_df.select_dtypes('float').columns
                            icols = live_df.select_dtypes('integer').columns
                            live_df[fcols] = live_df[fcols].astype('float32')
                            live_df[icols] = live_df[icols].astype('int32')

                            self.cached_volume_df = live_df.set_index('timestamp')[['synth_vol']]
                            self.cached_price_df = live_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                            with self._df_lock:
                                self.current_df = live_df

                            # Write the daily stamp so mid-session reboots skip this fetch
                            boot_stamp_file.parent.mkdir(parents=True, exist_ok=True)
                            boot_stamp_file.touch()
                            logger.info(f"=== BOOT COMPLETE: Engine Online from Live REST Fetch ({len(live_df)} bars, synth_vol ready) ===")
                        else:
                            raise ValueError("Empty DataFrame from historical fetch")
                    except Exception as fetch_err:
                        logger.warning(f"=== BOOT: Live historical fetch failed ({fetch_err}). Starting with empty DataFrame — VWAP/VFI will warm up over ~130 bars. ===")
                        empty_df = pd.DataFrame({
                            'timestamp': pd.Series(dtype='datetime64[ns]'),
                            'open': pd.Series(dtype='float32'),
                            'high': pd.Series(dtype='float32'),
                            'low': pd.Series(dtype='float32'),
                            'close': pd.Series(dtype='float32'),
                            'synth_vol': pd.Series(dtype='int32')
                        })
                        self.cached_volume_df = empty_df.set_index('timestamp')[['synth_vol']]
                        self.cached_price_df = empty_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                        with self._df_lock:
                            self.current_df = empty_df
                        logger.info("=== BOOT COMPLETE: Engine Online (Fresh Start, no historical data) ===")



        except Exception as e:
            logger.critical(f"BOOT ERROR: {e}")
            sys.exit(1)

    def _cleanup_old_indicator_streams(self, now: datetime):
        """Maintains a trailing 2-day window of indicator_stream parquets on disk"""
        try:
            from src.config.engineering_config import INSTITUTIONAL_MEMORY_DIR
            from pathlib import Path
            stream_dir = Path(INSTITUTIONAL_MEMORY_DIR) / "indicator_stream"
            
            if not stream_dir.exists():
                return
                
            # Files older than 2 days
            cutoff = now - timedelta(days=2)
            cleaned_count = 0
            
            for pf in stream_dir.rglob("*.parquet"):
                if pf.stat().st_mtime < cutoff.timestamp():
                    pf.unlink(missing_ok=True)
                    cleaned_count += 1
            
            if cleaned_count > 0:
                logger.info(f"[Cleanup] Deleted {cleaned_count} old indicator stream files to save VPS disk space.")
        except Exception as e:
            logger.error(f"Failed to cleanup old indicator streams: {e}")

    def _save_indicator_snapshot(self, now: datetime):
        """
        Saves the last CLOSED candle (with all indicators: VWAP, EMA, VFI, ATR etc.)
        to the indicator_stream Parquet Data Lake every minute.
        This solves the critical gap where VFI/EMA/VWAP are computed but never persisted.
        """
        try:
            if self.current_df is None or len(self.current_df) < 2:
                return

            # Take the second-to-last row — last CLOSED candle (not the live virtual one)
            closed_candle = self.current_df.iloc[-2].to_dict()

            # Add provenance metadata
            closed_candle['saved_at'] = now.isoformat()
            closed_candle['anchor_symbol'] = self.anchor_symbol
            
            from src.utils.provenance import get_provenance_metadata
            import json
            prov = get_provenance_metadata()
            closed_candle['schema_version'] = prov['schema_version']
            closed_candle['git_commit'] = prov['git_commit']
            closed_candle['git_branch'] = prov['git_branch']
            closed_candle['git_dirty'] = prov['git_dirty']
            closed_candle['strategy_hash'] = prov['strategy_hash']
            closed_candle['feature_schema_version'] = prov['feature_schema_version']
            closed_candle['dataset_schema_version'] = prov['dataset_schema_version']
            closed_candle['feature_lineage_json'] = json.dumps(prov['feature_lineage'])

            # Convert timestamp to string if it's a Timestamp object
            if hasattr(closed_candle.get('timestamp'), 'isoformat'):
                closed_candle['timestamp'] = str(closed_candle['timestamp'])

            # Fix 3: Persist the synth_vol that was actually used for VWAP/VFI computation.
            # current_df has OHLCV + indicator columns but synth_vol lives in cached_volume_df.
            # Without this, a reboot will reload indicator snapshots with no volume data,
            # causing VWAP to be unweighted (wrong) and VFI to be near-zero.
            if 'synth_vol' not in closed_candle or closed_candle.get('synth_vol', 0) == 0:
                try:
                    closed_ts = pd.Timestamp(closed_candle['timestamp'])
                    with self._df_lock:
                        vol_df_snap = self.cached_volume_df
                    if vol_df_snap is not None and not vol_df_snap.empty:
                        # Match by nearest timestamp
                        if closed_ts in vol_df_snap.index:
                            closed_candle['synth_vol'] = int(vol_df_snap.at[closed_ts, 'synth_vol'])
                        else:
                            # Fallback: nearest minute
                            nearest = vol_df_snap.index.asof(closed_ts)
                            if pd.notna(nearest):
                                closed_candle['synth_vol'] = int(vol_df_snap.at[nearest, 'synth_vol'])
                            else:
                                closed_candle['synth_vol'] = 0
                    else:
                        closed_candle['synth_vol'] = 0
                except Exception:
                    closed_candle['synth_vol'] = 0

            df = pd.DataFrame([closed_candle])


            # Save to: INSTITUTIONAL_MEMORY_DIR/indicator_stream/YYYY/MM/DD/indicators_HHMM.parquet
            date_str = now.strftime("%Y/%m/%d")
            from src.config.engineering_config import INSTITUTIONAL_MEMORY_DIR
            save_dir = Path(INSTITUTIONAL_MEMORY_DIR) / "indicator_stream" / date_str
            save_dir.mkdir(parents=True, exist_ok=True)

            file_name = f"indicators_{now.strftime('%H%M')}.parquet"
            save_path = save_dir / file_name

            table = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(table, save_path, compression="zstd")
            
            # Run trailing cleanup once an hour
            if now.minute == 0:
                self._cleanup_old_indicator_streams(now)

        except Exception as e:
            logger.warning(f"[IndicatorStream] Could not save snapshot: {e}")

    def subscribe_options(self, tokens, exchange="NFO"):
        """Sends command to FeedService to subscribe to options"""
        if not tokens: return
        self.cmd_pub.publish("CMD.SUBSCRIBE", {"tokens": tokens, "exchange": exchange})
        # Add ZMQ subscriptions so Brain receives them
        for tk in tokens:
            import zmq
            self.feed_sub.socket.setsockopt_string(zmq.SUBSCRIBE, f"TICK.{tk}")

    def on_tick(self, topic, message):
        """Callback for incoming ZMQ ticks"""
        now = datetime.now()
        is_market_open = (now.hour == 9 and now.minute >= 15) or (9 < now.hour < 15) or (now.hour == 15 and now.minute <= 30)
        
        token = message.get('token')
        if token: token = str(token)
        ltq = message.get('last_traded_quantity', 0)
        ltp = message.get('last_traded_price', 0)
        vtt = message.get('volume_trade_for_the_day', 0)
        
        # 1. Minute Rollover for Synthetic Volume + Candle Promotion
        # When the minute changes, the previous virtual candle is now a CLOSED candle.
        # We promote it directly into cached_price_df and cached_volume_df from live
        # WebSocket data — no REST call needed at all.
        if now.minute != self.live_volume_minute:
            total_vol = sum(self.current_minute_volume_tracker.values())
            ts = pd.Timestamp(now.replace(minute=self.live_volume_minute, second=0, microsecond=0))
            if self.cached_volume_df is not None and getattr(self.cached_volume_df.index, 'tz', None) is not None:
                ts = ts.tz_localize(self.cached_volume_df.index.tz)
                
            new_row = pd.DataFrame({'timestamp': [ts], 'synth_vol': [total_vol]}).set_index('timestamp')
            
            if self.cached_volume_df is not None:
                self.cached_volume_df = new_row.combine_first(self.cached_volume_df)
            else:
                self.cached_volume_df = new_row
            
            # Promote closed OHLC candle into cached_price_df from the virtual candle data.
            # This keeps cached_price_df current without any REST API calls.
            if self.live_open and self.live_high and self.live_low and self.live_ltp:
                closed_price_row = pd.DataFrame({
                    'open':  [float(self.live_open)],
                    'high':  [float(self.live_high)],
                    'low':   [float(self.live_low)],
                    'close': [float(self.live_ltp)]
                }, index=pd.Index([ts], name='timestamp'))
                if self.cached_price_df is not None:
                    self.cached_price_df = closed_price_row.combine_first(self.cached_price_df)
                else:
                    self.cached_price_df = closed_price_row
                
            for t, vol in self.current_minute_volume_tracker.items():
                self.last_known_vtt[t] = self.last_known_vtt.get(t, 0) + vol
                
            self.current_minute_volume_tracker = {}
            self.live_volume_minute = now.minute
            self.live_open = None
            self.live_high = None
            self.live_low = None

        # 2. Accumulate Volume
        if token and token in self.token_list and vtt > 0 and is_market_open:
            if token not in self.last_known_vtt:
                self.last_known_vtt[token] = vtt
            minute_vol = vtt - self.last_known_vtt[token]
            self.current_minute_volume_tracker[token] = max(0, minute_vol)
            
        # 3. Anchor Token (Index) Tracking
        if token == self.anchor_token and ltp > 0:
            self.live_ltp = float(ltp)
            if self.live_open is None: self.live_open = self.live_ltp
            if self.live_high is None or self.live_ltp > self.live_high: self.live_high = self.live_ltp
            if self.live_low is None or self.live_ltp < self.live_low: self.live_low = self.live_ltp
            
        # 4. Tracked Options for Gamma Collector
        if token in self.tracked_options and ltp > 0:
            opt_price = float(ltp)
            opt_details = self.tracked_options[token]
            best_bid = float(message.get('bid', 0.0))
            best_ask = float(message.get('ask', 0.0))
            
            if not best_bid and 'best_5_buy_data' in message and len(message['best_5_buy_data']) > 0:
                best_bid = float(message['best_5_buy_data'][0].get('price', 0)) / 100
            if not best_ask and 'best_5_sell_data' in message and len(message['best_5_sell_data']) > 0:
                best_ask = float(message['best_5_sell_data'][0].get('price', 0)) / 100
                
            opt_details["bid"] = best_bid
            opt_details["ask"] = best_ask
            opt_details["spread"] = round(best_ask - best_bid, 2) if best_ask > best_bid else 0.0
            
            self.exec_pub.publish("EXEC.OPTION_TICK", {
                "symbol": opt_details["symbol"],
                "price": opt_price,
                "index_price": self.live_ltp if self.live_ltp else 0.0,
                "market_state": self.get_current_market_state(),
                "option_details": opt_details,
                "exchange_timestamp": message.get("exchange_timestamp") or message.get("exch_time")
            })
            
            try:
                self.gamma_collector.feed_tick(
                    symbol=opt_details["symbol"],
                    price=opt_price,
                    index_price=self.live_ltp if self.live_ltp else 0.0,
                    market_state=self.get_current_market_state(),
                    option_details=opt_details,
                    exchange_timestamp=message.get("exchange_timestamp") or message.get("exch_time")
                )
            except Exception as e:
                logger.error(f"Gamma collector error: {e}")

        # 5. QOT Live Tape & Cache Updates
        if ltp > 0:
            ltp_val = float(ltp)
            symbol_name = message.get("symbol") or (self.anchor_symbol if token == self.anchor_token else (self.tracked_options[token]["symbol"] if token in self.tracked_options else token))
            
            self.tick_seq_counter += 1
            
            # Latency
            exchange_time = message.get("exchange_timestamp") or message.get("exch_time")
            latency_ms = 0
            if exchange_time:
                try:
                    if isinstance(exchange_time, str):
                        try:
                            dt = datetime.strptime(exchange_time, "%Y-%m-%d %H:%M:%S")
                            latency_ms = int((datetime.now() - dt).total_seconds() * 1000)
                        except: pass
                except: pass
                    
            # Direction and Spread
            tick_dir = "NEUTRAL"
            best_bid = float(message.get('bid', 0.0))
            best_ask = float(message.get('ask', 0.0))
            if not best_bid and 'best_5_buy_data' in message and len(message['best_5_buy_data']) > 0:
                best_bid = float(message['best_5_buy_data'][0].get('price', 0)) / 100
            if not best_ask and 'best_5_sell_data' in message and len(message['best_5_sell_data']) > 0:
                best_ask = float(message['best_5_sell_data'][0].get('price', 0)) / 100
                
            if best_ask > 0.0 and ltp_val >= best_ask:
                tick_dir = "UP"
            elif best_bid > 0.0 and ltp_val <= best_bid:
                tick_dir = "DOWN"
            else:
                last_price = self.order_flow["last_price"] if token == self.subscribed_option else (self.live_ltp if token == self.anchor_token else ltp_val)
                if ltp_val > last_price:
                    tick_dir = "UP"
                elif ltp_val < last_price:
                    tick_dir = "DOWN"
                    
            # Calculate general delta volume for the tape
            tick_ltq = message.get("last_traded_quantity", 0)
            
            self.exec_pub.publish("EXEC.TICK", {
                "timestamp": int(time.time() * 1000),
                "instrument": symbol_name,
                "ltp": ltp_val,
                "price_change": round((ltp_val - float(message.get("close", ltp_val))) / float(message.get("close", ltp_val)) * 100, 2) if float(message.get("close", 1)) > 0 else 0.0,
                "delta_volume": tick_ltq,
                "tick_direction": tick_dir,
                "bid": best_bid,
                "ask": best_ask,
                "spread": round(best_ask - best_bid, 2) if best_ask > best_bid else 0.0,
                "tick_seq": self.tick_seq_counter,
                "latency": latency_ms
            })      
            # Price change
            price_change = 0.0
            if symbol_name in self.prev_ltp_cache:
                price_change = ltp_val - self.prev_ltp_cache[symbol_name]
            self.prev_ltp_cache[symbol_name] = ltp_val
            
            # Update cache
            self.market_data_cache.update_tick(
                token=token,
                symbol=symbol_name,
                exchange=message.get("exchange", "NSE" if token == self.anchor_token else "NFO"),
                ltp=ltp_val,
                bid=best_bid,
                ask=best_ask,
                volume=ltq,
                seq=self.tick_seq_counter,
                latency=latency_ms,
                direction=tick_dir
            )
            
            # Publish EXEC.TICK
            if not self.feed_active_logged and symbol_name == self.anchor_symbol:
                self.publish_notification(
                    event_type="FEED_RESTORED",
                    severity="SUCCESS",
                    title="Feed Restored",
                    description=f"{symbol_name} Tick Stream Active",
                    instrument=symbol_name
                )
                self.feed_active_logged = True
            
            self.exec_pub.publish("EXEC.TICK", {
                "timestamp": int(time.time() * 1000),
                "instrument": symbol_name,
                "ltp": ltp_val,
                "price_change": round(price_change, 2),
                "delta_volume": ltq,
                "tick_direction": tick_dir,
                "bid": best_bid,
                "ask": best_ask,
                "spread": round(best_ask - best_bid, 2) if best_ask > best_bid else 0.0,
                "tick_seq": self.tick_seq_counter,
                "latency": latency_ms
            })

        # 5. Order Flow / Delta Tracking for Active Option
        if self.subscribed_option == token and ltp > 0:
            live_opt_ltp = float(ltp)
            if self.trader.trade_context and token == self.trader.trade_context['token']:
                # Update UI via exec port if needed
                pass
                
            if self.order_flow["token"] != token:
                self.order_flow = {"token": token, "buy_vol": 0, "sell_vol": 0, "delta": 0, "last_price": live_opt_ltp, "last_was_buy": True}
            elif ltq > 0 and is_market_open:
                prev_price = self.order_flow["last_price"]
                best_ask = 0
                best_bid = float(message.get('bid', 0.0))
                best_ask = float(message.get('ask', 0.0))
                
                bid_data = message.get('best_5_buy_data', [])
                sell_data = message.get('best_5_sell_data', [])
                
                if not best_bid and bid_data and isinstance(bid_data, list) and len(bid_data) > 0:
                    best_bid = float(bid_data[0].get('price', 0)) / 100
                if not best_ask and sell_data and isinstance(sell_data, list) and len(sell_data) > 0:
                    best_ask = float(sell_data[0].get('price', 0)) / 100
                    
                is_buy = False
                if best_ask > 0 and live_opt_ltp >= best_ask: is_buy = True
                elif best_bid > 0 and live_opt_ltp <= best_bid: is_buy = False
                else:
                    if live_opt_ltp > prev_price: is_buy = True
                    elif live_opt_ltp < prev_price: is_buy = False
                    else: is_buy = self.order_flow.get("last_was_buy", True)

                if is_buy:
                    self.order_flow["buy_vol"] += ltq
                    self.order_flow["delta"] += ltq
                else:
                    self.order_flow["sell_vol"] += ltq
                    self.order_flow["delta"] -= ltq
                    
                self.order_flow["last_price"] = live_opt_ltp
                self.order_flow["last_was_buy"] = is_buy

    def get_current_market_state(self):
        if self.current_df is not None and not self.current_df.empty:
            latest = self.current_df.iloc[-1]
            return {
                "regime": int(latest.get("market_regime", 0)),
                "atr": float(latest.get("atr", 0.0)),
                "atr_expansion": float(latest.get("atr_expansion", 1.0)),
                "compression": float(latest.get("compression", 0.0))
            }
        return {}

    def execute_logic_loop(self):
        """Runs on a separate thread to poll historical data and trigger logic."""
        # Wait for boot
        while self.cached_price_df is None:
            time.sleep(1)

        # ── ONE-TIME BOOT GAP FILL ──────────────────────────────────────────────
        # If indicator_stream had data from disk, there may be a gap between the
        # last saved candle and now (e.g., machine was off overnight or rebooted
        # mid-session). Fill that gap with a SINGLE REST call — price only, no
        # constituent volume fetch. This runs ONCE at startup and never again.
        # Volume for gap bars will be 0 (those bars won't affect VWAP weighting).
        try:
            if self.cached_price_df is not None and not self.cached_price_df.empty:
                last_ts = self.cached_price_df.index.max()
                now_ts_dt = datetime.now()
                gap_minutes = int((now_ts_dt - last_ts.replace(tzinfo=None)).total_seconds() / 60)
                if 1 <= gap_minutes <= 500:  # Fill gaps of 1 minute or more
                    logger.info(f"[BootGapFill] Gap detected: {gap_minutes} min since last candle ({last_ts}). Fetching missing price candles...")
                    from datetime import timedelta
                    gap_start = last_ts.replace(tzinfo=None) + timedelta(minutes=1)
                    gap_df = self.fetcher.get_historical_candles(
                        self.anchor_exch, self.anchor_token, "ONE_MINUTE",
                        minutes_back=gap_minutes + 2
                    )
                    if not gap_df.empty:
                        gap_df['timestamp'] = pd.to_datetime(gap_df['timestamp'])
                        # FIX: Use >= instead of > so we do not drop the first missing candle!
                        gap_df = gap_df[gap_df['timestamp'] >= pd.Timestamp(gap_start)]
                        if not gap_df.empty:
                            gap_price = gap_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                            
                            with self._df_lock:
                                self.cached_price_df = gap_price.combine_first(self.cached_price_df)
                                
                                # FIX: Also splice the gap into cached_volume_df with 0 volume 
                                # so that VWAP logic has a clean dataset without NaNs.
                                gap_vol = pd.DataFrame(index=gap_price.index)
                                gap_vol['synth_vol'] = 0
                                if self.cached_volume_df is not None:
                                    self.cached_volume_df = gap_vol.combine_first(self.cached_volume_df)
                                else:
                                    self.cached_volume_df = gap_vol
                                    
                            logger.info(f"[BootGapFill] Spliced {len(gap_df)} missing candles. Indicator chain is seamless.")
        except Exception as e:
            logger.warning(f"[BootGapFill] Gap fill failed (non-critical): {e}")
        # ────────────────────────────────────────────────────────────────────────

        while True:
            now = datetime.now()
            is_market_open = (now.hour == 9 and now.minute >= 15) or (9 < now.hour < 15) or (now.hour == 15 and now.minute <= 30)
            
            if is_market_open and self.live_ltp is not None:
                now_ts = time.time()
                
                try:
                    with self._df_lock:
                        if self.cached_price_df is not None and self.cached_volume_df is not None:
                            price_df = self.cached_price_df.copy().join(self.cached_volume_df, how='left')
                            price_df['volume'] = price_df['synth_vol'].fillna(0).astype(int)
                            price_df = price_df.drop(columns=['synth_vol']).reset_index()
                            
                            # Inject Virtual Candle
                            live_ts = pd.Timestamp(now.replace(second=0, microsecond=0))
                            # Guard against duplicate columns before accessing .dtype
            if price_df.columns.duplicated().any():
                price_df = price_df.loc[:, ~price_df.columns.duplicated()]

            ts_col = price_df['timestamp']
            if isinstance(ts_col, pd.DataFrame):
                ts_col = ts_col.iloc[:, 0]

            if getattr(ts_col.dtype, 'tz', None) is not None:
                                live_ts = live_ts.tz_localize(price_df['timestamp'].dtype.tz)
                                
                            live_vol = sum(self.current_minute_volume_tracker.values())
                            
                            if not (price_df['timestamp'] == live_ts).any():
                                price_df.loc[len(price_df)] = {
                                    'timestamp': live_ts,
                                    'open': self.live_open if self.live_open else self.live_ltp,
                                    'high': self.live_high if self.live_high else self.live_ltp,
                                    'low': self.live_low if self.live_low else self.live_ltp,
                                    'close': self.live_ltp,
                                    'volume': live_vol
                                }
                            else:
                                idx = price_df[price_df['timestamp'] == live_ts].index[-1]
                                price_df.at[idx, 'close'] = self.live_ltp
                                price_df.at[idx, 'volume'] = max(price_df.at[idx, 'volume'], live_vol)
                                if self.live_high: price_df.at[idx, 'high'] = max(price_df.at[idx, 'high'], self.live_high)
                                if self.live_low: price_df.at[idx, 'low'] = min(price_df.at[idx, 'low'], self.live_low)
                            
                            self.current_df = append_all_indicators(price_df)

                            # ── INDICATOR STREAM ARCHIVAL (G1 Fix) ──────────────
                            # Save last closed candle with VFI/EMA/VWAP to Parquet
                            # once per minute at the minute boundary.
                            if now.minute != self.last_saved_indicator_minute:
                                self._save_indicator_snapshot(now)
                                self.last_saved_indicator_minute = now.minute
                            # ────────────────────────────────────────────────────

                            # Refresh Option Universe
                            if now_ts - self.last_option_refresh >= 60:
                                index_name, exch_seg = self.fetcher.get_active_instrument()
                                step = 100 if index_name == "SENSEX" else 50
                                atm_strike = round(self.live_ltp / step) * step
                                weekly_opts = self.fetcher.get_weekly_option_tokens()
                                if not weekly_opts.empty:
                                    target_strikes = [atm_strike + i * step for i in range(-3, 4)]
                                    tracked = {}
                                    tokens_to_sub = []
                                    for strike_val in target_strikes:
                                        strike_scaled = int(strike_val * 100)
                                        for opt_type in ["CE", "PE"]:
                                            match = weekly_opts[(weekly_opts['strike'].astype(float).astype(int) == strike_scaled) & (weekly_opts['symbol'].str.endswith(opt_type))]
                                            if not match.empty:
                                                row = match.iloc[0]
                                                tk = str(row['token'])
                                                symbol = str(row['symbol'])
                                                
                                                try:
                                                    expiry_dt = pd.to_datetime(row['expiry'], format='%d%b%Y')
                                                    dte = (expiry_dt.date() - datetime.now().date()).days
                                                except:
                                                    dte = 0
                                                    
                                                tracked[tk] = {
                                                    "token": tk, "symbol": symbol, "strike": float(row['strike']) / 100,
                                                    "option_type": opt_type, "index_name": index_name,
                                                    "distance": int(abs(strike_val - atm_strike) / step),
                                                    "dte": max(0, dte), "expiry": str(row['expiry'])
                                                }
                                                tokens_to_sub.append(tk)
                                    
                                    self.tracked_options = tracked
                                    self.cmd_pub.publish("CMD.SUBSCRIBE", {"tokens": tokens_to_sub, "exchange": "NFO"})
                                    
                                    # Safely queue subscriptions to the feed thread
                                    for tk in tokens_to_sub:
                                        self.feed_sub.add_subscription(f"TICK.{tk}")
                                        
                                    # H2: Pre-cache LTPs for Trader asynchronously
                                    def prefetch_options(tokens):
                                        try:
                                            cache = {}
                                            for token in tokens:
                                                res = self.broker.market_data_provider.get_quote(exch_seg, token)
                                                if res and res.get('ltp', 0.0) > 0:
                                                    cache[token] = res['ltp']
                                            if cache:
                                                self.trader.update_option_cache(cache)
                                        except Exception as e:
                                            logger.debug(f"Option prefetch error: {e}")
                                            
                                    threading.Thread(target=prefetch_options, args=(tokens_to_sub,), daemon=True).start()
                                
                                self.last_option_refresh = now_ts
                                
                except Exception as e:
                    logger.error(f"[BrainService] Error in loop: {e}")
                    
                # Signal Generation & Execution
                if self.current_df is not None:
                    was_pending = self.trader.pending_setup is not None
                    pending_signal = self.trader.pending_setup.copy() if was_pending else None
                    was_trade = self.trader.trade_context is not None
                    
                    t0 = time.time()
                    
                    # ── GAP 1 FIX: ALWAYS EVALUATE SIGNALS DURING TRADING WINDOW ──
                    is_trading_window = (now.hour > 9 or (now.hour == 9 and now.minute >= 16)) and (now.hour < 15 or (now.hour == 15 and now.minute < 15))
                    is_stale = (now_ts - self._last_fetch_time) > 180  # 3 minutes stale
                    
                    if is_trading_window:
                        if is_stale:
                            signal, decision_state = None, {
                                "human_reason": f"Data stale by {int(now_ts - self._last_fetch_time)}s. Degraded mode.",
                                "machine_state": {},
                                "rule_evaluations": []
                            }
                        elif self.trader.cooldown_until and now < self.trader.cooldown_until:
                            signal, decision_state = None, {
                                "human_reason": f"Active Cooldown until {self.trader.cooldown_until.strftime('%H:%M:%S')}",
                                "machine_state": {},
                                "rule_evaluations": []
                            }
                        else:
                            # Increment Observed counts
                            self.strategy_stats["Strategy 1"]["observed"] += 1
                            self.strategy_stats["Strategy 2"]["observed"] += 1
                            self.strategy_stats["Strategy 3"]["observed"] += 1
                            
                            triggered_strategy = None
                            
                            s1_sig, s1_state = self.signal_gen.check_signal(self.current_df, generate_trace=True)
                            if s1_sig:
                                triggered_strategy = "Strategy 1"
                                self.strategy_stats["Strategy 1"]["candidate"] += 1
                                self.strategy_stats["Strategy 2"]["rejected"] += 1
                                self.strategy_stats["Strategy 3"]["rejected"] += 1
                                signal, decision_state = s1_sig, s1_state
                            else:
                                self.strategy_stats["Strategy 1"]["rejected"] += 1
                                
                                s2_sig, s2_state = self.signal_gen.check_rejection_signal(self.current_df, generate_trace=True)
                                if s2_sig:
                                    triggered_strategy = "Strategy 2"
                                    self.strategy_stats["Strategy 2"]["candidate"] += 1
                                    self.strategy_stats["Strategy 3"]["rejected"] += 1
                                    signal, decision_state = s2_sig, s2_state
                                else:
                                    self.strategy_stats["Strategy 2"]["rejected"] += 1
                                    
                                    s3_sig, s3_state = self.signal_gen.check_vwap_band_breakout(self.current_df, generate_trace=True)
                                    if s3_sig:
                                        triggered_strategy = "Strategy 3"
                                        self.strategy_stats["Strategy 3"]["candidate"] += 1
                                        signal, decision_state = s3_sig, s3_state
                                    else:
                                        self.strategy_stats["Strategy 3"]["rejected"] += 1
                                        signal, decision_state = None, s3_state
                                        
                                        strat1_reason = s1_state.get("human_reason", "Strategy 1 failed")
                                        strat2_reason = s2_state.get("human_reason", "Strategy 2 failed")
                                        strat3_reason = s3_state.get("human_reason", "Strategy 3 failed")
                                        decision_state["human_reason"] = f"S1: {strat1_reason} | S2: {strat2_reason} | S3: {strat3_reason}"
                                        
                                        # Combine rule evaluations from all strategies if they didn't trigger
                                        combined_rules = []
                                        combined_rules.extend(s1_state.get("rule_evaluations", []))
                                        combined_rules.extend(s2_state.get("rule_evaluations", []))
                                        combined_rules.extend(s3_state.get("rule_evaluations", []))
                                        decision_state["rule_evaluations"] = combined_rules
                                        
                                        decision_state["machine_state"]["strategy_1_state"] = s1_state.get("machine_state", {})
                                        decision_state["machine_state"]["strategy_2_state"] = s2_state.get("machine_state", {})
                                        decision_state["machine_state"]["strategy_3_state"] = s3_state.get("machine_state", {})
                        
                        latest = self.current_df.iloc[-1]
                        
                        # Fix Gap 5: Enforce exact string format match with Canonical Collector for deterministic UUID5
                        clean_ts = pd.Timestamp(latest['timestamp']).replace(second=0, microsecond=0)
                        observation_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(clean_ts)))
                        
                        decision_uuid = str(uuid.uuid4())
                        
                        if signal and triggered_strategy:
                            signal["strategy_name"] = triggered_strategy
                            self.publish_notification(
                                event_type="CANDIDATE_CREATED",
                                severity="INFO",
                                title="Candidate Created",
                                description=f"Candidate Created for {triggered_strategy}",
                                correlation_id=decision_uuid[:8],
                                strategy=triggered_strategy
                            )
                            
                        # Determine the decision status, noting if we ignored a valid signal due to current state
                        if signal:
                            if self.trader.trade_context is not None:
                                decision_status = "IGNORED_OPEN_TRADE"
                                lifecycle_stage = DecisionLifecycle.FILTERED.value
                                if triggered_strategy:
                                    self.strategy_stats[triggered_strategy]["filtered"] += 1
                            elif self.trader.pending_setup is not None:
                                decision_status = "IGNORED_SNIPER_MODE"
                                lifecycle_stage = DecisionLifecycle.FILTERED.value
                                if triggered_strategy:
                                    self.strategy_stats[triggered_strategy]["filtered"] += 1
                            else:
                                decision_status = "ACCEPTED"
                                lifecycle_stage = DecisionLifecycle.CANDIDATE.value
                        else:
                            decision_status = "REJECTED"
                            lifecycle_stage = DecisionLifecycle.OBSERVED.value
                        
                        # Logic evaluation stopwatch end
                        eval_ms = (time.time() - t0) * 1000.0
                        self.logic_eval_times.append(eval_ms)
                        if len(self.logic_eval_times) > 1000:
                            self.logic_eval_times.pop(0)
                        
                        # Build conditional trace payload (Level 0 vs Level 1)
                        if lifecycle_stage == DecisionLifecycle.OBSERVED.value:
                            # Level 0: Minimal observation row
                            decision_payload = {
                                "decision_uuid": decision_uuid,
                                "observation_uuid": observation_uuid,
                                "timestamp": datetime.now().isoformat(),
                                "market_session_id": datetime.now().strftime("%Y-%m-%d"),
                                "decision_action": "NONE",
                                "status": decision_status,
                                "lifecycle_stage": lifecycle_stage,
                                "decision_contract_version": "1.0.0",
                                "strategy_version": STRATEGY_VERSION,
                                "evaluation_time_ms": round(eval_ms, 2),
                                "market_state": {
                                    "vfi": float(latest.get('vfi', 0)),
                                    "vwap": float(latest.get('vwap', 0)),
                                    "ema_9": float(latest.get('ema_9', 0)),
                                    "atr": float(latest.get('atr', 0.0)),
                                    "atr_expansion": float(latest.get('atr_expansion', 1.0)),
                                    "compression": float(latest.get('compression', 0.0)),
                                    "market_regime": int(latest.get('market_regime', 0)),
                                    "vwap_high": float(latest.get('vwap_high', 0.0)),
                                    "vwap_low": float(latest.get('vwap_low', 0.0)),
                                    "vfi_ema": float(latest.get('vfi_ema', 0.0)),
                                    "rvol": float(latest.get('rvol', 1.0)),
                                    "ltp": float(self.live_ltp) if self.live_ltp else float(latest.get('close', 0.0))
                                },
                                "human_reason": decision_state.get("human_reason", ""),
                                "rule_evaluations": decision_state.get("rule_evaluations", [])
                            }
                        else:
                            # Level 1: Full Candidate / Filtered row
                            from src.utils.provenance import get_provenance_metadata
                            from src.strategy.registry import STRATEGY_CONSTANTS
                            prov = get_provenance_metadata()
                            
                            decision_payload = {
                                "decision_uuid": decision_uuid,
                                "observation_uuid": observation_uuid,
                                "timestamp": datetime.now().isoformat(),
                                "market_session_id": datetime.now().strftime("%Y-%m-%d"),
                                "decision_action": "BUY" if signal and signal.get("type") == "CALL" else "SELL" if signal else "NONE",
                                "status": decision_status,
                                "lifecycle_stage": lifecycle_stage,
                                "decision_contract_version": "1.0.0",
                                "trade_mode": "Paper Trade",
                                "human_reason": decision_state.get("human_reason", ""),
                                "machine_state": decision_state.get("machine_state", {}),
                                "strategy_version": STRATEGY_VERSION,
                                "git_commit": prov["git_commit"],
                                "git_branch": prov["git_branch"],
                                "git_dirty": prov["git_dirty"],
                                "strategy_hash": prov["strategy_hash"],
                                "schema_version": prov["schema_version"],
                                "migration_version": prov["migration_version"],
                                "compatible_reader_version": prov["compatible_reader_version"],
                                "feature_schema_version": prov["feature_schema_version"],
                                "dataset_schema_version": prov["dataset_schema_version"],
                                "strategy_parameters": STRATEGY_CONSTANTS,
                                "rule_evaluations": decision_state.get("rule_evaluations", []),
                                "evaluation_time_ms": round(eval_ms, 2),
                                "market_state": {
                                    "vfi": float(latest.get('vfi', 0)),
                                    "vwap": float(latest.get('vwap', 0)),
                                    "ema_9": float(latest.get('ema_9', 0)),
                                    "atr": float(latest.get('atr', 0.0)),
                                    "atr_expansion": float(latest.get('atr_expansion', 1.0)),
                                    "compression": float(latest.get('compression', 0.0)),
                                    "market_regime": int(latest.get('market_regime', 0)),
                                    "vwap_high": float(latest.get('vwap_high', 0.0)),
                                    "vwap_low": float(latest.get('vwap_low', 0.0)),
                                    "vfi_ema": float(latest.get('vfi_ema', 0.0)),
                                    "rvol": float(latest.get('rvol', 1.0)),
                                    "ltp": float(self.live_ltp) if self.live_ltp else float(latest.get('close', 0.0))
                                }
                            }
                        self.exec_pub.publish("EXEC.DECISION", decision_payload)
                            
                        # Only register setup if we accepted it (flat state)
                        if signal and decision_status == "ACCEPTED":
                            signal["signal_id"] = str(uuid.uuid4())
                            signal["decision_uuid"] = decision_uuid
                            # Nest the full decision contract inside the signal so PaperTrader inherits it
                            signal["decision_payload"] = decision_payload
                            self.trader.register_setup(signal)
                            # Publish setup to exec port for UI
                            self.exec_pub.publish("EXEC.SETUP", signal)
                            self.publish_notification(
                                event_type="SETUP_PUBLISHED",
                                severity="SUCCESS",
                                title="Setup Published",
                                description=f"BUY {signal.get('type')} Published for {signal['symbol']} @ limit price ₹{signal.get('limit_price', 0.0)}",
                                correlation_id=decision_uuid[:8],
                                strategy=signal.get('strategy_name', '--'),
                                instrument=signal.get('symbol', '--'),
                                premium=signal.get('limit_price')
                            )
                            
                    # ── MANAGE ACTIVE TRADES / SETUPS ──
                    if self.trader.pending_setup is not None:
                        # Sniper mode
                        self.trader.sniper_hunt(self.live_ltp, self.current_df, self.order_flow)
                    elif self.trader.trade_context is not None:
                        self.trader.manage_open_trade(self.live_ltp, self.current_df)
                        
                    # State transitions -> Send to Shadow ML via ZeroMQ
                    is_pending = self.trader.pending_setup is not None
                    is_trade = self.trader.trade_context is not None
                    
                    if was_pending:
                        recent_candles = self.current_df.tail(500).to_dict('records') if self.current_df is not None else None
                        
                        latest = self.current_df.iloc[-1] if self.current_df is not None else {}
                        market_state = {
                            "regime": int(latest.get("market_regime", 0)),
                            "atr": float(latest.get("atr", 0.0)),
                            "atr_expansion": float(latest.get("atr_expansion", 1.0)),
                            "compression": float(latest.get("compression", 0.0))
                        }
                        telemetry = {
                            "symbol": self.anchor_symbol,
                            "ltp": self.live_ltp,
                            "volume": sum(self.current_minute_volume_tracker.values()),
                            "vwap": float(latest.get('vwap', 0)),
                            "ema": float(latest.get('ema_9', 0)),
                            "vfi": float(latest.get('vfi', 0)),
                            "vfi_ema": float(latest.get('vfi_ema', 0))
                        }
                        
                        payload = {
                            "signal": pending_signal,
                            "price": self.live_ltp,
                            "recent_candles": recent_candles,
                            "market_state": market_state,
                            "telemetry": telemetry
                        }
                        
                        if not is_pending and is_trade:
                            pending_signal['signal_category'] = 'EXECUTED'
                            self.exec_pub.publish("EXEC.SIGNAL_RESOLVED", payload)
                            strategy_name = pending_signal.get("strategy_name", "Strategy 1")
                            if strategy_name in self.strategy_stats:
                                self.strategy_stats[strategy_name]["executed"] += 1
                        elif not is_pending and not is_trade:
                            pending_signal['signal_category'] = 'REJECTED'
                            self.exec_pub.publish("EXEC.SIGNAL_RESOLVED", payload)
                            strategy_name = pending_signal.get("strategy_name", "Strategy 1")
                            if strategy_name in self.strategy_stats:
                                self.strategy_stats[strategy_name]["expired"] += 1
                            
                        try:
                            self.strike_intelligence.register_signal(payload)
                        except Exception as e:
                            logger.error(f"Strike Intelligence error: {e}")
                            
                    # Time stop research entry/exit transitions
                    if not was_trade and self.trader.trade_context is not None:
                        # Sniper trade entered!
                        trade = self.trader.trade_context
                        self.research_service.register_trade_entry(trade)
                        self.publish_notification(
                            event_type="BUY_EXECUTED",
                            severity="SUCCESS",
                            title="BUY Executed",
                            description=f"Paper Trade Executed: {trade.get('symbol')} // BUY @ limit price ₹{trade.get('entry_price')}",
                            correlation_id=(trade.get("decision_uuid") or '')[:8],
                            strategy=trade.get('strategy', 'Strategy 1'),
                            instrument=trade.get('symbol', '--'),
                            premium=trade.get('entry_price')
                        )
                    elif was_trade and self.trader.trade_context is None:
                        # Trade exited!
                        if len(self.trader.history_list) > 0:
                            last_trade = self.trader.history_list[-1]
                            self.research_service.register_trade_exit(
                                last_trade.get("decision_uuid") or last_trade.get("id"),
                                last_trade.get("exit_price"),
                                last_trade.get("reason"),
                                last_trade.get("net_pl")
                            )
                            
                            reason_str = last_trade.get("reason", "")
                            if "target" in reason_str.lower():
                                evt_t = "TARGET_HIT"
                                evt_title = "Target Hit"
                                evt_sev = "SUCCESS"
                            elif "stop loss" in reason_str.lower() or "sl" in reason_str.lower() or "stop" in reason_str.lower():
                                evt_t = "STOP_LOSS"
                                evt_title = "Stop Loss"
                                evt_sev = "ERROR"
                            elif "stall" in reason_str.lower() or "time stop" in reason_str.lower():
                                evt_t = "TIME_STOP"
                                evt_title = "Time Stop"
                                evt_sev = "WARNING"
                            else:
                                evt_t = "TRADE_CLOSED"
                                evt_title = "Paper Trade Closed"
                                evt_sev = "INFO"
                                
                            self.publish_notification(
                                event_type=evt_t,
                                severity=evt_sev,
                                title=evt_title,
                                description=f"Trade Closed ({reason_str}): Exit price ₹{last_trade.get('exit_price')} // Net P&L ₹{last_trade.get('net_pl'):.2f}",
                                correlation_id=(last_trade.get("decision_uuid") or '')[:8],
                                strategy=last_trade.get('strategy', 'Strategy 1'),
                                instrument=last_trade.get('symbol', '--'),
                                premium=last_trade.get('exit_price'),
                                pnl=last_trade.get('net_pl')
                            )
                            
                            self.publish_notification(
                                event_type="OBSERVATION_STARTED",
                                severity="RESEARCH",
                                title="Observation Started",
                                description=f"Post-Exit Time-Stop Observation Started for {last_trade.get('symbol')}",
                                correlation_id=(last_trade.get("decision_uuid") or '')[:8],
                                strategy=last_trade.get('strategy', 'Strategy 1'),
                                instrument=last_trade.get('symbol', '--')
                            )

                    # Compute Configurable Market Personality Score
                    from src.config.market_personality_config import PERSONALITY_WEIGHTS
                    latest_bar = self.current_df.iloc[-1]
                    p_score = PERSONALITY_WEIGHTS.get("base_score", 50)
                    price_val = float(latest_bar.get('close', 0.0))
                    vwap_val = float(latest_bar.get('vwap', 0.0))
                    if price_val > vwap_val:
                        p_score += PERSONALITY_WEIGHTS.get("vwap_alignment", 15)
                    else:
                        p_score -= PERSONALITY_WEIGHTS.get("vwap_alignment", 15)
                    
                    ema_val = float(latest_bar.get('ema_9', 0.0))
                    if ema_val > vwap_val:
                        p_score += PERSONALITY_WEIGHTS.get("ema_crossover", 15)
                    else:
                        p_score -= PERSONALITY_WEIGHTS.get("ema_crossover", 15)
                        
                    vfi_val = float(latest_bar.get('vfi', 0.0))
                    if vfi_val > 0.0:
                        p_score += PERSONALITY_WEIGHTS.get("vfi_positive", 10)
                    else:
                        p_score -= PERSONALITY_WEIGHTS.get("vfi_positive", 10)
                        
                    vfi_ema_val = float(latest_bar.get('vfi_ema', 0.0))
                    if vfi_ema_val > 0.0:
                        p_score += PERSONALITY_WEIGHTS.get("vfi_ema_positive", 10)
                    else:
                        p_score -= PERSONALITY_WEIGHTS.get("vfi_ema_positive", 10)
                        
                    regime_val = int(latest_bar.get('market_regime', 0))
                    if regime_val == 1:
                        p_score += PERSONALITY_WEIGHTS.get("bullish_regime", 10)
                    elif regime_val == -1:
                        p_score -= PERSONALITY_WEIGHTS.get("bullish_regime", 10)
                    p_score = max(0, min(100, p_score))

                    # Logic check latency stats
                    eval_avg = sum(self.logic_eval_times) / len(self.logic_eval_times) if self.logic_eval_times else 0.0
                    eval_max = max(self.logic_eval_times) if self.logic_eval_times else 0.0
                    eval_min = min(self.logic_eval_times) if self.logic_eval_times else 0.0
                    eval_95th = float(np.percentile(self.logic_eval_times, 95)) if self.logic_eval_times else 0.0

                    # Publish Telemetry for UI
                    telemetry = {
                        "symbol": self.anchor_symbol,
                        "ltp": self.live_ltp,
                        "volume": sum(self.current_minute_volume_tracker.values()),
                        "vwap": float(latest_bar.get('vwap', 0)),
                        "ema": float(latest_bar.get('ema_9', 0)),
                        "vfi": float(latest_bar.get('vfi', 0)),
                        "vfi_ema": float(latest_bar.get('vfi_ema', 0)),
                        "market_regime": regime_val,
                        "compression": float(latest_bar.get('compression', 0.0)),
                        "atr_expansion": float(latest_bar.get('atr_expansion', 1.0)),
                        "strategy_stats": self.strategy_stats,
                        "market_personality_score": p_score,
                        "tick_seq_counter": self.tick_seq_counter,
                        "research_queue_health": self.research_service.get_queue_health(),
                        "latency_metrics": {
                            "min_eval_ms": round(eval_min, 2),
                            "avg_eval_ms": round(eval_avg, 2),
                            "max_eval_ms": round(eval_max, 2),
                            "pct95_eval_ms": round(eval_95th, 2)
                        }
                    }
                    self.exec_pub.publish("EXEC.TELEMETRY", telemetry)
                    
                    # Publish Chart Data for UI (send last 200 candles)
                    if self.current_df is not None and not self.current_df.empty:
                        chart_df = self.current_df.tail(200).copy()
                        if 'timestamp' not in chart_df.columns and chart_df.index.name == 'timestamp':
                            chart_df = chart_df.reset_index()
                        # Convert timestamps to string to avoid JSON serialization errors
                        chart_df['timestamp'] = chart_df['timestamp'].astype(str)
                        chart_payload = chart_df.to_dict('records')
                        self.exec_pub.publish("EXEC.CHART_SYNC", chart_payload)
                    
                    # Manage Option Subscription for Order Flow
                    opt_tokens = []
                    if self.trader.trade_context:
                        opt_tokens.append(self.trader.trade_context['token'])
                        self.exec_pub.publish("EXEC.ACTIVE_TRADE", self.trader.trade_context)
                    if self.trader.pending_setup:
                        opt_tokens.append(self.trader.pending_setup.get('candidate_token'))
                    opt_tokens.extend(self.research_service.get_observed_tokens())
                    
                    import zmq
                    # Ensure we subscribe to any new options tokens we need to observe
                    for t in opt_tokens:
                        if t and t not in self.subscribed_options_set:
                            self.cmd_pub.publish("CMD.SUBSCRIBE", {"tokens": [t], "exchange": "NFO"})
                            try:
                                self.feed_sub.socket.setsockopt_string(zmq.SUBSCRIBE, f"TICK.{t}")
                            except Exception:
                                pass
                            self.subscribed_options_set.add(t)

            time.sleep(5)

    def start(self):
        logger.info("=== STARTING BRAIN SERVICE ===")
        self.boot_sequence()
        self.research_service.start()
        
        # Publish start event
        self.publish_notification(
            event_type="BRAIN_RESTARTED",
            severity="SYSTEM",
            title="Brain Restarted",
            description="Brain Service Started"
        )
        
        # Start logic loop
        logic_thread = threading.Thread(target=self.execute_logic_loop, daemon=True)
        logic_thread.start()
        
        # Start blocking feed listener
        import zmq
        self.feed_sub.listen(self.on_tick)

if __name__ == "__main__":
    service = BrainService()
    try:
        service.start()
    except KeyboardInterrupt:
        logger.info("Brain Service shutting down...")
        service.cmd_pub.close()
        service.exec_pub.close()
        service.feed_sub.close()
