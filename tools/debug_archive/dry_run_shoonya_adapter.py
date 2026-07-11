"""Dry‑run smoke test for the ShoonyaAdapter.

Loads environment variables, creates the adapter, and verifies that each
provider and the manifest can be instantiated without side‑effects.
"""

from dotenv import load_dotenv

# Load .env from the repository root
load_dotenv(dotenv_path=".env")

from src.broker.adapters.shoonya_adapter import ShoonyaAdapter

def main() -> None:
    # Instantiate the adapter – this performs the Auth 2.0 login.
    adapter = ShoonyaAdapter()
    # Verify each component can be accessed.
    assert adapter.session_provider is not None, "SessionProvider not initialized"
    assert adapter.market_data_provider is not None, "MarketDataProvider not initialized"
    assert adapter.execution_provider is not None, "ExecutionProvider not initialized"
    assert adapter.historical_provider is not None, "HistoricalProvider not initialized"
    assert adapter.portfolio_provider is not None, "PortfolioProvider not initialized"
    assert adapter.manifest is not None, "BrokerManifest not loaded"
    print("ShoonyaAdapter smoke test passed: all providers and manifest are available.")

if __name__ == "__main__":
    main()