import time
import threading
import sys
import os
from datetime import datetime, timedelta

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.broker import get_broker_adapter
from src.core.message_bus import MessageBusPublisher, MessageBusSubscriber, FEED_PORT, CMD_PORT
from src.core.market_calendar import MarketCalendar
from src.core.symbol_registry import SymbolRegistry
from src.utils.logger import get_logger

logger = get_logger("feed_service")

class FeedService:
    def __init__(self):
        self.pub = MessageBusPublisher(FEED_PORT)
        # Load the registry once (Singleton) — O(1) token→symbol lookup for all ticks
        self.registry = SymbolRegistry()
        
        # Obtain broker adapter and session information via the abstraction layer
        try:
            broker = get_broker_adapter()
            session_data = broker.session_provider.get_session()
        except Exception as e:
            logger.critical(f"[FeedService] Failed to obtain broker session: {e}")
            sys.exit(1)

        # Use the market data provider to get a DataFetcher bound to the broker API
        self.fetcher = broker.market_data_provider.get_data_fetcher()
        self.anchor_token, self.anchor_symbol, self.anchor_exch = self.fetcher.get_cash_index_token()
        
        self.eq_exch_type = 1 if self.anchor_exch == "NSE" else 3
        self.deriv_exch_type = 2 if self.anchor_exch == "NSE" else 4
        
        self.eq_tokens = [self.anchor_token]
        self.eq_tokens.append("99926017") # INDIA VIX
        self.deriv_tokens = []
        
        # 1. Futures
        fut_token, _, _ = self.fetcher.get_current_futures_token()
        if fut_token:
            self.deriv_tokens.append(fut_token)
            
        # 2. Constituents
        active_tokens = self.fetcher.get_active_constituents()
        self.eq_tokens.extend(list(active_tokens.values()))
        
        # 3. Option Chain
        opt_df = self.fetcher.get_weekly_option_tokens()
        if not opt_df.empty:
            self.deriv_tokens.extend(opt_df['token'].tolist())
            
        logger.info(f"[FeedService] Built token lists: {len(self.eq_tokens)} Equities, {len(self.deriv_tokens)} Derivatives.")
        
        self.broker = broker
        self.reconnect_attempts = 0
        
        # Command Subscriber (listens to Brain for dynamic subscriptions)
        self.cmd_sub = MessageBusSubscriber(CMD_PORT, topics=["CMD.SUBSCRIBE"])

    def on_open(self):
        logger.info("[FeedService] WS Connected. Subscribing to base tokens...")
        self.reconnect_attempts = 0
        try:
            if self.eq_tokens:
                self.broker.market_data_provider.subscribe(self.eq_tokens, exchange="NSE")
            if self.deriv_tokens:
                self.broker.market_data_provider.subscribe(self.deriv_tokens, exchange="NFO")
            
            logger.info(f"[FeedService] Subscribed to {len(self.eq_tokens)} Equities and {len(self.deriv_tokens)} Derivatives.")
        except Exception as e:
            logger.error(f"[FeedService] Initial subscribe error: {e}")

    def on_data(self, message):
        if isinstance(message, dict):
            token = message.get("token")
            if token:
                # Enrich tick with universal symbol before publishing.
                # This is the single injection point that makes ALL downstream
                # services (brain, canonical, gamma) broker-agnostic.
                broker_symbol = message.get("symbol", "")
                message["symbol"] = self.registry.get_symbol(str(token), broker_symbol)
                self.pub.publish(f"TICK.{token}", message)

    def on_error(self, error):
        logger.error(f"[FeedService] WS Error: {error}")

    def run_ws(self):
        while True:
            # Check Market Calendar
            session_type = MarketCalendar.get_session_type()
            if session_type in ["HOLIDAY", "AFTER_MARKET", "PREOPEN"]:
                next_open = MarketCalendar.next_market_open()
                if not next_open:
                    next_open = datetime.now() + timedelta(days=1)
                
                now = datetime.now()
                sleep_sec = (next_open - now).total_seconds()
                
                # If we are more than 10 seconds away from market open, sleep.
                if sleep_sec > 10:
                    logger.info(f"[FeedService] Off-market ({session_type}). Sleeping for {int(sleep_sec)}s until {next_open}.")
                    time.sleep(sleep_sec - 5)  # Wake up 5 seconds early
                    logger.warning("[FeedService] Waking up! Exiting to force fresh token generation via LifecycleManager.")
                    sys.exit(10)
            
            try:
                logger.info(f"[FeedService] Starting Live Feed (Attempt {self.reconnect_attempts})...")
                self.broker.market_data_provider.start_live_feed(
                    on_tick_callback=self.on_data,
                    on_open_callback=self.on_open,
                    on_error_callback=self.on_error
                )
                self.reconnect_attempts = 0
            except Exception as e:
                logger.error(f"[FeedService] Connection threw error: {e}")
                
            self.reconnect_attempts += 1
            if self.reconnect_attempts > 10:
                logger.error("[FeedService] Max reconnect attempts reached. Sleeping for 1 minute before trying again.")
                time.sleep(60)
            else:
                logger.info(f"[FeedService] Reconnecting in 3 seconds (Attempt {self.reconnect_attempts}/10)...")
                time.sleep(3)

    def command_listener(self):
        """Listens for dynamic subscription commands from the Brain."""
        def on_cmd(topic, payload):
            if topic == "CMD.SUBSCRIBE":
                tokens = payload.get("tokens", [])
                exchange = payload.get("exchange", "NFO")
                if tokens:
                    logger.info(f"[FeedService] Received CMD.SUBSCRIBE for {len(tokens)} tokens on {exchange}")
                    try:
                        self.broker.market_data_provider.subscribe(tokens, exchange=exchange)
                    except Exception as e:
                        logger.error(f"[FeedService] Dynamic subscribe error: {e}")
                        
        logger.info("[FeedService] Command listener started.")
        self.cmd_sub.listen(on_cmd)

    def start(self):
        logger.info("=== STARTING FEED SERVICE ===")
        # Start command listener thread
        cmd_thread = threading.Thread(target=self.command_listener, daemon=True)
        cmd_thread.start()
        
        # Start WS runner
        self.run_ws()

if __name__ == "__main__":
    service = FeedService()
    try:
        service.start()
    except KeyboardInterrupt:
        logger.info("Feed Service shutting down...")
        service.pub.close()
        service.cmd_sub.close()
