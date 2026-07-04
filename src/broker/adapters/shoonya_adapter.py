"""Skeleton adapter for the Shoonya broker.

All methods raise :class:`BrokerFeatureUnavailableError` because the Shoonya
SDK is not yet integrated.
"""

from src.broker.exceptions import BrokerFeatureUnavailableError
from typing import Any, List

# Import manifest models for a static description of Shoonya capabilities.
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
from src.broker.interfaces import (
    IBrokerGateway,
    ISessionProvider,
    IMarketDataProvider,
    IExecutionProvider,
    IHistoricalProvider,
    IPortfolioProvider,
)

# Minimal provider implementations that raise the feature‑unavailable error

class _UnavailableProvider:
    def __getattr__(self, name):
        def _unavailable(*args, **kwargs):
            raise BrokerFeatureUnavailableError(
                f"Shoonya adapter does not implement '{name}'."
            )
        return _unavailable

class ShoonyaAdapter(IBrokerGateway):
    def __init__(self) -> None:
        self._session_provider = _UnavailableProvider()
        self._market_data_provider = _UnavailableProvider()
        self._execution_provider = _UnavailableProvider()
        self._historical_provider = _UnavailableProvider()
        self._portfolio_provider = _UnavailableProvider()

        # Minimal static manifest – fields are filled with generic placeholders
        # because the Shoonya SDK is not yet integrated.
        self._manifest = BrokerManifest(
            identity=IdentityCapability(
                broker_name="Shoonya",
                broker_version="0.0.0",
                vendor="Shoonya",
            ),
            authentication=AuthenticationCapability(
                mechanism="api_key",
                token_endpoint=None,
                token_refresh_supported=False,
            ),
            rate_limits=RateLimitCapability(
                rest_requests_per_sec=5.0,
                order_requests_per_sec=2.0,
                historical_requests_per_sec=1.0,
            ),
            websocket=WebSocketCapability(
                max_subscriptions=200,
                tick_format="json",
                depth_supported=False,
                heartbeat_interval_seconds=30,
                auto_reconnect=True,
            ),
            market_data=MarketDataCapability(
                live_quotes=False,
                ohlc=False,
                open_interest=False,
                market_depth=False,
                greeks=False,
                streaming_supported=False,
            ),
            historical=HistoricalDataCapability(
                max_lookback_days=0,
                max_candles_per_request=0,
                supports_adjusted_close=False,
                supports_tick_history=False,
            ),
            order_management=OrderManagementCapability(
                modify_order=False,
                cancel_order=False,
                basket_orders=False,
                bracket_orders=False,
                cover_orders=False,
                gtt_orders=False,
                supported_order_variants=(),
            ),
            product_support=ProductSupportCapability(
                equities=False,
                futures=False,
                options=False,
                commodities=False,
                currencies=False,
                derivatives=False,
            ),
            exchange_support=ExchangeSupportCapability(
                exchanges=(),
                primary_exchange="",
            ),
            feature_flags=FeatureFlagCapability(
                paper_trading=False,
                replay_mode=False,
                simulation_mode=False,
                sandbox=False,
            ),
            performance=PerformanceRecommendation(
                recommended_batch_size=0,
                recommended_retry_delay_ms=0,
                recommended_throttling_interval_ms=0,
                session_timeout_seconds=0,
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
    def manifest(self) -> BrokerManifest:
        """Return a placeholder manifest for Shoonya.

        The manifest is static and provides enough information for the
        registry to expose broker capabilities even though the SDK is not yet
        implemented.
        """
        return self._manifest


