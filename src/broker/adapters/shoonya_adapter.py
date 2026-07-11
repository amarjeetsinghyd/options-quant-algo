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
    from Shoonya_API_OAuth.api_helper import NorenApiPy
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
                        # Use set_session on SDK
                        self._api.set_session(self.userid, self.password, self.susertoken)
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
            self.susertoken = call_with_retry(
                lambda: oauth_provider.authenticate(),
                limiter=limiter
            )
            
            if self.susertoken:
                self._api.set_session(self.userid, self.password, self.susertoken)
                os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
                with open(SESSION_FILE, "w") as f:
                    json.dump({"userid": self.userid, "susertoken": self.susertoken, "updated_at": time.time()}, f)
                self.logger.info(f"Shoonya OAuth login successful for {self.userid}")
            else:
                self.logger.error(f"Shoonya OAuth login returned empty token")

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

    def get_websocket_connection(self, *args, **kwargs):
        # We return the API object; users can call api.start_websocket(...)
        return self._api

    def get_data_fetcher(self):
        """Return the data fetcher utility, resolving IMarketDataProvider abstraction."""
        from src.core.data_fetcher import DataFetcher
        return DataFetcher(self._api)


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
            buy_or_sell = "B" # Assuming Entry is Buy for our option strategy
            resp = self.exec_provider.place_order(
                buy_or_sell=buy_or_sell,
                product_type="I", # Intraday
                exchange="NFO",
                tradingsymbol=leg.symbol,
                quantity=leg.quantity,
                discloseqty=0,
                price_type="MKT",
                price=0,
                retention="DAY"
            )
            
            if resp and resp.get("stat") == "Ok":
                leg.broker_order_id = resp.get("norenordno")
                leg.status = "OPEN"
                logger.info(f"[ShoonyaOrderLifecycle] Entry Placed. OrderNo: {leg.broker_order_id}")
                return True
            else:
                logger.error(f"[ShoonyaOrderLifecycle] Entry Failed: {resp}")
                return False
        except Exception as e:
            logger.error(f"[ShoonyaOrderLifecycle] Exception during entry: {e}")
            return False

    def execute_exit(self, leg: TradeLeg, reason: str, exit_price=None) -> bool:
        logger.info(f"[ShoonyaOrderLifecycle] Initiating Exit for {leg.symbol}. Reason: {reason}")
        try:
            # Check for pending limit order in Order Book
            order_book = self.exec_provider.get_order_book()
            pending_orderno = None
            
            for o in order_book:
                if isinstance(o, dict) and o.get("tsym") == leg.symbol and o.get("status") in ["OPEN", "TRIGGER PENDING", "PENDING"]:
                    pending_orderno = o.get("norenordno")
                    break
                    
            if pending_orderno:
                logger.info(f"[ShoonyaOrderLifecycle] Found Pending Order {pending_orderno}. Modifying to MKT.")
                resp = self.exec_provider.modify_order(
                    orderno=pending_orderno,
                    exchange="NFO",
                    tradingsymbol=leg.symbol,
                    newquantity=leg.quantity, # Total Qty is required by Shoonya
                    newprice_type="MKT",
                    newprice=0.0
                )
            else:
                logger.info(f"[ShoonyaOrderLifecycle] No pending order found. Placing new MKT Sell order.")
                resp = self.exec_provider.place_order(
                    buy_or_sell="S",
                    product_type="I",
                    exchange="NFO",
                    tradingsymbol=leg.symbol,
                    quantity=leg.quantity,
                    discloseqty=0,
                    price_type="MKT",
                    price=0,
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

    def get_historical(self, exchange: str, token: str, starttime: int | None = None, endtime: int | None = None, interval: int = 1):
        if starttime is not None:
            return call_with_retry(
                lambda: self._api.get_time_price_series(exchange=exchange, token=token, starttime=starttime, endtime=endtime, interval=interval),
                limiter=self._limiter
            )
        return call_with_retry(
            lambda: self._api.get_daily_price_series(exchange=exchange, tradingsymbol=token, startdate=str(starttime or 0), enddate=str(endtime)),
            limiter=self._limiter
        )

class ShoonyaAdapter(IBrokerGateway):
    def __init__(self) -> None:
        self._api = NorenApiPy()
        
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
