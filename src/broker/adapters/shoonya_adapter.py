import os
import json
import time
import logging

from src.broker.exceptions import BrokerFeatureUnavailableError
from src.broker.models.manifest import BrokerManifest, IdentityCapability, AuthenticationCapability, RateLimitCapability, WebSocketCapability, MarketDataCapability, HistoricalDataCapability, OrderManagementCapability, ProductSupportCapability, ExchangeSupportCapability, FeatureFlagCapability, PerformanceRecommendation
from src.core.rate_limiter import TokenBucketLimiter, call_with_retry
from src.broker.interfaces import IBrokerGateway, ISessionProvider, IMarketDataProvider, IExecutionProvider, IHistoricalProvider, IPortfolioProvider
from src.execution.order_lifecycle import OrderLifecycle
from src.execution.trade_context import TradeLeg

logger = logging.getLogger("shoonya_adapter")

try:
    from NorenRestApiPy.NorenApi import NorenApi as NorenApiPy
except Exception as e:
    from src.config.engineering_config import ENABLE_LIVE_BROKERAGE_EXECUTION
    if ENABLE_LIVE_BROKERAGE_EXECUTION:
        logger.critical(f"Shoonya SDK import failed in LIVE mode: {e}")
        raise
    
    logger.error(f"Shoonya SDK import failed: {e}. Falling back to mock for PAPER/DEV mode.")
    class _MockNorenApi:
        def __init__(self, *args, **kwargs): pass
        def login(self, *args, **kwargs): return {"status": True, "susertoken": "dummy_token"}
        def set_session(self, *args, **kwargs): pass
        def get_limits(self, *args, **kwargs): return {"status": "ok", "cash": "100000.00"}
        def get_positions(self, *args, **kwargs): return []
        def get_holdings(self, *args, **kwargs): return []
        def get_quotes(self, *args, **kwargs): return {"status": "ok"}
        def get_time_price_series(self, *args, **kwargs): return []
        def get_daily_price_series(self, *args, **kwargs): return []
        def searchscrip(self, *args, **kwargs): return {"values": []}
        def place_order(self, *args, **kwargs): return {"status": "Ok", "norenordno": "dummy_id"}
        def modify_order(self, *args, **kwargs): return {"status": "Ok"}
        def cancel_order(self, *args, **kwargs): return {"status": "Ok"}
        def get_order_book(self, *args, **kwargs): return []
        def get_trade_book(self, *args, **kwargs): return []
    NorenApiPy = _MockNorenApi

SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "shoonya_session.json")


class ShoonyaSessionProvider(ISessionProvider):
    def __init__(self, api: NorenApiPy) -> None:
        self.logger = logger
        self._api = api
        
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env")
        load_dotenv(dotenv_path=env_path)
        
        self.client_id = os.getenv("SHOONYA_CLIENT_ID", "")
        self.client_secret = os.getenv("SHOONYA_CLIENT_SECRET", "")
        self.userid = os.getenv("SHOONYA_USERNAME", "")
        self.password = os.getenv("SHOONYA_PASSWORD", "")
        self.totp = os.getenv("SHOONYA_TOTP", "")
        self.susertoken = None
        self._restore_or_login()

    def _restore_or_login(self):
        # 1. Attempt to restore from JSON
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "r") as f:
                    data = json.load(f)
                    if data.get("userid") == self.userid and data.get("susertoken"):
                        self.susertoken = data["susertoken"]
                        actid = data.get("actid", self.userid)  # fallback to userid if missing
                        # CRITICAL: OAuth API requires injectOAuthHeader (Bearer token), NOT set_session.
                        # set_session() only sets the old password-auth susertoken and never populates
                        # __OAuthHeaders, so all OAuth API calls fail with 'Invalid Session Key'.
                        # HOWEVER, start_websocket NEEDS self.__access_token, which is only set by set_session!
                        # We must call BOTH to satisfy REST and WebSocket endpoints!
                        self._api.set_session(self.userid, self.password, self.susertoken, self.susertoken)
                        self._api.injectOAuthHeader(self.susertoken, self.userid, actid)
                        # Validate the session with a lightweight call
                        limits = self._api.get_limits()
                        if isinstance(limits, dict) and limits.get("stat") != "Not_Ok":
                            self.logger.info(f"Restored and validated Shoonya session for {self.userid}")
                            return
                        else:
                            self.logger.warning(f"Restored session invalid or expired for {self.userid}. Re-authenticating.")
                            self.susertoken = None
            except Exception as e:
                self.logger.error(f"Failed to restore Shoonya session: {e}")

        # 2. If no valid session, Login
        self._login()

    def _login(self):
        if not self.client_id or not self.userid:
            self.logger.warning("Shoonya credentials missing in .env")
            return
            
        try:
            from src.broker.adapters.shoonya_auth import ShoonyaHeadlessOAuthProvider
            oauth_provider = ShoonyaHeadlessOAuthProvider(
                client_id=self.client_id,
                client_secret=self.client_secret,
                userid=self.userid,
                password=self.password,
                totp_secret=self.totp
            )
            
            limiter = TokenBucketLimiter(per_second=1, name="shoonya_oauth")
            auth_code = call_with_retry(
                lambda: oauth_provider.authenticate(),
                limiter=limiter
            )
            
            if auth_code:
                result = self._api.getAccessToken(auth_code, self.client_secret, self.client_id, self.userid)
                if result is not None:
                    acc_tok, usrid, ref_tok, actid = result
                    self.susertoken = acc_tok
                    self.logger.info("Shoonya getAccessToken successful.")
                    # getAccessToken calls injectOAuthHeader internally for REST, but does NOT set __access_token
                    # which is required for the WebSocket. We must call set_session.
                    self._api.set_session(self.userid, self.password, self.susertoken, self.susertoken)
                    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
                    with open(SESSION_FILE, "w") as f:
                        json.dump({
                            "userid": self.userid,
                            "susertoken": self.susertoken,
                            "actid": actid,
                            "updated_at": time.time()
                        }, f)
                    self.logger.info(f"Shoonya OAuth login successful for {self.userid}")
                else:
                    self.logger.error("Failed to retrieve access token via getAccessToken")
            else:
                self.logger.error("Shoonya OAuth login failed: No auth code returned")

        except Exception as e:
            self.logger.error(f"Exception during Shoonya login: {e}")

    def get_session(self) -> dict:
        return {"access_token": self.susertoken}


class ShoonyaMarketDataProvider(IMarketDataProvider):
    QUOTE_LIMITER = TokenBucketLimiter(per_second=10, per_minute=500, name="shoonya_quote")
    HISTORICAL_LIMITER = TokenBucketLimiter(per_second=3, per_minute=180, name="shoonya_historical")

    def __init__(self, api: NorenApiPy):
        self._api = api

    def get_quotes(self, instrument_ids: list) -> dict:
        # Example API format for get_quotes is per exchange/token
        # Our adapter simplifies it here. In a real system it's called per symbol.
        res = {}
        for inst in instrument_ids:
            exch, token = inst.split(":") if ":" in inst else ("NSE", inst)
            data = call_with_retry(lambda: self._api.get_quotes(exchange=exch, token=token), limiter=self.QUOTE_LIMITER)
            res[inst] = data
        return res

    def search_instruments(self, query: str) -> list:
        resp = call_with_retry(
            lambda: self._api.searchscrip(exchange="NSE", searchtext=query),
            limiter=self.QUOTE_LIMITER
        )
        return resp.get("values", []) if isinstance(resp, dict) else resp

    def get_historical(self, exchange: str, token: str, starttime=None, endtime=None, interval=1) -> dict:
        if starttime is not None:
            resp = call_with_retry(
                lambda: self._api.get_time_price_series(exchange=exchange, token=token, starttime=starttime, endtime=endtime, interval=interval),
                limiter=self.HISTORICAL_LIMITER
            )
        else:
            resp = call_with_retry(
                lambda: self._api.get_daily_price_series(exchange=exchange, tradingsymbol=token, startdate=str(starttime), enddate=str(endtime)),
                limiter=self.HISTORICAL_LIMITER
            )
        return resp

    def start_live_feed(self, on_tick_callback, on_open_callback=None, on_error_callback=None) -> None:
        """Start the live market data WebSocket feed, abstracting NorenApiPy."""
        
        def event_handler_quote_update(message):
            if isinstance(message, dict):
                token = message.get("tk")
                if not token:
                    return
                # Calculate delta volume (ltq) since Shoonya may only send total volume 'v'
                v_total = int(message.get("v", 0) or 0)
                ltq = int(message.get("ltq", 0) or 0)
                if ltq == 0 and v_total > 0:
                    if not hasattr(self, "_last_vol"):
                        self._last_vol = {}
                    
                    prev_v = self._last_vol.get(token, 0)
                    if prev_v > 0 and v_total > prev_v:
                        ltq = v_total - prev_v
                    
                    self._last_vol[token] = v_total

                # Map Shoonya's payload to the standardized TickData format
                std_msg = {
                    "token": str(token),
                    "exchange": message.get("e", "NSE"),
                    "last_traded_price": float(message.get("lp", 0) or 0),
                    "last_traded_quantity": int(ltq),
                    "volume_trade_for_the_day": int(v_total),
                    "average_traded_price": float(message.get("ap", 0) or 0),
                    "open": float(message.get("o", 0) or 0),
                    "high": float(message.get("h", 0) or 0),
                    "low": float(message.get("l", 0) or 0),
                    "close": float(message.get("c", 0) or 0),
                    "percent_change": float(message.get("pc", 0) or 0),
                }
                
                # Add Best Bid/Ask in standard fields
                if "bp1" in message:
                    std_msg["bid"] = float(message["bp1"])
                if "sp1" in message:
                    std_msg["ask"] = float(message["sp1"])

                # Remove zero values where we might not have received a full tick yet
                std_msg = {k: v for k, v in std_msg.items() if v != 0 or k in ["last_traded_price"]}
                on_tick_callback(std_msg)

        def event_handler_order_update(message):
            pass # Order updates handled separately by ExecutionManager (if via WS)

        def open_callback():
            if on_open_callback:
                on_open_callback()

        def error_callback(err):
            if on_error_callback:
                on_error_callback(err)

        def close_callback():
            pass

        self._api.start_websocket(
            order_update_callback=event_handler_order_update,
            subscribe_callback=event_handler_quote_update,
            socket_open_callback=open_callback,
            socket_close_callback=close_callback,
            socket_error_callback=error_callback
        )

    def subscribe(self, tokens: list, exchange: str) -> None:
        """Translates generic tokens into Shoonya format and subscribes."""
        if not tokens: return
        shoonya_tokens = [f"{exchange}|{t}" for t in tokens]
        # Subscribe with feed_type='d' (depth) to get bid/ask fields (bp1, sp1)
        self._api.subscribe(shoonya_tokens, feed_type='d')
        
    def unsubscribe(self, tokens: list, exchange: str) -> None:
        """Translates generic tokens into Shoonya format and unsubscribes."""
        if not tokens: return
        shoonya_tokens = [f"{exchange}|{t}" for t in tokens]
        self._api.unsubscribe(shoonya_tokens, feed_type='d')
    def get_quote(self, exchange: str, token: str) -> dict:
        """Fetch the latest snapshot quote for a given token."""
        try:
            res = self._api.get_quotes(exchange=exchange, token=token)
            if isinstance(res, dict) and 'lp' in res:
                return {"ltp": float(res['lp'])}
        except Exception:
            pass
        return {"ltp": 0.0}


class ShoonyaPortfolioProvider(IPortfolioProvider):
    def __init__(self, api: NorenApiPy):
        self._api = api
        self._limiter = TokenBucketLimiter(per_second=5, name="shoonya_portfolio")

    def get_positions(self, *args, **kwargs) -> list:
        return call_with_retry(lambda: self._api.get_positions() or [], limiter=self._limiter)

    def get_holdings(self, *args, **kwargs) -> list:
        return call_with_retry(lambda: self._api.get_holdings() or [], limiter=self._limiter)

    def get_limits(self, *args, **kwargs) -> dict:
        res = call_with_retry(lambda: self._api.get_limits() or {}, limiter=self._limiter)
        return res

    def get_available_funds(self) -> float:
        limits = self.get_limits()
        if isinstance(limits, dict) and "cash" in limits:
            return float(limits["cash"])
        return 0.0


class ShoonyaExecutionProvider(IExecutionProvider):
    def __init__(self, api: NorenApiPy):
        self._api = api
        self._order_limiter = TokenBucketLimiter(per_second=2, name="shoonya_order")

    def place_order(self, **order):
        return call_with_retry(lambda: self._api.place_order(**order), limiter=self._order_limiter)

    def modify_order(self, **kwargs):
        return call_with_retry(lambda: self._api.modify_order(**kwargs), limiter=self._order_limiter)

    def cancel_order(self, orderno: str):
        return call_with_retry(lambda: self._api.cancel_order(orderno=orderno), limiter=self._order_limiter)

    def get_order_book(self):
        return call_with_retry(lambda: self._api.get_order_book() or [], limiter=self._order_limiter)


class ShoonyaOrderLifecycle(OrderLifecycle):
    def __init__(self, execution_provider: ShoonyaExecutionProvider):
        self.exec_provider = execution_provider

    def execute_entry(self, leg: TradeLeg) -> bool:
        logger.info(f"[ShoonyaOrderLifecycle] Initiating Entry for {leg.symbol} (Qty: {leg.quantity})")
        try:
            # Fetch fresh LTP for marketable limit order
            ltp = float(leg.entry_price or 0.0)
            try:
                quote = self.exec_provider._api.get_quotes(exchange="NFO", token=leg.token)
                if quote and "lp" in quote:
                    ltp = float(quote["lp"])
            except Exception as e:
                logger.warning(f"[ShoonyaOrderLifecycle] Could not fetch fresh LTP, using entry_price: {e}")

            if ltp <= 0:
                logger.error("[ShoonyaOrderLifecycle] Invalid LTP for entry.")
                return False

            buffer = max(0.5, ltp * 0.015)
            limit_price = round((ltp + buffer) / 0.05) * 0.05

            resp = self.exec_provider.place_order(
                buy_or_sell="B",
                product_type="I",
                exchange="NFO",
                tradingsymbol=leg.symbol,
                quantity=leg.quantity,
                discloseqty=0,
                price_type="LMT",
                price=limit_price,
                retention="DAY"
            )
            
            if resp and resp.get("stat") == "Ok":
                leg.broker_order_id = resp.get("norenordno")
                leg.status = "OPEN"
                logger.info(f"[ShoonyaOrderLifecycle] Entry Placed. OrderNo: {leg.broker_order_id} at Limit: {limit_price}")
                return True
            else:
                logger.error(f"[ShoonyaOrderLifecycle] Entry Failed: {resp}")
                return False
        except Exception as e:
            logger.error(f"[ShoonyaOrderLifecycle] Exception during entry: {e}")
            return False

    def place_sl_order(self, leg: TradeLeg, sl_trigger: float, sl_limit: float) -> str:
        """Places the initial SL-LMT order."""
        try:
            sl_trigger = round(sl_trigger / 0.05) * 0.05
            sl_limit = round(sl_limit / 0.05) * 0.05
            logger.info(f"[ShoonyaOrderLifecycle] Placing SL order for {leg.symbol}. Trigger: {sl_trigger}, Limit: {sl_limit}")
            
            resp = self.exec_provider.place_order(
                buy_or_sell="S",
                product_type="I",
                exchange="NFO",
                tradingsymbol=leg.symbol,
                quantity=leg.quantity,
                discloseqty=0,
                price_type="SL-LMT",
                price=sl_limit,
                trigger_price=sl_trigger,
                retention="DAY"
            )
            if resp and resp.get("stat") == "Ok":
                return resp.get("norenordno")
            else:
                logger.error(f"[ShoonyaOrderLifecycle] SL placement failed: {resp}")
                return None
        except Exception as e:
            logger.error(f"[ShoonyaOrderLifecycle] Exception placing SL: {e}")
            return None

    def modify_sl_order(self, leg: TradeLeg, sl_orderno: str, new_trigger: float, new_limit: float) -> bool:
        """Modifies an existing SL-LMT order."""
        try:
            new_trigger = round(new_trigger / 0.05) * 0.05
            new_limit = round(new_limit / 0.05) * 0.05
            logger.info(f"[ShoonyaOrderLifecycle] Modifying SL order {sl_orderno} to Trigger: {new_trigger}")
            
            resp = self.exec_provider.modify_order(
                orderno=sl_orderno,
                exchange="NFO",
                tradingsymbol=leg.symbol,
                newquantity=leg.quantity,
                newprice_type="SL-LMT",
                newprice=new_limit,
                newtrigger_price=new_trigger
            )
            return resp and resp.get("stat", "").lower() == "ok"
        except Exception as e:
            logger.error(f"[ShoonyaOrderLifecycle] Exception modifying SL: {e}")
            return False

    def execute_exit(self, leg: TradeLeg, reason: str, exit_price=None, pending_sl_orderno=None) -> bool:
        logger.info(f"[ShoonyaOrderLifecycle] Initiating Exit for {leg.symbol}. Reason: {reason}")
        try:
            ltp = float(exit_price or leg.current_price or 0.0)
            buffer = max(0.5, ltp * 0.015)
            limit_price = round((ltp - buffer) / 0.05) * 0.05
            
            if pending_sl_orderno:
                logger.info(f"[ShoonyaOrderLifecycle] Modifying SL order {pending_sl_orderno} to marketable Limit.")
                resp = self.exec_provider.modify_order(
                    orderno=pending_sl_orderno,
                    exchange="NFO",
                    tradingsymbol=leg.symbol,
                    newquantity=leg.quantity,
                    newprice_type="LMT",
                    newprice=limit_price
                )
            else:
                # Check for pending limit order in Order Book if sl_orderno not provided
                order_book = self.exec_provider.get_order_book()
                pending_orderno = None
                
                for o in order_book:
                    if isinstance(o, dict) and o.get("tsym") == leg.symbol and o.get("status") in ["OPEN", "TRIGGER PENDING", "PENDING"]:
                        pending_orderno = o.get("norenordno")
                        break
                        
                if pending_orderno:
                    logger.info(f"[ShoonyaOrderLifecycle] Found Pending Order {pending_orderno}. Modifying to LMT.")
                    resp = self.exec_provider.modify_order(
                        orderno=pending_orderno,
                        exchange="NFO",
                        tradingsymbol=leg.symbol,
                        newquantity=leg.quantity,
                        newprice_type="LMT",
                        newprice=limit_price
                    )
                else:
                    logger.info(f"[ShoonyaOrderLifecycle] No pending order found. Placing new LMT Sell order.")
                    resp = self.exec_provider.place_order(
                        buy_or_sell="S",
                        product_type="I",
                        exchange="NFO",
                        tradingsymbol=leg.symbol,
                        quantity=leg.quantity,
                        discloseqty=0,
                        price_type="LMT",
                        price=limit_price,
                        retention="DAY"
                    )
                
            if resp and resp.get("stat", "").lower() == "ok":
                leg.close_leg(exit_price or leg.current_price, reason)
                return True
            else:
                logger.error(f"[ShoonyaOrderLifecycle] Exit Action Failed: {resp}")
                return False
                
        except Exception as e:
            logger.error(f"[ShoonyaOrderLifecycle] Exception during exit: {e}")
            return False


class ShoonyaHistoricalProvider(IHistoricalProvider):
    def __init__(self, api: NorenApiPy):
        self._api = api
        self._limiter = TokenBucketLimiter(per_second=3, name="shoonya_historical")

    def get_historical(self, exchange: str, token: str, interval: str, start_time, end_time) -> "pd.DataFrame":
        import pandas as pd
        import datetime
        from src.utils.logger import get_logger
        logger = get_logger("shoonya_adapter")

        # Shoonya expects UNIX timestamp (seconds) or date string
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())

        # Map 'ONE_MINUTE' to Shoonya interval format (in minutes)
        interval_map = {
            "ONE_MINUTE": 1,
            "THREE_MINUTE": 3,
            "FIVE_MINUTE": 5,
            "TEN_MINUTE": 10,
            "FIFTEEN_MINUTE": 15,
            "THIRTY_MINUTE": 30,
            "ONE_HOUR": 60,
            "ONE_DAY": 1440
        }
        shoonya_interval = interval_map.get(interval, 1)

        from src.core.rate_limiter import call_with_retry
        
        try:
            if shoonya_interval < 1440:
                resp = call_with_retry(
                    lambda: self._api.get_time_price_series(exchange=exchange, token=token, starttime=start_ts, endtime=end_ts, interval=shoonya_interval),
                    limiter=self._limiter
                )
            else:
                resp = call_with_retry(
                    lambda: self._api.get_daily_price_series(exchange=exchange, tradingsymbol=token, startdate=start_time.strftime('%Y-%m-%d'), enddate=end_time.strftime('%Y-%m-%d')),
                    limiter=self._limiter
                )
            
            if isinstance(resp, list) and len(resp) > 0:
                df = pd.DataFrame(resp)
                
                # Shoonya time price series format mapping:
                # time -> timestamp, into -> open, inth -> high, intl -> low, intc -> close, intv -> volume
                # Shoonya daily price series format mapping:
                # time -> timestamp, into -> open, inth -> high, intl -> low, intc -> close, intv -> volume
                rename_map = {
                    'time': 'timestamp',
                    'ssboe': 'timestamp',  # Some endpoints return ssboe for timestamp
                    'into': 'open',
                    'inth': 'high',
                    'intl': 'low',
                    'intc': 'close',
                    'intv': 'volume',
                    'v': 'volume', # Daily might just use v
                }
                
                df.rename(columns=rename_map, inplace=True)
                
                # Standardize columns
                required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                for col in required_cols:
                    if col not in df.columns:
                        df[col] = 0
                
                df = df[required_cols]
                
                # Convert timestamp
                if df['timestamp'].dtype == 'O': # string format
                    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed', dayfirst=True)
                else: # numerical
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                    
                # Convert to numeric
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                return df
                
        except Exception as e:
            logger.error(f"Shoonya historical data error for {token}: {e}")
            
        return pd.DataFrame()

class ShoonyaAdapter(IBrokerGateway):
    def __init__(self) -> None:
        self._api = NorenApiPy(host='https://api.shoonya.com/NorenWClientAPI/', websocket='wss://api.shoonya.com/NorenWSAPI/')
        
        self._session_provider = ShoonyaSessionProvider(self._api)
        self._market_data_provider = ShoonyaMarketDataProvider(self._api)
        self._execution_provider = ShoonyaExecutionProvider(self._api)
        self._portfolio_provider = ShoonyaPortfolioProvider(self._api)
        self._historical_provider = ShoonyaHistoricalProvider(self._api)
        
        self.order_lifecycle = ShoonyaOrderLifecycle(self._execution_provider)

        self._manifest = BrokerManifest(
            identity=IdentityCapability(broker_name="Shoonya", broker_version="1.0", vendor="Shoonya"),
            authentication=AuthenticationCapability(mechanism="oauth", token_endpoint="/QuickAuth", token_refresh_supported=True),
            rate_limits=RateLimitCapability(rest_requests_per_sec=5.0, order_requests_per_sec=2.0, historical_requests_per_sec=1.0),
            websocket=WebSocketCapability(max_subscriptions=200, tick_format="json", depth_supported=False, heartbeat_interval_seconds=30, auto_reconnect=True),
            market_data=MarketDataCapability(live_quotes=True, ohlc=True, open_interest=False, market_depth=False, greeks=False, streaming_supported=True),
            historical=HistoricalDataCapability(max_lookback_days=1000, max_candles_per_request=1000, supports_adjusted_close=False, supports_tick_history=True),
            order_management=OrderManagementCapability(modify_order=True, cancel_order=True, basket_orders=True, bracket_orders=False, cover_orders=True, gtt_orders=False, supported_order_variants=()),
            product_support=ProductSupportCapability(equities=True, futures=True, options=True, commodities=True, currencies=True, derivatives=True),
            exchange_support=ExchangeSupportCapability(exchanges=("NSE", "NFO", "BSE", "MCX"), primary_exchange="NSE"),
            feature_flags=FeatureFlagCapability(paper_trading=False, replay_mode=False, simulation_mode=False, sandbox=False),
            performance=PerformanceRecommendation(recommended_batch_size=50, recommended_retry_delay_ms=500, recommended_throttling_interval_ms=200, session_timeout_seconds=86400)
        )

    @property
    def session_provider(self) -> ISessionProvider: return self._session_provider
    @property
    def market_data_provider(self) -> IMarketDataProvider: return self._market_data_provider
    @property
    def execution_provider(self) -> IExecutionProvider: return self._execution_provider
    @property
    def historical_provider(self) -> IHistoricalProvider: return self._historical_provider
    @property
    def portfolio_provider(self) -> IPortfolioProvider: return self._portfolio_provider
    @property
    def manifest(self) -> BrokerManifest: return self._manifest
    
    def get_order_lifecycle(self) -> OrderLifecycle:
        return self.order_lifecycle
