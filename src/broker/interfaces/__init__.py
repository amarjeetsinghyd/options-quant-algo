"""Broker abstraction interfaces.

These define the contract that concrete broker adapters must fulfil.
"""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

# Primary gateway interface exposing sub‑services
class IBrokerGateway(Protocol):
    """Top‑level broker gateway exposing domain‑specific providers."""

    @property
    def session_provider(self) -> "ISessionProvider":
        ...

    @property
    def market_data_provider(self) -> "IMarketDataProvider":
        ...

    @property
    def execution_provider(self) -> "IExecutionProvider":
        ...

    @property
    def historical_provider(self) -> "IHistoricalProvider":
        ...

    @property
    def portfolio_provider(self) -> "IPortfolioProvider":
        ...

# Individual provider interfaces
class ISessionProvider(Protocol):
    @abstractmethod
    def get_session(self) -> "any":
        """Return a broker session object (e.g., authentication token)."""

class IMarketDataProvider(Protocol):
    @abstractmethod
    def get_data_fetcher(self) -> "any":
        """Return a data fetcher utility for market data."""

    @abstractmethod
    def get_websocket_connection(self, *args, **kwargs) -> "any":
        """Create and return a websocket connection for live market data."""

class IExecutionProvider(Protocol):
    @abstractmethod
    def place_order(self, *args, **kwargs) -> "any":
        """Place an order with the broker."""

class IHistoricalProvider(Protocol):
    @abstractmethod
    def get_historical(self, *args, **kwargs) -> "any":
        """Fetch historical market data."""

class IPortfolioProvider(Protocol):
    @abstractmethod
    def get_positions(self, *args, **kwargs) -> "any":
        """Retrieve current portfolio positions."""
