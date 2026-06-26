import pandas as pd
import numpy as np
from datetime import time

def calculate_vwap(df, price_col='typical_price'):
    """
    Calculates the Daily anchored VWAP starting strictly from 09:15 AM.
    Requires a dataframe with 'timestamp', 'high', 'low', 'close', 'volume'.
    """
    df = df.copy()
    df['date'] = df['timestamp'].dt.date
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
    
    # Filter out pre-market volume (before 9:15 AM)
    market_open = time(9, 15)
    valid_vol = df['volume'].where(df['timestamp'].dt.time >= market_open, 0)
    
    # Use the specified price column (typical_price, high, or low)
    df['tpV'] = df[price_col] * valid_vol
    
    # Calculate cumulative sum per day
    df['cum_tpV'] = df.groupby('date')['tpV'].cumsum()
    df['cum_V'] = valid_vol.groupby(df['date']).cumsum()
    
    df['vwap'] = df['cum_tpV'] / df['cum_V']
    return df['vwap']

def calculate_ema(df, period=9):
    return df['close'].ewm(span=period, adjust=False).mean()

def calculate_vfi(df, period=130, coef=0.2, vcoef=2.5, vfi_smooth=5):
    """
    Volume Flow Indicator (Markos Katsanos / LazyBear implementation)
    Matches TradingView exactly.
    """
    df = df.copy()
    tp = (df['high'] + df['low'] + df['close']) / 3
    
    # inter = log( typical ) - log( typical[1] )
    inter = np.log(tp) - np.log(tp.shift(1))
    
    # vinter = stdev(inter, 30 )
    vinter = inter.rolling(window=30).std(ddof=0)
    
    # cutoff = coef * vinter * close
    cutoff = coef * vinter * df['close']
    
    # vave = sma( volume, length )[1]
    vave = df['volume'].rolling(window=period).mean().shift(1)
    
    # vmax = vave * vcoef
    vmax = vave * vcoef
    
    # vc = iff(volume < vmax, volume, vmax)
    vc = np.where(df['volume'] < vmax, df['volume'], vmax)
    
    # mf = typical - typical[1]
    mf = tp - tp.shift(1)
    
    # vcp = iff( mf > cutoff, vc, iff( mf < -cutoff, -vc, 0 ) )
    vcp = np.where(mf > cutoff, vc, np.where(mf < -cutoff, -vc, 0))
    
    # sum( vcp , length )/vave
    sum_vcp = pd.Series(vcp, index=df.index).rolling(window=period).sum()
    
    # Prevent division by zero
    vave = vave.replace(0, np.nan)
    vfi = sum_vcp / vave
    
    # vfima=ema( vfi, signalLength )
    vfi_smoothed = vfi.ewm(span=vfi_smooth, adjust=False).mean()
    
    return pd.DataFrame({'vfi': vfi, 'vfi_ema': vfi_smoothed})

def calculate_atr(df, period=14):
    """Calculates Average True Range (ATR) over period candles."""
    df = df.copy()
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=1).mean()
    return atr

def append_all_indicators(df):
    """
    Appends VWAP, EMA_9, VFI, ATR, ATR Expansion, Compression, and Regime to the DataFrame.
    """
    if df.empty or len(df) < 130:
        return df # Not enough data
        
    df['vwap'] = calculate_vwap(df, price_col='typical_price')
    df['vwap_high'] = calculate_vwap(df, price_col='high')
    df['vwap_low'] = calculate_vwap(df, price_col='low')
    
    df['ema_9'] = calculate_ema(df, period=9)
    vfi_df = calculate_vfi(df, period=130)
    df['vfi'] = vfi_df['vfi']
    df['vfi_ema'] = vfi_df['vfi_ema']
    
    # --- VSA Gatekeeper Metrics ---
    df['vol_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
    df['rvol'] = df['volume'] / df['vol_sma_20']
    
    # Body Dominance Ratio
    df['candle_range'] = df['high'] - df['low']
    df['real_body'] = abs(df['open'] - df['close'])
    
    # Avoid division by zero by replacing 0 range with a tiny number
    df['candle_range'] = df['candle_range'].replace(0, 0.0001)
    df['body_ratio'] = df['real_body'] / df['candle_range']
    
    # --- ATR & Compression Features ---
    df['atr'] = calculate_atr(df, period=14)
    df['atr_sma_20'] = df['atr'].rolling(window=20, min_periods=1).mean()
    df['atr_expansion'] = df['atr'] / df['atr_sma_20'].replace(0, 1.0)
    df['compression'] = np.where(df['atr_expansion'] < 0.85, 1.0, 0.0)
    
    # --- Market Regime ---
    # Regime: 1 if trending, 0 if ranging
    vwap_dist = df['close'] - df['vwap']
    is_above = (vwap_dist > 0).rolling(5).sum() == 5
    is_below = (vwap_dist < 0).rolling(5).sum() == 5
    df['market_regime'] = np.where(is_above | is_below, 1, 0)
    
    return df
