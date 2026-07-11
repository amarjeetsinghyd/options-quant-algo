import os
import json
import logging
from typing import Optional
from src.config.engineering_config import DATA_DIR, INITIAL_PAPER_CAPITAL

logger = logging.getLogger("capital_engine")

class CapitalEngine:
    """
    Broker-agnostic Capital Engine.
    For paper trading, it persists capital locally (JSON for now, SQLite in future).
    For live trading, it will delegate to IPortfolioProvider.get_available_funds().
    """
    
    # TODO: Future migration: capital_state.json -> SQLite runtime store.
    STATE_FILE = os.path.join(DATA_DIR, "capital_state.json")

    def __init__(self, mode: str = "PAPER", portfolio_provider=None):
        self.mode = mode
        self.portfolio_provider = portfolio_provider
        self._paper_capital = INITIAL_PAPER_CAPITAL

        if self.mode == "PAPER":
            self._load_state()

    def _load_state(self):
        if os.path.exists(self.STATE_FILE):
            try:
                with open(self.STATE_FILE, "r") as f:
                    data = json.load(f)
                    self._paper_capital = float(data.get("available_funds", INITIAL_PAPER_CAPITAL))
                logger.info(f"[CapitalEngine] Loaded paper capital state: {self._paper_capital}")
            except Exception as e:
                logger.error(f"[CapitalEngine] Failed to load state: {e}. Defaulting to {INITIAL_PAPER_CAPITAL}")
                self._paper_capital = INITIAL_PAPER_CAPITAL
                self._save_state()
        else:
            logger.info(f"[CapitalEngine] First run. Initializing paper capital: {self._paper_capital}")
            self._save_state()

    def _save_state(self):
        if self.mode != "PAPER":
            return
        os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)
        try:
            with open(self.STATE_FILE, "w") as f:
                json.dump({"available_funds": self._paper_capital}, f, indent=4)
        except Exception as e:
            logger.error(f"[CapitalEngine] Failed to save state: {e}")

    def get_available_funds(self) -> float:
        if self.mode == "LIVE":
            if not self.portfolio_provider:
                raise ValueError("Portfolio provider is required for LIVE mode")
            return float(self.portfolio_provider.get_available_funds())
        return self._paper_capital

    def deduct_funds(self, amount: float):
        if self.mode == "PAPER":
            if amount > self._paper_capital:
                logger.warning(f"[CapitalEngine] Deducting more than available! (Capital: {self._paper_capital}, Amount: {amount})")
            self._paper_capital -= amount
            logger.info(f"[CapitalEngine] Deducted {amount}. New balance: {self._paper_capital}")
            self._save_state()

    def add_funds(self, amount: float):
        if self.mode == "PAPER":
            self._paper_capital += amount
            logger.info(f"[CapitalEngine] Added {amount}. New balance: {self._paper_capital}")
            self._save_state()
