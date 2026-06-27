import time
import threading
import sys
import os
from datetime import datetime

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.angel_connection import get_angel_connection, get_websocket_connection
from src.core.data_fetcher import DataFetcher
from src.core.message_bus import MessageBusPublisher, MessageBusSubscriber, FEED_PORT, CMD_PORT
from src.core.market_calendar import MarketCalendar
from src.utils.logger import get_logger

logger = get_logger("feed_service")

class FeedService:
    def __init__(self):
        self.pub = MessageBusPublisher(FEED_PORT)
        
        try:
            self.api, session_data = get_angel_connection()
        except Exception as e:
            logger.critical(f"[FeedService] Failed to connect to Angel: {e}")
            sys.exit(1)
            
        self.fetcher = DataFetcher(self.api)
        self.anchor_token, self.anchor_symbol, self.anchor_exch = self.fetcher.get_cash_index_token()
        
        self.eq_exch_type = 1 if self.anchor_exch == "NSE" else 3
        self.deriv_exch_type = 2 if self.anchor_exch == "NSE" else 4
        
        self.eq_tokens = [self.anchor_token]
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
        
        feed_token = session_data.get("feedToken")
        jwt_token = session_data.get("jwtToken")
        client_id = os.getenv("ANGEL_CLIENT_ID")
        api_key = os.getenv("ANGEL_API_KEY")
        
        self.ws = get_websocket_connection(jwt_token, api_key, client_id, feed_token)
        self.ws.on_open = self.on_open
        self.ws.on_data = self.on_data
        self.ws.on_error = self.on_error
        self.ws.on_close = self.on_close
        
        self.reconnect_attempts = 0
        
        # Command Subscriber (listens to Brain for dynamic subscriptions)
        self.cmd_sub = MessageBusSubscriber(CMD_PORT, topics=["CMD.SUBSCRIBE"])

    def on_open(self, wsapp):
        logger.info("[FeedService] WS Connected. Subscribing to base tokens...")
        self.reconnect_attempts = 0
        try:
            reqs = []
            if self.eq_tokens:
                reqs.append({"exchangeType": self.eq_exch_type, "tokens": self.eq_tokens})
            if self.deriv_tokens:
                reqs.append({"exchangeType": self.deriv_exch_type, "tokens": self.deriv_tokens})
            
            if reqs:
                self.ws.subscribe("mega_sub", 3, reqs)
                logger.info(f"[FeedService] Subscribed to {sum(len(r['tokens']) for r in reqs)} tokens across {len(reqs)} exchanges.")
        except Exception as e:
            logger.error(f"[FeedService] Initial subscribe error: {e}")

    def on_data(self, wsapp, message):
        if isinstance(message, dict):
            token = message.get("token")
            if token:
                # Publish tick to ZeroMQ
                self.pub.publish(f"TICK.{token}", message)

    def on_error(self, wsapp, error):
        logger.error(f"[FeedService] WS Error: {error}")
        # Force a clean disconnect so run_ws can trigger reconnect
        try:
            self.ws.close()
        except:
            pass

    def on_close(self, wsapp):
        logger.warning("[FeedService] WS Closed.")

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
                    logger.warning("[FeedService] Waking up! Exiting to force fresh AngelOne token generation via Process Supervisor.")
                    sys.exit(0)
            
            try:
                logger.info(f"[FeedService] Connecting WS (Attempt {self.reconnect_attempts})...")
                self.ws.connect()
                self.reconnect_attempts = 0
            except Exception as e:
                logger.error(f"[FeedService] Connection threw error: {e}")
                
            self.reconnect_attempts += 1
            if self.reconnect_attempts > 10:
                logger.critical("[FeedService] Max WS reconnect attempts reached. Halting for 60s.")
                time.sleep(60)
                self.reconnect_attempts = 0
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
                    exch_type = 1 if exchange == "NSE" else (2 if exchange == "NFO" else 3)
                    try:
                        self.ws.subscribe("dyn_sub", 3, [{"exchangeType": exch_type, "tokens": tokens}])
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
