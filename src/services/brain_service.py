import time
import threading
import sys
import os
import uuid
from pathlib import Path
os.environ["POLARS_IGNORE_TIMEZONE_PARSE_ERROR"] = "1"
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.angel_connection import get_angel_connection
from src.core.data_fetcher import DataFetcher
from src.strategy.indicators import append_all_indicators
from src.strategy.signal_generator import SignalGenerator
from src.execution.paper_trader import PaperTrader
from src.core.message_bus import MessageBusPublisher, MessageBusSubscriber, FEED_PORT, CMD_PORT, EXEC_PORT
from src.utils.logger import get_logger
from src.ml_engine.gamma_event_collector import GammaEventCollector
from src.research.strike_intelligence import StrikeIntelligenceModule

logger = get_logger("brain_service")

class BrainService:
    def __init__(self):
        try:
            self.api, _ = get_angel_connection()
        except Exception as e:
            logger.critical(f"[BrainService] Failed to connect: {e}")
            sys.exit(1)
            
        self.fetcher = DataFetcher(self.api)
        self.signal_gen = SignalGenerator()
        self.trader = PaperTrader(self.api, self.fetcher, [])
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
        self.tracked_options = {}
        self.last_historic_fetch = 0
        self.last_option_refresh = 0
        self.last_saved_indicator_minute = -1  # Tracks last minute we archived indicators

    def boot_sequence(self):
        logger.info("=== BOOT: Building Synthetic Volume Engine (this takes ~35 seconds) ===")
        try:
            boot_df = self.fetcher.get_historical_candles_with_synthetic_volume(days_back=5)
            if not boot_df.empty:
                self.cached_volume_df = boot_df.set_index('timestamp')[['volume']].rename(columns={'volume': 'synth_vol'})
                self.cached_price_df = boot_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                self.current_df = append_all_indicators(boot_df)
                logger.info("=== BOOT COMPLETE: Synthetic Volume Engine Online ===")
        except Exception as e:
            logger.critical(f"BOOT ERROR: {e}")
            sys.exit(1)

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
            closed_candle['schema_version'] = 'indicator_stream_v1.0'

            # Convert timestamp to string if it's a Timestamp object
            if hasattr(closed_candle.get('timestamp'), 'isoformat'):
                closed_candle['timestamp'] = str(closed_candle['timestamp'])

            df = pd.DataFrame([closed_candle])

            # Save to: data/institutional_memory/indicator_stream/YYYY/MM/DD/indicators_HHMM.parquet
            date_str = now.strftime("%Y/%m/%d")
            save_dir = Path("data/institutional_memory/indicator_stream") / date_str
            save_dir.mkdir(parents=True, exist_ok=True)

            file_name = f"indicators_{now.strftime('%H%M')}.parquet"
            save_path = save_dir / file_name

            table = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(table, save_path, compression="zstd")

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
        
        # 1. Minute Rollover for Synthetic Volume
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
            self.live_ltp = float(ltp / 100)
            if self.live_open is None: self.live_open = self.live_ltp
            if self.live_high is None or self.live_ltp > self.live_high: self.live_high = self.live_ltp
            if self.live_low is None or self.live_ltp < self.live_low: self.live_low = self.live_ltp
            
        # 4. Tracked Options for Gamma Collector
        if token in self.tracked_options and ltp > 0:
            opt_price = float(ltp / 100)
            opt_details = self.tracked_options[token]
            best_bid = 0.0
            best_ask = 0.0
            if 'best_5_buy_data' in message and len(message['best_5_buy_data']) > 0:
                best_bid = float(message['best_5_buy_data'][0].get('price', 0)) / 100
            if 'best_5_sell_data' in message and len(message['best_5_sell_data']) > 0:
                best_ask = float(message['best_5_sell_data'][0].get('price', 0)) / 100
            
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

        # 5. Order Flow / Delta Tracking for Active Option
        if self.subscribed_option == token and ltp > 0:
            live_opt_ltp = float(ltp / 100)
            if self.trader.current_trade and token == self.trader.current_trade['token']:
                # Update UI via exec port if needed
                pass
                
            if self.order_flow["token"] != token:
                self.order_flow = {"token": token, "buy_vol": 0, "sell_vol": 0, "delta": 0, "last_price": live_opt_ltp, "last_was_buy": True}
            elif ltq > 0 and is_market_open:
                prev_price = self.order_flow["last_price"]
                best_ask = 0
                best_bid = 0
                
                ask_data = message.get('best_5_sell_data', [])
                bid_data = message.get('best_5_buy_data', [])
                if ask_data and isinstance(ask_data, list): best_ask = ask_data[0].get('price', 0) / 100
                if bid_data and isinstance(bid_data, list): best_bid = bid_data[0].get('price', 0) / 100
                    
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
        import zmq # Needed for setsockopt in subscribe_options
        # Wait for boot
        while self.cached_price_df is None:
            time.sleep(1)
            
        while True:
            now = datetime.now()
            is_market_open = (now.hour == 9 and now.minute >= 15) or (9 < now.hour < 15) or (now.hour == 15 and now.minute <= 30)
            
            if is_market_open and self.live_ltp is not None:
                now_ts = time.time()
                
                # Fetch recent candles every 10 seconds to ensure consistency with broker
                if now_ts - self.last_historic_fetch >= 10:
                    try:
                        new_price_df = self.fetcher.get_historical_candles(self.anchor_exch, self.anchor_token, "ONE_MINUTE", minutes_back=15)
                        if not new_price_df.empty and self.cached_volume_df is not None:
                            new_price_df = new_price_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                            self.cached_price_df = new_price_df.combine_first(self.cached_price_df)
                            
                            price_df = self.cached_price_df.copy().join(self.cached_volume_df, how='left')
                            price_df['volume'] = price_df['synth_vol'].fillna(0).astype(int)
                            price_df = price_df.drop(columns=['synth_vol']).reset_index()
                            
                            # Inject Virtual Candle
                            live_ts = pd.Timestamp(now.replace(second=0, microsecond=0))
                            if getattr(price_df['timestamp'].dtype, 'tz', None) is not None:
                                live_ts = live_ts.tz_localize(price_df['timestamp'].dtype.tz)
                                
                            live_vol = sum(self.current_minute_volume_tracker.values())
                            
                            if not (price_df['timestamp'] == live_ts).any():
                                live_row = pd.DataFrame({
                                    'timestamp': [live_ts], 'open': [self.live_open if self.live_open else self.live_ltp],
                                    'high': [self.live_high if self.live_high else self.live_ltp], 'low': [self.live_low if self.live_low else self.live_ltp],
                                    'close': [self.live_ltp], 'volume': [live_vol]
                                })
                                price_df = pd.concat([price_df, live_row], ignore_index=True)
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
                                    
                                    # Manually set sock opts here
                                    for tk in tokens_to_sub:
                                        self.feed_sub.socket.setsockopt_string(zmq.SUBSCRIBE, f"TICK.{tk}")
                                        
                                self.last_option_refresh = now_ts
                                
                    except Exception as e:
                        logger.error(f"[BrainService] Error in loop: {e}")
                    self.last_historic_fetch = now_ts
                    
                # Signal Generation & Execution
                if self.current_df is not None:
                    was_pending = self.trader.pending_setup is not None
                    pending_signal = self.trader.pending_setup.copy() if was_pending else None
                    was_trade = self.trader.current_trade is not None
                    
                    # ── GAP 1 FIX: ALWAYS EVALUATE SIGNALS DURING TRADING WINDOW ──
                    is_trading_window = (now.hour > 10 or (now.hour == 10 and now.minute >= 0)) and (now.hour < 15 or (now.hour == 15 and now.minute < 15))
                    if is_trading_window:
                        if self.trader.cooldown_until and now < self.trader.cooldown_until:
                            signal, decision_state = None, {
                                "human_reason": f"Active Cooldown until {self.trader.cooldown_until.strftime('%H:%M:%S')}",
                                "machine_state": {}
                            }
                        else:
                            signal, decision_state = self.signal_gen.check_signal(self.current_df)
                            if not signal: 
                                strat1_reason = decision_state.get("human_reason", "Strategy 1 failed")
                                strat1_machine = decision_state.get("machine_state", {})
                                
                                signal, decision_state = self.signal_gen.check_rejection_signal(self.current_df)
                                if not signal:
                                    # Both strategies failed. Combine their rejection states.
                                    strat2_reason = decision_state.get("human_reason", "Strategy 2 failed")
                                    decision_state["human_reason"] = f"S1: {strat1_reason} | S2: {strat2_reason}"
                                    decision_state["machine_state"]["strategy_1_state"] = strat1_machine
                            
                        latest = self.current_df.iloc[-1]
                        observation_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(latest['timestamp'])))
                        decision_uuid = str(uuid.uuid4())
                        
                        # Determine the decision status, noting if we ignored a valid signal due to current state
                        if signal:
                            if self.trader.current_trade is not None:
                                decision_status = "IGNORED_OPEN_TRADE"
                            elif self.trader.pending_setup is not None:
                                decision_status = "IGNORED_SNIPER_MODE"
                            else:
                                decision_status = "ACCEPTED"
                        else:
                            decision_status = "REJECTED"
                        
                        decision_payload = {
                            "decision_uuid": decision_uuid,
                            "observation_uuid": observation_uuid,
                            "timestamp": datetime.now().isoformat(),
                            "market_session_id": datetime.now().strftime("%Y-%m-%d"),
                            "decision_action": "BUY" if signal and signal.get("type")=="CALL" else "SELL" if signal else "NONE",
                            "status": decision_status,
                            "trade_mode": "Paper Trade",
                            "human_reason": decision_state.get("human_reason", ""),
                            "machine_state": decision_state.get("machine_state", {}),
                            "strategy_version": "3.1",
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
                            self.trader.register_setup(signal)
                            # Publish setup to exec port for UI
                            self.exec_pub.publish("EXEC.SETUP", signal)
                            
                    # ── MANAGE ACTIVE TRADES / SETUPS ──
                    if self.trader.pending_setup is not None:
                        # Sniper mode
                        self.trader.sniper_hunt(self.live_ltp, self.current_df, self.order_flow)
                    elif self.trader.current_trade is not None:
                        self.trader.manage_open_trade(self.live_ltp, self.current_df)
                        
                    # State transitions -> Send to Shadow ML via ZeroMQ
                    is_pending = self.trader.pending_setup is not None
                    is_trade = self.trader.current_trade is not None
                    
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
                        elif not is_pending and not is_trade:
                            pending_signal['signal_category'] = 'REJECTED'
                            self.exec_pub.publish("EXEC.SIGNAL_RESOLVED", payload)
                            
                        try:
                            self.strike_intelligence.register_signal(payload)
                        except Exception as e:
                            logger.error(f"Strike Intelligence error: {e}")
                            
                    # Publish Telemetry for UI
                    latest = self.current_df.iloc[-1]
                    telemetry = {
                        "symbol": self.anchor_symbol,
                        "ltp": self.live_ltp,
                        "volume": sum(self.current_minute_volume_tracker.values()),
                        "vwap": float(latest.get('vwap', 0)),
                        "ema": float(latest.get('ema_9', 0)),
                        "vfi": float(latest.get('vfi', 0)),
                        "vfi_ema": float(latest.get('vfi_ema', 0))
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
                    opt_token = None
                    if self.trader.current_trade:
                        opt_token = self.trader.current_trade['token']
                        self.exec_pub.publish("EXEC.ACTIVE_TRADE", self.trader.current_trade)
                    elif self.trader.pending_setup:
                        opt_token = self.trader.pending_setup.get('candidate_token')
                        
                    if opt_token and self.subscribed_option != opt_token:
                        self.cmd_pub.publish("CMD.SUBSCRIBE", {"tokens": [opt_token], "exchange": "NFO"})
                        self.feed_sub.socket.setsockopt_string(zmq.SUBSCRIBE, f"TICK.{opt_token}")
                        self.subscribed_option = opt_token

            time.sleep(2)

    def start(self):
        logger.info("=== STARTING BRAIN SERVICE ===")
        self.boot_sequence()
        
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
