"""Adapter that wraps the existing Angel One integration.

The adapter implements the :class:`IBrokerGateway` protocol and delegates
calls to the legacy ``src.core.angel_connection`` module and the
``DataFetcher`` utility.
"""

from typing import Any, List

# Import static manifest models
from src.broker.models.manifest import (
    BrokerManifest,
    IdentityCapability,
    AuthenticationCapability,
    RateLimitCapability,
    WebSocketCapability,
    MarketDataCapability,
    HistoricalDataCapability,
    OrderManagementCapability,
    ProductSupportCapability,
    ExchangeSupportCapability,
    FeatureFlagCapability,
    PerformanceRecommendation,
)
from src.broker.models.instrument import UniversalInstrument
from src.broker.instrument_registry import bulk_register

import json
import os
from src.core import angel_connection
from src.config.engineering_config import DATA_DIR
from src.core.data_fetcher import DataFetcher

from src.broker.interfaces import (
    IBrokerGateway,
    ISessionProvider,
    IMarketDataProvider,
    IExecutionProvider,
    IHistoricalProvider,
    IPortfolioProvider,
)

# Concrete provider implementations ------------------------------------------------

class AngelSessionProvider(ISessionProvider):
    def __init__(self, session_data) -> None:
        self._session_data = session_data

    def get_session(self) -> Any:
        return self._session_data

class AngelMarketDataProvider(IMarketDataProvider):
    def __init__(self, api) -> None:
        # DataFetcher expects the Angel One API client instance.
        self._data_fetcher = DataFetcher(api)

    def get_data_fetcher(self) -> DataFetcher:
        return self._data_fetcher

    def get_websocket_connection(self, auth_token: str, api_key: str, client_id: str, feed_token: str) -> Any:
        # Delegates to the original helper
        return angel_connection.get_websocket_connection(
            auth_token, api_key, client_id, feed_token
        )

class AngelExecutionProvider(IExecutionProvider):
    def __init__(self, api) -> None:
        self._api = api

    def place_order(self, *args, **kwargs) -> Any:
        # The legacy code uses ``self.api`` directly; expose a thin wrapper.
        return self._api.place_order(*args, **kwargs)

class AngelHistoricalProvider(IHistoricalProvider):
    def __init__(self, api) -> None:
        self._api = api

    def get_historical(self, *args, **kwargs) -> Any:
        return self._api.get_historical_data(*args, **kwargs)

class AngelPortfolioProvider(IPortfolioProvider):
    def __init__(self, api) -> None:
        self._api = api

    def get_positions(self, *args, **kwargs) -> Any:
        return self._api.get_positions(*args, **kwargs)

# Gateway implementation ----------------------------------------------------------

class AngelOneAdapter(IBrokerGateway):
    def __init__(self) -> None:
        # Initialise the underlying Angel connection once and reuse it.
        self._api, self._session_data = angel_connection.get_angel_connection()
        self._session_provider = AngelSessionProvider(self._session_data)
        self._market_data_provider = AngelMarketDataProvider(self._api)
        self._execution_provider = AngelExecutionProvider(self._api)
        self._historical_provider = AngelHistoricalProvider(self._api)
        self._portfolio_provider = AngelPortfolioProvider(self._api)

        # -------------------------------------------------------------------
        # Static Broker Manifest – describes Angel One capabilities.
        # -------------------------------------------------------------------
        self._manifest = BrokerManifest(
            identity=IdentityCapability(
                broker_name="Angel One",
                broker_version="1.0.0",
                vendor="Angel Broking",
            ),
            authentication=AuthenticationCapability(
                mechanism="api_key",
                token_endpoint=None,
                token_refresh_supported=False,
            ),
            rate_limits=RateLimitCapability(
                rest_requests_per_sec=10.0,
                order_requests_per_sec=5.0,
                historical_requests_per_sec=2.0,
            ),
            websocket=WebSocketCapability(
                max_subscriptions=500,
                tick_format="json",
                depth_supported=False,
                heartbeat_interval_seconds=30,
                auto_reconnect=True,
            ),
            market_data=MarketDataCapability(
                live_quotes=True,
                ohlc=True,
                open_interest=False,
                market_depth=False,
                greeks=False,
                streaming_supported=True,
            ),
            historical=HistoricalDataCapability(
                max_lookback_days=365,
                max_candles_per_request=5000,
                supports_adjusted_close=False,
                supports_tick_history=False,
            ),
            order_management=OrderManagementCapability(
                modify_order=True,
                cancel_order=True,
                basket_orders=False,
                bracket_orders=False,
                cover_orders=False,
                gtt_orders=False,
                supported_order_variants=("MARKET", "LIMIT"),
            ),
            product_support=ProductSupportCapability(
                equities=True,
                futures=True,
                options=True,
                commodities=False,
                currencies=False,
                derivatives=False,
            ),
            exchange_support=ExchangeSupportCapability(
                exchanges=("NSE", "BSE"),
                primary_exchange="NSE",
            ),
            feature_flags=FeatureFlagCapability(
                paper_trading=False,
                replay_mode=False,
                simulation_mode=False,
                sandbox=False,
            ),
            performance=PerformanceRecommendation(
                recommended_batch_size=200,
                recommended_retry_delay_ms=250,
                recommended_throttling_interval_ms=1200,
                session_timeout_seconds=300,
            ),
        )



    @property
    def session_provider(self) -> ISessionProvider:
        return self._session_provider

    @property
    def market_data_provider(self) -> IMarketDataProvider:
        return self._market_data_provider

    @property
    def execution_provider(self) -> IExecutionProvider:
        return self._execution_provider

    @property
    def historical_provider(self) -> IHistoricalProvider:
        return self._historical_provider

    @property
    def portfolio_provider(self) -> IPortfolioProvider:
        return self._portfolio_provider

    @property
    def api(self) -> Any:
        """Expose the underlying Angel API client for legacy callers.

        Some existing services (e.g., PaperTrader) expect direct access to the
        SDK instance.  The adapter provides it via this read‑only property.
        """
        return self._api



    @property
    def manifest(self) -> BrokerManifest:
        """Return the static :class:`BrokerManifest` describing Angel One.

        The registry registers the adapter and reads this property to obtain
        the broker's immutable capability description.
        """
        return self._manifest
