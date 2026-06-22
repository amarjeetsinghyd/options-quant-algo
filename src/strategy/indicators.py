import pandas as pd
import numpy as np

def calculate_vwap(df):
    """
    Calculates the Daily anchored VWAP.
    Requires a dataframe with 'timestamp', 'high', 'low', 'close', 'volume'.
    """
    df = df.copy()
    df['date'] = df['timestamp'].dt.date
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
    df['tpV'] = df['typical_price'] * df['volume']
    
    # Calculate cumulative sum per day
    df['cum_tpV'] = df.groupby('date')['tpV'].cumsum()
    df['cum_V'] = df.groupby('date')['volume'].cumsum()
    
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

def append_all_indicators(df):
    """
    Appends VWAP, EMA_9, and VFI to the DataFrame.
    """
    if df.empty or len(df) < 130:
        return df # Not enough data
        
    df['vwap'] = calculate_vwap(df)
    df['ema_9'] = calculate_ema(df, period=9)
    vfi_df = calculate_vfi(df, period=130)
    df['vfi'] = vfi_df['vfi']
    df['vfi_ema'] = vfi_df['vfi_ema']
    
    # --- VSA Gatekeeper Metrics ---
    # 20-period Volume SMA
    df['vol_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
    # Relative Volume (RVOL)
    df['rvol'] = df['volume'] / df['vol_sma_20']
    
    # Body Dominance Ratio
    df['candle_range'] = df['high'] - df['low']
    df['real_body'] = abs(df['open'] - df['close'])
    
    # Avoid division by zero by replacing 0 range with a tiny number
    df['candle_range'] = df['candle_range'].replace(0, 0.0001)
    df['body_ratio'] = df['real_body'] / df['candle_range']
    
    return df
