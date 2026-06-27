import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

from src.utils.logger import get_logger
from src.core.research_collector import ResearchCollector

logger = get_logger("analytics_engine")

# ── Feature engineering thresholds ───────────────────────────────────────────
VFI_PERIOD = 130
VFI_SMOOTH = 3
EMA_PERIOD = 9


class AnalyticsEngine:
    """
    Lightweight analytics engine. Provides:
    
    1) Feature engineering from archived Parquet data:
       - VFI (Volume Flow Indicator)
       - 9 EMA
       - VWAP
       - Volume-based metrics
       
    2) Signal generation aligned with the VFI+EMA+VWAP strategy
    3) Placeholder for future ML (XGBoost) integration
    
    Zero heavy dependencies — built for local production robustness.
    """

    def __init__(self):
        pass

    # ── Load data ─────────────────────────────────────────────────────────────

    @staticmethod
    def load_data(
        symbol: str,
        timeframe: str,
        lookback_days: int = 30,
    ) -> pd.DataFrame:
        """
        Load archived OHLCV data from Parquet files via ResearchCollector.load().
        Returns DataFrame with 'timestamp', 'open', 'high', 'low', 'close', 'volume'.
        """
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        df = ResearchCollector.load(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        if df.empty:
            logger.warning("No data loaded for %s/%s.", symbol, timeframe)
        return df

    # ── Feature engineering ──────────────────────────────────────────────────

    @staticmethod
    def compute_vfi(df: pd.DataFrame, period: int = VFI_PERIOD, smooth: int = VFI_SMOOTH) -> pd.DataFrame:
        """
        Volume Flow Indicator (VFI).
        Logic:
          - Typical Price = (high + low + close) / 3
          - Price Change = typical - previous_typical
          - Volume Flow = volume * price_change / typical
          - VFI = rolling_sum(volume_flow, period) / rolling_sum(volume, period) * coef
          - Smooth with SMA(smooth)
        """
        df = df.copy()
        df["typical"] = (df["high"] + df["low"] + df["close"]) / 3
        df["price_change"] = df["typical"] - df["typical"].shift(1)
        df["volume_flow"] = df["volume"] * df["price_change"] / df["typical"].replace(0, np.nan)

        vol_sum = df["volume"].rolling(window=period).sum()
        flow_sum = df["volume_flow"].rolling(window=period).sum()
        df["vfi_raw"] = (flow_sum / vol_sum.replace(0, np.nan)) * 100

        # Smooth
        df["vfi"] = df["vfi_raw"].rolling(window=smooth).mean()
        df["vfi_ma"] = df["vfi"].rolling(window=smooth).mean()

        return df.drop(columns=["typical", "price_change", "volume_flow", "vfi_raw"])

    @staticmethod
    def compute_ema(df: pd.DataFrame, period: int = EMA_PERIOD) -> pd.DataFrame:
        """Add 9 EMA column."""
        df = df.copy()
        df["ema_9"] = df["close"].ewm(span=period, adjust=False).mean()
        return df

    @staticmethod
    def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """
        VWAP = cumulative(volume * typical_price) / cumulative(volume).
        Resets daily if 'timestamp' exists.
        """
        df = df.copy()
        df["typical"] = (df["high"] + df["low"] + df["close"]) / 3

        if "timestamp" in df.columns:
            df["date"] = pd.to_datetime(df["timestamp"]).dt.date
            df["cum_vol"] = df.groupby("date")["volume"].cumsum()
            df["cum_tp_vol"] = df.groupby("date")["typical"].transform(lambda x: (x * df.loc[x.index, "volume"]).cumsum())
        else:
            df["cum_vol"] = df["volume"].cumsum()
            df["cum_tp_vol"] = (df["typical"] * df["volume"]).cumsum()

        df["vwap"] = df["cum_tp_vol"] / df["cum_vol"].replace(0, np.nan)
        return df.drop(columns=["typical", "cum_vol", "cum_tp_vol"] + (["date"] if "date" in df.columns else []))

    # ── Combined pipeline ──────────────────────────────────────────────────────

    @classmethod
    def enrich(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        Full feature-engineering pipeline:
          1) VFI
          2) 9 EMA
          3) VWAP
        Returns enriched DataFrame.
        """
        if df.empty:
            return df
        df = cls.compute_vfi(df)
        df = cls.compute_ema(df)
        df = cls.compute_vwap(df)
        return df

    # ── Signal generation (VFI + EMA + VWAP strategy) ─────────────────────────────

    @staticmethod
    def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply VFI + 9 EMA + VWAP logic to generate buy/sell signals.
        
        BUY:  VFI crosses above 0  AND  9 EMA > VWAP
        SELL: VFI crosses below 0  AND  9 EMA < VWAP
        
        Adds 'signal' column: 1 (BUY), -1 (SELL), 0 (HOLD)
        """
        df = df.copy()
        df["vfi_cross_up"]   = (df["vfi"] > 0) & (df["vfi"].shift(1) <= 0)
        df["vfi_cross_down"] = (df["vfi"] < 0) & (df["vfi"].shift(1) >= 0)
        df["ema_above_vwap"] = df["ema_9"] > df["vwap"]
        df["ema_below_vwap"] = df["ema_9"] < df["vwap"]

        df["signal"] = 0
        df.loc[df["vfi_cross_up"] & df["ema_above_vwap"], "signal"] = 1   # BUY
        df.loc[df["vfi_cross_down"] & df["ema_below_vwap"], "signal"] = -1 # SELL

        return df.drop(columns=["vfi_cross_up", "vfi_cross_down", "ema_above_vwap", "ema_below_vwap"])

    # ── ML Placeholder (XGBoost integration) ─────────────────────────────────────

    @staticmethod
    def train_xgboost(X_train: pd.DataFrame, y_train: pd.Series):
        """
        Placeholder for XGBoost model training.
        To be implemented when ML integration is enabled.
        """
        logger.info("XGBoost training not yet implemented (deferred to future phase).")
        return None

    @staticmethod
    def predict_xgboost(model, X_test: pd.DataFrame):
        """
        Placeholder for XGBoost inference.
        """
        logger.info("XGBoost prediction not yet implemented.")
        return None
