import time
from datetime import datetime, time as datetime_time
import json
import os
import pandas as pd

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "feature_registry.json")

def load_feature_registry():
    try:
        with open(REGISTRY_PATH, 'r') as f:
            return json.load(f).get("features", {})
    except Exception:
        return {}

def get_premium_change(history, seconds, current_time, current_premium):
    """
    Finds the premium in history closest to target_time (current_time - seconds)
    and returns the percentage change from that price to current_premium.
    history is a list of (timestamp, premium) sorted by timestamp.
    """
    if not history or len(history) < 2:
        return 0.0
    target_time = current_time - seconds
    
    # find the premium in history closest to target_time
    closest_p = None
    min_diff = float('inf')
    for t, p in history:
        diff = abs(t - target_time)
        if diff < min_diff and t <= current_time:
            min_diff = diff
            closest_p = p
            
    if closest_p is not None and closest_p > 0:
        return ((current_premium - closest_p) / closest_p) * 100
    return 0.0

def extract_features(state_snapshot, signal_data, current_df=None, premium_history=None):
    """
    Converts live market state and option details into an ML-ready feature vector.
    Enforces Data Leakage Prevention by attaching a strict feature_timestamp.
    """
    registry = load_feature_registry()
    feature_timestamp = datetime.now().isoformat()
    current_time = time.time()
    
    # Base feature dictionary
    features = {
        "feature_timestamp": feature_timestamp,
        "signal_type": signal_data.get("signal_category", "UNKNOWN")
    }

    # Extract Market State Features
    market = state_snapshot.get("market_state", {})
    telemetry = state_snapshot.get("telemetry", {})
    order_flow = state_snapshot.get("order_flow", {})
    
    # 1. Base indicators
    features["market_regime"] = market.get("regime", 0)
    features["atr_current"] = market.get("atr", 0.0)
    features["atr_expansion_ratio"] = market.get("atr_expansion", 1.0)
    features["compression_score"] = market.get("compression", 0.0)
    features["vfi_value"] = telemetry.get("vfi", 0.0)
    features["vfi_angle"] = telemetry.get("vfi_angle", 0.0)
    features["ofa_score"] = order_flow.get("score", 0.0)
    features["buyer_aggression"] = order_flow.get("buyer_aggression", 0.0)
    features["seller_aggression"] = order_flow.get("seller_aggression", 0.0)

    # 2. Option specific parameters
    option = signal_data.get("option_data", {})
    current_premium = option.get("premium", 0.0)
    features["premium"] = current_premium
    
    # Expiry and DTE calculations
    dte = option.get("dte", -1)
    if dte == -1 and "expiry" in option:
        try:
            expiry_dt = pd.to_datetime(option["expiry"], format='%d%b%Y')
            dte = (expiry_dt.date() - datetime.now().date()).days
        except Exception:
            dte = 0
    features["dte"] = max(0, dte)
    features["distance_from_atm"] = option.get("distance", 0.0)

    # 3. Premium Velocity (Calculated from premium_history)
    premium_change_10s = 0.0
    premium_change_30s = 0.0
    premium_acceleration = 0.0
    
    if premium_history and len(premium_history) >= 2:
        premium_change_10s = get_premium_change(premium_history, 10, current_time, current_premium)
        premium_change_30s = get_premium_change(premium_history, 30, current_time, current_premium)
        
        # Calculate velocity 10 seconds ago to measure acceleration
        premium_10s_ago = current_premium
        target_time_10s = current_time - 10
        for t, p in premium_history:
            if abs(t - target_time_10s) < 2.0:
                premium_10s_ago = p
                break
        
        prev_velocity = get_premium_change(premium_history, 10, current_time - 10, premium_10s_ago)
        premium_acceleration = premium_change_10s - prev_velocity

    features["premium_change_10s"] = premium_change_10s
    features["premium_change_30s"] = premium_change_30s
    features["premium_acceleration"] = premium_acceleration

    # 4. Market Structure Features (From Index Candles)
    distance_from_day_high = 0.0
    distance_from_day_low = 0.0
    range_position = 50.0
    
    # 5. Candle Behaviour Features
    body_expansion_ratio = 1.0
    wick_rejection_ratio = 0.0
    consecutive_green = 0
    consecutive_red = 0

    if current_df is not None and not current_df.empty:
        try:
            # Market Structure
            latest_idx = current_df.iloc[-1]
            current_idx_price = latest_idx.get("close", 0.0)
            
            # Filter for today's candles to calculate high/low
            # Make sure to handle timestamp formats safely
            latest_ts = pd.to_datetime(latest_idx["timestamp"])
            day_df = current_df[pd.to_datetime(current_df["timestamp"]).dt.date == latest_ts.date()]
            
            if not day_df.empty:
                day_high = day_df["high"].max()
                day_low = day_df["low"].min()
                
                if current_idx_price > 0:
                    distance_from_day_high = ((day_high - current_idx_price) / current_idx_price) * 100
                    distance_from_day_low = ((current_idx_price - day_low) / day_low) * 100
                    if day_high > day_low:
                        range_position = ((current_idx_price - day_low) / (day_high - day_low)) * 100
            
            # Candle Behaviour
            temp_df = current_df.copy()
            temp_df["real_body"] = (temp_df["close"] - temp_df["open"]).abs()
            temp_df["body_sma_20"] = temp_df["real_body"].rolling(20, min_periods=1).mean()
            
            latest_body = temp_df["real_body"].iloc[-1]
            latest_body_sma = temp_df["body_sma_20"].iloc[-1]
            if latest_body_sma > 0:
                body_expansion_ratio = latest_body / latest_body_sma
                
            c_high, c_low, c_open, c_close = latest_idx["high"], latest_idx["low"], latest_idx["open"], latest_idx["close"]
            c_range = c_high - c_low
            if c_range > 0:
                upper_wick = c_high - max(c_open, c_close)
                lower_wick = min(c_open, c_close) - c_low
                wick_rejection_ratio = (upper_wick + lower_wick) / c_range
                
            # Consecutive Green/Red
            for i in range(len(current_df) - 1, -1, -1):
                c_row = current_df.iloc[i]
                if c_row["close"] > c_row["open"]:
                    consecutive_green += 1
                    if consecutive_red > 0: break
                elif c_row["close"] < c_row["open"]:
                    consecutive_red += 1
                    if consecutive_green > 0: break
                else:
                    break
        except Exception as e:
            print(f"[FeatureBuilder] Error calculating structure/candle features: {e}")

    features["distance_from_day_high"] = distance_from_day_high
    features["distance_from_day_low"] = distance_from_day_low
    features["range_position"] = range_position
    features["body_expansion_ratio"] = body_expansion_ratio
    features["wick_rejection_ratio"] = wick_rejection_ratio
    features["consecutive_green_candles"] = consecutive_green
    features["consecutive_red_candles"] = consecutive_red

    # 6. Time and Expiry Features
    now = datetime.now()
    market_open = datetime.combine(now.date(), datetime_time(9, 15))
    minutes_from_open = max(0.0, (now - market_open).total_seconds() / 60.0)
    
    market_session = "MIDDAY"
    if minutes_from_open <= 75:
        market_session = "OPENING"
    elif minutes_from_open >= 300:
        market_session = "CLOSING"
        
    is_expiry_day = 1 if dte == 0 else 0
    theta_pressure_zone = 1 if (is_expiry_day == 1 and now.hour >= 13) else 0

    features["minutes_from_open"] = minutes_from_open
    features["market_session"] = market_session
    features["is_expiry_day"] = is_expiry_day
    features["theta_pressure_zone"] = theta_pressure_zone

    # Attach versioning metadata
    features["meta_versions"] = {
        k: v.get("calculation_version", "v1") for k, v in registry.items()
    }

    return features

if __name__ == "__main__":
    # Test harness
    dummy_state = {
        "market_state": {"regime": 1, "atr": 20.5, "atr_expansion": 1.2},
        "telemetry": {"vfi": 15000, "vfi_angle": 12.5},
        "order_flow": {"score": 8.5, "buyer_aggression": 65.0}
    }
    dummy_signal = {
        "signal_category": "EXECUTED",
        "option_data": {"premium": 45.2, "expiry": "30JUN2026", "distance": 100}
    }
    
    # Create a small dummy dataframe representing candles
    dummy_df = pd.DataFrame([
        {"timestamp": datetime.now(), "open": 22000, "high": 22050, "low": 21980, "close": 22020},
        {"timestamp": datetime.now(), "open": 22020, "high": 22080, "low": 22010, "close": 22070}
    ])
    
    dummy_history = [
        (time.time() - 30, 40.0),
        (time.time() - 10, 42.0),
        (time.time(), 45.2)
    ]
    
    res = extract_features(dummy_state, dummy_signal, current_df=dummy_df, premium_history=dummy_history)
    print("Extracted Features:")
    print(json.dumps(res, indent=2))
