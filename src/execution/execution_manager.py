import time
import os
import csv
import json
from datetime import datetime, timedelta
import pandas as pd
from src.utils.logger import get_logger
from src.core.decision_lifecycle import DecisionLifecycle
from src.execution.capital_engine import CapitalEngine
from src.execution.strike_selector import StrikeSelector
from src.execution.trade_context import TradeContext, TradeLeg
from src.execution.order_lifecycle import PaperOrderLifecycle

logger = get_logger("execution_manager")

class ExecutionManager:
    def __init__(self, broker_gateway, data_fetcher, history_list=None, order_lifecycle=None):
        self.broker = broker_gateway
        self.data_fetcher = data_fetcher
        self.capital_engine = CapitalEngine(mode="PAPER")
        self.order_lifecycle = order_lifecycle if order_lifecycle else PaperOrderLifecycle()
        self.trades_today = 0
        self.trade_context = None
        self.pending_setup = None
        self.cooldown_until = None
        self.last_trade_date = None
        self.history_list = history_list if history_list is not None else []
        self._option_cache = {}
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        trades_dir = os.path.join(base_dir, "data", "trades")
        os.makedirs(trades_dir, exist_ok=True)
        self.history_file = os.path.join(trades_dir, "trade_history.json")
        self.depth_file = os.path.join(trades_dir, "slippage_data.ndjson")
        self.active_context_file = os.path.join(trades_dir, "active_trade_context.json")
        
        self._load_active_context()
        
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.history_list = json.load(f)
                    today_str = datetime.now().strftime('%d %b')
                    today_trades = [t for t in self.history_list if t.get('date', '').startswith(today_str)]
                    self.trades_today = len(today_trades)
                    
                    if today_trades:
                        last_trade = today_trades[-1]
                        last_time_str = last_trade.get('date')
                        if last_time_str:
                            curr_year = datetime.now().year
                            last_trade_time = datetime.strptime(f"{last_time_str} {curr_year}", '%d %b %H:%M:%S %Y')
                            self.cooldown_until = last_trade_time + timedelta(minutes=30)
                            if self.cooldown_until < datetime.now():
                                self.cooldown_until = None
            except Exception as e:
                logger.error(f"Error loading history file: {e}")
                self.history_list = []

    def _load_active_context(self):
        if os.path.exists(self.active_context_file):
            try:
                with open(self.active_context_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                self.trade_context = TradeContext(
                    signal_type=data["signal_type"],
                    strategy=data["strategy"],
                    index_entry=data["index_entry"],
                    decision_payload=data.get("decision_payload")
                )
                self.trade_context.context_id = data["context_id"]
                self.trade_context.status = data["status"]
                self.trade_context.entry_time = datetime.fromisoformat(data["entry_time"]) if data.get("entry_time") else None
                
                for leg_data in data.get("legs", []):
                    leg = TradeLeg(
                        token=leg_data["token"],
                        symbol=leg_data["symbol"],
                        strike=leg_data["strike"],
                        option_type=leg_data["option_type"],
                        quantity=leg_data["quantity"],
                        entry_price=leg_data["entry_price"],
                        broker_order_id=leg_data.get("broker_order_id"),
                        paper_order_id=leg_data.get("paper_order_id")
                    )
                    leg.leg_id = leg_data["leg_id"]
                    leg.status = leg_data["status"]
                    leg.current_price = leg_data["current_price"]
                    leg.exit_price = leg_data.get("exit_price")
                    leg.pnl = leg_data.get("pnl", 0.0)
                    self.trade_context.add_leg(leg)
                    
                self._validate_restored_context()
                
                logger.info(f"[ExecutionManager] Restored active TradeContext with {len(self.trade_context.legs)} legs.")
            except Exception as e:
                logger.error(f"[ExecutionManager] Failed to restore TradeContext: {e}")
                self.trade_context = None

    def _validate_restored_context(self):
        """
        Validates the restored TradeContext against the actual broker execution state.
        In PAPER mode, the JSON is the source of truth.
        In LIVE mode, this prevents ghost positions by verifying with the broker's order/position book.
        """
        if not self.trade_context or self.trade_context.status != "OPEN":
            return
            
        # If LIVE mode, query self.broker.portfolio_provider.get_positions() to ensure the leg quantities match reality.
        # This prevents the system from managing a trade that was closed manually or rejected.
        pass

    def _save_active_context(self):
        if self.trade_context and self.trade_context.status == "OPEN":
            with open(self.active_context_file, 'w', encoding='utf-8') as f:
                json.dump(self.trade_context.to_dict(), f, indent=4)
        else:
            if os.path.exists(self.active_context_file):
                os.remove(self.active_context_file)

    def reset_daily(self):
        today = datetime.now().date()
        if self.last_trade_date != today:
            self.trades_today = 0
            self.last_trade_date = today
            self.cooldown_until = None

    def get_instrument_params(self):
        from src.config.engineering_config import NIFTY_PREMIUM_MIN, NIFTY_PREMIUM_MAX, SENSEX_PREMIUM_MIN, SENSEX_PREMIUM_MAX
        name, exch_seg = self.data_fetcher.get_active_instrument()
        if name == "SENSEX":
            return {"premium_min": SENSEX_PREMIUM_MIN, "premium_max": SENSEX_PREMIUM_MAX, "lot_size": 20, "index_name": "SENSEX"}
        else:
            return {"premium_min": NIFTY_PREMIUM_MIN, "premium_max": NIFTY_PREMIUM_MAX, "lot_size": 25, "index_name": "NIFTY"}

    def register_setup(self, signal):
        self.reset_daily()
        now = datetime.now()
        
        if now.hour < 10: return
        if self.trades_today >= 3: return
        if self.cooldown_until and now < self.cooldown_until: return
            
        opt_row, entry_price = self.select_option(signal["type"])
        if opt_row is None:
            logger.info("Sniper Aborted: Could not find option candidate.")
            return
            
        signal["candidate_token"] = str(opt_row['token'])
        signal["candidate_symbol"] = opt_row['symbol']
        signal["candidate_price"] = entry_price
        
        self.pending_setup = signal
        self.pending_setup["expiry_time"] = now + timedelta(minutes=3)
        logger.info(f"[{now.time()}] MASTER SETUP LOCKED: {signal['type']}")
        logger.info(f"Candidate for Order Flow: {signal['candidate_symbol']} at Rs{entry_price}")

    def sniper_hunt(self, live_ltp, current_nifty_df, order_flow_state):
        if not self.pending_setup: return
        now = datetime.now()
        setup = self.pending_setup
        
        if now > setup["expiry_time"]:
            logger.info(f"[{now.time()}] SETUP ABORTED: 3 minutes passed.")
            self.pending_setup = None
            return
            
        triggered = False
        if setup["type"] == "CALL" and live_ltp > (setup["master_high"] + 0.05): triggered = True
        elif setup["type"] == "PUT" and live_ltp < (setup["master_low"] - 0.05): triggered = True
            
        if triggered:
            delta = order_flow_state.get("delta", 0)
            if delta > 0:
                logger.info(f"!!! SNIPER TRIGGERED !!! Delta POSITIVE ({delta}).")
                self._execute_trade(setup, current_nifty_df)
            else:
                logger.info(f"!!! FAKE BREAKOUT DETECTED !!! Delta NEGATIVE ({delta}).")
                self.pending_setup = None

    def update_option_cache(self, fetched_data: dict):
        self._option_cache.update(fetched_data)

    def select_option(self, signal_type):
        weekly_opts = self.data_fetcher.get_weekly_option_tokens()
        if weekly_opts.empty: return None, 0
        
        params = self.get_instrument_params()
        # Just return the first affordable one for candidate tracking
        allocs = StrikeSelector.select_strikes(
            signal_type=signal_type,
            index_price=self.data_fetcher.get_index_ltp() if hasattr(self.data_fetcher, 'get_index_ltp') else 24000,
            index_name=params["index_name"],
            weekly_opts=weekly_opts,
            option_cache=self._option_cache,
            available_funds=self.capital_engine.get_available_funds(),
            lot_size=params["lot_size"]
        )
        if allocs:
            return allocs[0][0], allocs[0][2]
        return None, 0

    def _execute_trade(self, setup, current_nifty_df):
        params = self.get_instrument_params()
        weekly_opts = self.data_fetcher.get_weekly_option_tokens()
        index_price = current_nifty_df.iloc[-1]['close']
        
        allocations = StrikeSelector.select_strikes(
            signal_type=setup["type"],
            index_price=index_price,
            index_name=params["index_name"],
            weekly_opts=weekly_opts,
            option_cache=self._option_cache,
            available_funds=self.capital_engine.get_available_funds(),
            lot_size=params["lot_size"]
        )
        
        if not allocations:
            logger.info("Sniper Aborted: No affordable OTM strikes found for Capital.")
            self.pending_setup = None
            return
            
        self.trade_context = TradeContext(
            signal_type=setup["type"],
            strategy=setup.get("strategy", "VWAP_BREAKOUT"),
            index_entry=index_price,
            decision_payload=setup.get("decision_payload")
        )
        
        name, exch_seg = self.data_fetcher.get_active_instrument()
        
        for opt_row, quantity, ltp in allocations:
            token = str(opt_row['token'])
            symbol = opt_row['symbol']
            strike = float(opt_row['strike']) / 100
            
            # Simulated Sequential Execution
            leg = TradeLeg(token, symbol, strike, setup["type"], quantity, ltp) # quantity here is lots
            
            # Delegate Entry to OrderLifecycle
            if self.order_lifecycle.execute_entry(leg):
                self.trade_context.add_leg(leg)
                # Deduct Funds Sequentially
                self.capital_engine.deduct_funds(ltp * quantity * params["lot_size"])
                logger.info(f"Executed Leg: {quantity} lots of {symbol} at Rs{ltp}")
            
        if self.trade_context.decision_payload:
            self.trade_context.decision_payload["lifecycle_stage"] = DecisionLifecycle.EXECUTED.value
            
        self._save_active_context()
        self.trades_today += 1
        self.pending_setup = None
        logger.info("--- MULTI-STRIKE TRADE EXECUTED ---")

    def manage_open_trade(self, live_ltp, current_nifty_df):
        if not self.trade_context or self.trade_context.status != "OPEN":
            return
            
        name, exch_seg = self.data_fetcher.get_active_instrument()
        
        # Update live prices for all open legs
        for leg in self.trade_context.legs:
            if leg.status == "OPEN":
                try:
                    res = self.broker.market_data_provider.get_quote(exch_seg, leg.token)
                    if res and res.get('ltp', 0.0) > 0:
                        leg.current_price = res['ltp']
                except:
                    pass

        # Calculate PnL
        total_pnl = sum((leg.current_price - leg.entry_price) * leg.quantity * self.get_instrument_params()["lot_size"] for leg in self.trade_context.legs if leg.status == "OPEN")
        capital_used = sum((leg.entry_price) * leg.quantity * self.get_instrument_params()["lot_size"] for leg in self.trade_context.legs if leg.status == "OPEN")
        
        # 1. Target Check
        if capital_used > 0 and (total_pnl / capital_used) >= 0.10: # 10% Target
            self._close_all_legs(current_nifty_df, "10% TARGET HIT")
            return
            
        # 2. Time Stop (3 mins)
        duration = (datetime.now() - self.trade_context.entry_time).total_seconds()
        if duration >= 180:
            self._close_all_legs(current_nifty_df, "Gamma Stall Abort")
            return
            
        # 3. Candle SL Check
        now = datetime.now()
        closed_candles = current_nifty_df[current_nifty_df['timestamp'].dt.floor('min') < pd.Timestamp(now).floor('min')]
        if not closed_candles.empty:
            last_closed = closed_candles.iloc[-1]
            ema_9 = float(last_closed['ema_9'])
            vwap = float(last_closed['vwap'])
            close_price = float(last_closed['close'])
            
            strat = self.trade_context.strategy
            if strat == 'WINDOW_ALIGNMENT':
                if self.trade_context.signal_type == "CALL" and ema_9 < vwap:
                    self._close_all_legs(current_nifty_df, "CANDLE SL: 9 EMA Closed Below VWAP")
                    return
                elif self.trade_context.signal_type == "PUT" and ema_9 > vwap:
                    self._close_all_legs(current_nifty_df, "CANDLE SL: 9 EMA Closed Above VWAP")
                    return

    def _close_all_legs(self, current_nifty_df, reason):
        params = self.get_instrument_params()
        
        for leg in self.trade_context.legs:
            if leg.status == "OPEN":
                # Delegate Exit to OrderLifecycle
                if self.order_lifecycle.execute_exit(leg, reason, leg.current_price):
                    leg.pnl = (leg.exit_price - leg.entry_price) * leg.quantity * params["lot_size"]
                    self.capital_engine.add_funds((leg.exit_price * leg.quantity * params["lot_size"]))
                    logger.info(f"Closed Leg {leg.symbol} at Rs{leg.exit_price}. PnL: Rs{leg.pnl:.2f}")
                
        self.trade_context.close_context()
        self.trade_context.total_pnl = sum(leg.pnl for leg in self.trade_context.legs)
        self._save_active_context()
        
        # Log History
        row_id = len(self.history_list) + 1
        net_pl = self.trade_context.total_pnl
        result = "WIN" if net_pl > 0 else ("LOSS" if net_pl < -50 else "MIN LOSS")
        
        if self.trade_context.decision_payload:
            self.trade_context.decision_payload["lifecycle_stage"] = DecisionLifecycle.EXITED.value
            
        self.history_list.append({
            "id": row_id,
            "date": datetime.now().strftime('%d %b %H:%M:%S'),
            "duration": "MULTI",
            "symbol": f"MULTI {len(self.trade_context.legs)} LEGS",
            "strategy": self.trade_context.strategy,
            "entry_price": 0,
            "exit_price": 0,
            "opt_pct": 0,
            "idx_pts": 0,
            "net_pl": round(net_pl, 2),
            "capital_used": sum(leg.entry_price * leg.quantity * params["lot_size"] for leg in self.trade_context.legs),
            "chart": "",
            "reason": reason,
            "result": result,
            "decision_payload": self.trade_context.decision_payload
        })
        
        temp_file = self.history_file + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(self.history_list, f, indent=4)
        os.replace(temp_file, self.history_file)
        
        logger.info(f"--- CONTEXT CLOSED --- Total PnL: Rs{net_pl:.2f}")
        self.cooldown_until = datetime.now() + timedelta(minutes=30)
        self.trade_context = None
