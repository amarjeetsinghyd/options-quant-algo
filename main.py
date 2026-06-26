import time
import threading
from datetime import datetime, timedelta
import os
import json
import uuid
import pandas as pd
from flask import Flask, render_template, jsonify, request
from src.core.angel_connection import get_angel_connection, get_websocket_connection
from src.core.data_fetcher import DataFetcher
from src.strategy.indicators import append_all_indicators
from src.strategy.signal_generator import SignalGenerator
from src.execution.paper_trader import PaperTrader
from src.research.strike_intelligence import StrikeIntelligenceModule
from src.analytics.analytics_engine import AnalyticsEngine
from src.ml_engine.shadow_predictor import ShadowPredictor
from src.ml_engine.feature_builder import extract_features
from src.ml_engine.gamma_event_collector import GammaEventCollector

# Initialize Shadow ML Engine components
try:
    shadow_predictor = ShadowPredictor()
    gamma_collector = GammaEventCollector()
except Exception as e:
    print(f"Failed to initialize ML Engine: {e}")
    shadow_predictor = None
    gamma_collector = None

import webbrowser
import sys
import logging
import traceback

# Global Exception Handler
def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    if not os.path.exists("logs"): os.makedirs("logs")
    with open("logs/crash_report_latest.txt", "w") as f:
        f.write("=== FATAL CRASH ===\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    print(f"FATAL ERROR: {exc_value}. See logs/crash_report_latest.txt")

sys.excepthook = global_exception_handler

app = Flask(__name__, template_folder='src/web/templates', static_folder='src/web/static')

# Load history if exists
history_data = []
if os.path.exists("trade_history.json"):
    try:
        with open("trade_history.json", 'r') as f:
            history_data = json.load(f)
    except: pass

# Global State for Telemetry
current_df = None
state = {
    "status": "stopped", # stopped, initializing, running, error
    "error_msg": "",
    "error_time": "",
    "telemetry": {},
    "active_trade": None,
    "last_signal": None,
    "history": history_data,
    "order_flow": {
        "token": None,
        "buy_vol": 0,
        "sell_vol": 0,
        "delta": 0,
        "last_price": 0
    },
    "errors": [],
    "tracked_options": {},
    "market_state": {}
}

# Analytics Engine Instance
analytics = AnalyticsEngine()

def log_ui_error(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted_err = f"[{timestamp}] {msg}"
    state["errors"].insert(0, formatted_err)
    if len(state["errors"]) > 5:
        state["errors"].pop()
    print(f"ERROR: {msg}")


def _run_research(intelligence, signal, index_price, api, fetcher, ws_subscribe_callback, recent_candles=None):
    """
    [RESEARCH MODULE] Helper called in daemon thread.
    Passes signal to StrikeIntelligenceModule and schedules 180s finalization.
    Completely isolated from execution logic.
    """
    try:
        signal_id, tokens = intelligence.register_signal(
            signal, index_price, api, fetcher, recent_candles,
            signal_category=signal.get('signal_category', 'EXECUTED'),
            rejection_reason=signal.get('rejection_reason'),
            rejection_stage=signal.get('rejection_stage'),
            filter_name=signal.get('filter_name'),
            filter_value=signal.get('filter_value'),
            would_have_entered_price=signal.get('would_have_entered_price')
        )
        if signal_id:
            intelligence.schedule_finalization(signal_id, delay=180.0)
            
            # [ML RESEARCH LAYER] Shadow ML Prediction (Non-blocking)
            if shadow_predictor:
                try:
                    features = extract_features(state, signal)
                    shadow_predictor.predict_all_models_async(signal_id, features)
                except Exception as ml_err:
                    print(f"[ML Shadow] Prediction error: {ml_err}")

            if tokens and ws_subscribe_callback:
                ws_subscribe_callback(tokens)
    except Exception as e:
        print(f"[Research] Error in research thread: {e}")

def refresh_tracked_options(fetcher, index_price, ws_subscribe_callback):
    try:
        index_name, exch_seg = fetcher.get_active_instrument()
        step = 100 if index_name == "SENSEX" else 50
        atm_strike = round(index_price / step) * step
        
        weekly_opts = fetcher.get_weekly_option_tokens()
        if weekly_opts.empty:
            return {}
            
        # Select CE and PE for ATM - 3*step to ATM + 3*step
        target_strikes = [atm_strike + i * step for i in range(-3, 4)]
        tracked = {}
        tokens_to_sub = []
        
        for strike_val in target_strikes:
            strike_scaled = int(strike_val * 100)
            for opt_type in ["CE", "PE"]:
                match = weekly_opts[(weekly_opts['strike'].astype(int) == strike_scaled) & (weekly_opts['symbol'].str.endswith(opt_type))]
                if not match.empty:
                    row = match.iloc[0]
                    token = str(row['token'])
                    symbol = str(row['symbol'])
                    
                    try:
                        expiry_dt = pd.to_datetime(row['expiry'], format='%d%b%Y')
                        dte = (expiry_dt.date() - datetime.now().date()).days
                    except Exception:
                        dte = 0
                        
                    tracked[token] = {
                        "token": token,
                        "symbol": symbol,
                        "strike": float(row['strike']) / 100,
                        "option_type": opt_type,
                        "index_name": index_name,
                        "distance": int(abs(strike_val - atm_strike) / step),
                        "dte": max(0, dte),
                        "expiry": str(row['expiry'])
                    }
                    tokens_to_sub.append(token)
                    
        if tokens_to_sub and ws_subscribe_callback:
            ws_subscribe_callback(tokens_to_sub)
            
        print(f"[OptionTracker] Refreshed option universe around ATM {atm_strike}. Subscribed to {len(tokens_to_sub)} contracts.")
        return tracked
    except Exception as e:
        print(f"[OptionTracker] Error refreshing options: {e}")
        return {}

def algo_loop():
    global current_df
    print("Algorithm background thread initialized.")
    try:
        api, session_data = get_angel_connection()
    except Exception as e:
        state["status"] = "error"
        state["error_msg"] = f"Login Exception: {str(e)}"
        state["error_time"] = datetime.now().strftime("%H:%M:%S")
        return

    if not api:
        print("Failed to connect to API.")
        state["status"] = "error"
        state["error_msg"] = "Failed to connect to Angel One API. Check credentials."
        state["error_time"] = datetime.now().strftime("%H:%M:%S")
        return
        
    fetcher = DataFetcher(api)
    signal_gen = SignalGenerator()
    trader = PaperTrader(api, fetcher, state["history"])
    intelligence = StrikeIntelligenceModule()  # [RESEARCH] Silent background module
    
    name, deriv_seg = fetcher.get_active_instrument()
    
    # Always use Cash Index + Synthetic Volume (both NIFTY and SENSEX days)
    anchor_token, anchor_symbol, anchor_exch = fetcher.get_cash_index_token()
    use_synthetic_volume = True
    
    if not anchor_token:
        print("Could not find anchor token!")
        return

    print(f"Tracking: {anchor_symbol} on {anchor_exch} (Synthetic Volume: {use_synthetic_volume})")
    state["telemetry"]["symbol"] = anchor_symbol
    
    last_historic_fetch = 0
    last_ltp_fetch = 0
    last_volume_fetch_minute = datetime.now().minute
    last_option_refresh = 0
    cached_volume_df = None  # Cache the synthetic volume to avoid repeated constituent API calls
    cached_price_df = None
    current_df = None
    
    # Setup WebSocket for Live Synthetic Volume
    active_tokens = fetcher.get_active_constituents()
    token_list = list(active_tokens.values())
    
    feed_token = session_data.get("feedToken")
    jwt_token = session_data.get("jwtToken")
    client_id = os.getenv("ANGEL_CLIENT_ID")
    api_key = os.getenv("ANGEL_API_KEY")
    
    ws = get_websocket_connection(jwt_token, api_key, client_id, feed_token)
    
    last_known_vtt = {}
    current_minute_volume_tracker = {}
    live_volume_minute = datetime.now().minute
    live_ltp = None
    live_open = None
    live_high = None
    live_low = None
    live_tracking_minute = datetime.now().minute
    
    def subscribe_option(option_token):
        print(f"[WebSocket] Subscribing to active option: {option_token}")
        correlation_id = "option_sub"
        mode = 3 # SNAPQUOTE
        token_payload = [{"exchangeType": 2, "tokens": [option_token]}] # 2 is NFO
        try:
            ws.subscribe(correlation_id, mode, token_payload)
        except Exception as e:
            print(f"WS Subscribe error: {e}")

    def subscribe_research_batch(tokens):
        if not tokens: return
        print(f"[WebSocket] Subscribing to research options: {tokens}")
        correlation_id = "research_sub"
        mode = 3 # SNAPQUOTE
        token_payload = [{"exchangeType": 2, "tokens": tokens}]
        try:
            ws.subscribe(correlation_id, mode, token_payload)
        except Exception as e:
            print(f"WS Subscribe error: {e}")

    def on_data(wsapp, message):
        nonlocal live_volume_minute, cached_volume_df, current_minute_volume_tracker, last_known_vtt, live_ltp
        now = datetime.now()
        state['telemetry']['last_ws_tick'] = time.time()
        
        # [RESEARCH] Route tick to Strike Intelligence module (non-blocking)
        if isinstance(message, dict):
            _tk = str(message.get('token', ''))
            if _tk:
                intelligence.on_tick(_tk, message)
        
        # When minute rolls over, flush the tracked volume to cache
        if now.minute != live_volume_minute:
            total_vol = sum(current_minute_volume_tracker.values())
            print(f"[WebSocket] Minute {live_volume_minute} closed. Total Synthetic Vol: {total_vol}")
            
            # Create a dataframe for this minute
            ts = pd.Timestamp(now.replace(minute=live_volume_minute, second=0, microsecond=0))
            if cached_volume_df is not None and getattr(cached_volume_df.index, 'tz', None) is not None:
                ts = ts.tz_localize(cached_volume_df.index.tz)
                
            new_row = pd.DataFrame({'timestamp': [ts], 'synth_vol': [total_vol]}).set_index('timestamp')
            
            if cached_volume_df is not None:
                cached_volume_df = new_row.combine_first(cached_volume_df)
            else:
                cached_volume_df = new_row
                
            # Update the baseline VTT for the new minute
            for t, vol in current_minute_volume_tracker.items():
                last_known_vtt[t] = last_known_vtt.get(t, 0) + vol
                
            # Reset tracker for the new minute
            current_minute_volume_tracker = {}
            live_volume_minute = now.minute
            
        # Accumulate tick volume and update LTP
        is_market_open = (now.hour == 9 and now.minute >= 15) or (9 < now.hour < 15) or (now.hour == 15 and now.minute <= 30)

        if isinstance(message, dict):
            token = message.get('token')
            # Temporarily cast token to string just in case it comes as an int
            if token is not None:
                token = str(token)
                
            ltq = message.get('last_traded_quantity', 0)
            ltp = message.get('last_traded_price', 0)
            vtt = message.get('volume_trade_for_the_day', 0)
            
            # Only accumulate volume strictly during live market hours
            if token and token in token_list and vtt > 0 and is_market_open:
                if token not in last_known_vtt:
                    last_known_vtt[token] = vtt
                
                minute_vol = vtt - last_known_vtt[token]
                current_minute_volume_tracker[token] = max(0, minute_vol)
                
                # Stream Live Volume to Dashboard
                live_vol = sum(current_minute_volume_tracker.values())
                state["telemetry"]["volume"] = live_vol
                state["telemetry"]["volume_time"] = datetime.now().strftime("%H:%M:%S")
                state["telemetry"]["volume_seconds"] = datetime.now().second
                
            if token == anchor_token and ltp > 0:
                live_ltp = float(ltp / 100) # Angel One sends price in paise
                state["telemetry"]["ltp"] = live_ltp
                state["telemetry"]["ltp_time"] = datetime.now().strftime("%H:%M:%S")
                
            # Route tracked options ticks to GammaEventCollector
            if gamma_collector and token and token in state.get("tracked_options", {}) and ltp > 0:
                opt_price = float(ltp / 100)
                opt_details = state["tracked_options"][token]
                best_bid = 0.0
                best_ask = 0.0
                if 'best_5_buy_data' in message and len(message['best_5_buy_data']) > 0:
                    best_bid = float(message['best_5_buy_data'][0].get('price', 0)) / 100
                if 'best_5_sell_data' in message and len(message['best_5_sell_data']) > 0:
                    best_ask = float(message['best_5_sell_data'][0].get('price', 0)) / 100
                spread = round(best_ask - best_bid, 2) if best_ask > best_bid else 0.0
                opt_details["spread"] = spread
                
                gamma_collector.feed_tick(
                    symbol=opt_details["symbol"],
                    price=opt_price,
                    index_price=live_ltp if live_ltp else 0.0,
                    market_state=state.get("market_state", {}),
                    option_details=opt_details,
                    exchange_timestamp=message.get("exchange_timestamp") or message.get("exch_time")
                )
                
            if state.get("subscribed_option") == token and ltp > 0:
                live_opt_ltp = float(ltp / 100)
                
                if trader.current_trade and token == trader.current_trade['token']:
                    state["active_trade"]["current_ltp"] = live_opt_ltp
                
                # Order Flow / Delta Calculation Logic
                if state["order_flow"]["token"] != token:
                    # Reset tracker for new token
                    state["order_flow"] = {
                        "token": token, "buy_vol": 0, "sell_vol": 0, "delta": 0, "last_price": live_opt_ltp
                    }
                elif ltq > 0 and is_market_open:
                    prev_price = state["order_flow"]["last_price"]
                    best_ask = 0
                    best_bid = 0
                    
                    # Try to use Market Depth (Bid/Ask) if available in SNAPQUOTE
                    ask_data = message.get('best_5_sell_data', [])
                    bid_data = message.get('best_5_buy_data', [])
                    if ask_data and isinstance(ask_data, list):
                        best_ask = ask_data[0].get('price', 0) / 100
                    if bid_data and isinstance(bid_data, list):
                        best_bid = bid_data[0].get('price', 0) / 100
                        
                    # Determine classification (Aggressive Buy vs Sell)
                    is_buy = False
                    if best_ask > 0 and live_opt_ltp >= best_ask:
                        is_buy = True
                    elif best_bid > 0 and live_opt_ltp <= best_bid:
                        is_buy = False
                    else:
                        # Fallback: Tick Test
                        if live_opt_ltp > prev_price:
                            is_buy = True
                        elif live_opt_ltp < prev_price:
                            is_buy = False
                        else:
                            # If price unchanged, we can default to buy or ignore. We'll ignore neutrality or keep previous (default buy here for simplicity if it ticked up)
                            is_buy = state["order_flow"].get("last_was_buy", True)

                    if is_buy:
                        state["order_flow"]["buy_vol"] += ltq
                        state["order_flow"]["delta"] += ltq
                    else:
                        state["order_flow"]["sell_vol"] += ltq
                        state["order_flow"]["delta"] -= ltq
                        
                    state["order_flow"]["last_price"] = live_opt_ltp
                    state["order_flow"]["last_was_buy"] = is_buy

    def on_open(wsapp):
        print("[WebSocket] Connected. Subscribing to 50 Nifty constituents and anchor...")
        if state["status"] == "initializing":
            state["status"] = "running"
            state["error_msg"] = ""
            state["error_time"] = ""
        correlation_id = f"sub_{int(time.time())}"
        action = 1
        mode = 3 # SNAPQUOTE
        
        try:
            full_list = token_list + [anchor_token]
            ws_exch_type = 1 if anchor_exch == "NSE" else 3
            ws.subscribe(correlation_id, mode, [{"exchangeType": ws_exch_type, "tokens": full_list}])
                
        except Exception as e:
            log_ui_error(f"WS Subscribe error: {e}")

    reconnect_attempts = 0

    def on_error(wsapp, error):
        log_ui_error(f"WebSocket Error: {error}")
        if state["status"] == "running":
            state["status"] = "initializing"
            state["error_msg"] = f"Connection dropped. Reconnecting..."

    def on_close(wsapp):
        log_ui_error("WebSocket Connection Closed")
        if state["status"] == "running":
            state["status"] = "initializing"
            state["error_msg"] = "Connection dropped. Reconnecting..."
            state["error_time"] = datetime.now().strftime("%H:%M:%S")

    ws.on_open = on_open
    ws.on_data = on_data
    ws.on_error = on_error
    ws.on_close = on_close
    
    def ws_runner():
        nonlocal reconnect_attempts
        while True:
            if state["status"] == "stopped":
                time.sleep(1)
                continue
                
            try:
                print(f"[WebSocket] Starting connection (Attempt {reconnect_attempts})...")
                ws.connect()
                # If we get here and it returns immediately, or after a long time:
                reconnect_attempts = 0
            except Exception as e:
                print(f"[WebSocket] Connection threw error: {e}")
                
            if state["status"] != "stopped":
                reconnect_attempts += 1
                if reconnect_attempts > 10:
                    state["status"] = "error"
                    state["error_msg"] = "Max WS reconnect attempts reached."
                    state["error_time"] = datetime.now().strftime("%H:%M:%S")
                    print("[WebSocket] Max reconnect attempts reached. Halting.")
                    while state["status"] == "error":
                        time.sleep(1)
                    reconnect_attempts = 0
                else:
                    print(f"[WebSocket] Connection died. Reconnecting in 3 seconds (Attempt {reconnect_attempts}/10)...")
                    time.sleep(3)
            
    ws_thread = threading.Thread(target=ws_runner, daemon=True)

    # Fallback Checker Thread
    def fallback_checker():
        while True:
            time.sleep(120) # Check every 2 minutes
            if state["status"] == "stopped":
                continue
            
            try:
                # Fetch the last 6 minutes to cover the 5-minute interval plus buffer
                vol_df = fetcher._fetch_constituent_volume(minutes_back=6)
                if vol_df is not None and not vol_df.empty:
                    # Current minute is incomplete, so we exclude it
                    current_minute_ts = datetime.now().replace(second=0, microsecond=0)
                    
                    for _, row in vol_df.iterrows():
                        ts = row['timestamp']
                        if ts >= current_minute_ts:
                            continue # Skip the currently running minute
                            
                        server_vol = row['synthetic_volume']
                        
                        if cached_volume_df is not None and ts in cached_volume_df.index:
                            local_vol = cached_volume_df.loc[ts, 'synth_vol']
                            if server_vol != local_vol:
                                print(f"[Fallback System] Discrepancy found for {ts.strftime('%H:%M')}! Local: {local_vol}, Server: {server_vol}. Correcting cache.")
                                cached_volume_df.loc[ts, 'synth_vol'] = server_vol
            except Exception as e:
                print(f"[Fallback System] Error: {e}")

    fallback_thread = threading.Thread(target=fallback_checker, daemon=True)

    print("=== INITIALIZING WEBSOCKET ENGINE ===")
    ws_thread.start()
    fallback_thread.start()

    # --- BOOT SEQUENCE: Fetch full historical data with synthetic volume ---
    if use_synthetic_volume:
        print("=== BOOT: Building Synthetic Volume Engine (this takes ~35 seconds) ===")
        try:
            boot_df = fetcher.get_historical_candles_with_synthetic_volume(days_back=5)
            if not boot_df.empty:
                # Cache the volume data indexed by timestamp
                cached_volume_df = boot_df.set_index('timestamp')[['volume']].rename(columns={'volume': 'synth_vol'})
                cached_price_df = boot_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                current_df = append_all_indicators(boot_df)
                if current_df is not None and not current_df.empty:
                    latest = current_df.iloc[-1]
                    state["telemetry"]["vwap"] = float(latest.get('vwap', 0))
                    state["telemetry"]["ema"] = float(latest.get('ema_9', 0))
                    state["telemetry"]["vfi"] = float(latest.get('vfi', 0))
                    state["telemetry"]["vfi_ema"] = float(latest.get('vfi_ema', 0))
                    state["telemetry"]["timestamp"] = latest.get('timestamp').strftime('%H:%M:%S') if pd.notnull(latest.get('timestamp')) else "--:--:--"
                last_volume_fetch_minute = datetime.now().minute  # Reset timer to boot completion time
                print("=== BOOT COMPLETE: Synthetic Volume Engine Online ===")
        except Exception as e:
            log_ui_error(f"Boot Sequence Error: {e}")
            print(f"BOOT ERROR: {e}")
            state["status"] = "error"
            state["error_msg"] = f"Boot Sequence Failed: {e}"
            state["error_time"] = datetime.now().strftime("%H:%M:%S")
            return
            
    # Transition to active PAPER MODE
    if state["status"] != "error" and state["status"] != "stopped":
        state["status"] = "running"
    
    while True:
        if state["status"] == "stopped" or state["status"] == "error":
            print(f"Engine terminating (Status: {state['status']}). Cleaning up connections...")
            try:
                ws.close()
            except:
                pass
            break
            
        now = datetime.now()
        is_market_open = (now.hour == 9 and now.minute >= 15) or (9 < now.hour < 15) or (now.hour == 15 and now.minute <= 30)
        
        if is_market_open:
            now_ts = time.time()
            
            # Reset live candle tracker on minute rollover
            if now.minute != live_tracking_minute:
                live_open = None
                live_high = None
                live_low = None
                live_tracking_minute = now.minute
                
            # 1. Live LTP polling (every 2 seconds)
            if now_ts - last_ltp_fetch >= 2:
                try:
                    res = fetcher.obj.ltpData(anchor_exch, anchor_symbol, anchor_token)
                    if res and res.get('status') and res.get('data'):
                        live_ltp = float(res['data']['ltp'])
                        state["telemetry"]["ltp"] = live_ltp
                        state["telemetry"]["ltp_time"] = datetime.now().strftime("%H:%M:%S")
                        
                        if live_open is None: live_open = live_ltp
                        if live_high is None or live_ltp > live_high: live_high = live_ltp
                        if live_low is None or live_ltp < live_low: live_low = live_ltp
                except Exception as e:
                    pass
                last_ltp_fetch = now_ts
                
            # 2. Refresh historical price data every 10 seconds
            if now_ts - last_historic_fetch >= 10:
                try:
                    if use_synthetic_volume:
                        if cached_price_df is None:
                            new_price_df = fetcher.get_historical_candles(anchor_exch, anchor_token, "ONE_MINUTE", days_back=5)
                        else:
                            new_price_df = fetcher.get_historical_candles(anchor_exch, anchor_token, "ONE_MINUTE", minutes_back=15)
                        
                        if not new_price_df.empty and cached_volume_df is not None:
                            new_price_df = new_price_df.set_index('timestamp')[['open', 'high', 'low', 'close']]
                            if cached_price_df is not None:
                                cached_price_df = new_price_df.combine_first(cached_price_df)
                            else:
                                cached_price_df = new_price_df
                            
                            price_df = cached_price_df.copy()
                            price_df = price_df.join(cached_volume_df, how='left')
                            price_df['volume'] = price_df['synth_vol'].fillna(0).astype(int)
                            price_df = price_df.drop(columns=['synth_vol']).reset_index()
                            
                            # --- INJECT LIVE VIRTUAL CANDLE ---
                            if live_ltp is not None:
                                live_ts = pd.Timestamp(datetime.now().replace(second=0, microsecond=0))
                                if not price_df.empty and getattr(price_df['timestamp'].dtype, 'tz', None) is not None:
                                    live_ts = live_ts.tz_localize(price_df['timestamp'].dtype.tz)
                                    
                                live_vol = sum(current_minute_volume_tracker.values())
                                
                                if not (price_df['timestamp'] == live_ts).any():
                                    live_row = pd.DataFrame({
                                        'timestamp': [live_ts],
                                        'open': [live_open if live_open else live_ltp],
                                        'high': [live_high if live_high else live_ltp],
                                        'low': [live_low if live_low else live_ltp],
                                        'close': [live_ltp],
                                        'volume': [live_vol]
                                    })
                                    price_df = pd.concat([price_df, live_row], ignore_index=True)
                                else:
                                    idx = price_df[price_df['timestamp'] == live_ts].index[-1]
                                    price_df.at[idx, 'close'] = live_ltp
                                    price_df.at[idx, 'volume'] = max(price_df.at[idx, 'volume'], live_vol)
                                    if live_high: price_df.at[idx, 'high'] = max(price_df.at[idx, 'high'], live_high)
                                    if live_low: price_df.at[idx, 'low'] = min(price_df.at[idx, 'low'], live_low)
                            
                            current_df = append_all_indicators(price_df)
                    else:
                        # SENSEX days: use Futures directly
                        if cached_price_df is None:
                            new_df = fetcher.get_historical_candles(anchor_exch, anchor_token, "ONE_MINUTE", days_back=5)
                            if not new_df.empty:
                                cached_price_df = new_df.set_index('timestamp')[['open', 'high', 'low', 'close', 'volume']]
                                current_df = append_all_indicators(new_df)
                        else:
                            new_df = fetcher.get_historical_candles(anchor_exch, anchor_token, "ONE_MINUTE", minutes_back=15)
                            if not new_df.empty:
                                new_df = new_df.set_index('timestamp')[['open', 'high', 'low', 'close', 'volume']]
                                cached_price_df = new_df.combine_first(cached_price_df)
                                current_df = append_all_indicators(cached_price_df.copy().reset_index())
                    
                    if current_df is not None and not current_df.empty:
                        latest = current_df.iloc[-1]
                        state["telemetry"]["vwap"] = float(latest.get('vwap', 0))
                        state["telemetry"]["ema"] = float(latest.get('ema_9', 0))
                        state["telemetry"]["vfi"] = float(latest.get('vfi', 0))
                        state["telemetry"]["vfi_ema"] = float(latest.get('vfi_ema', 0))
                        state["telemetry"]["timestamp"] = latest.get('timestamp').strftime('%H:%M:%S') if pd.notnull(latest.get('timestamp')) else "--:--:--"
                        
                        # Update market state
                        state["market_state"] = {
                            "regime": int(latest.get("market_regime", 0)),
                            "atr": float(latest.get("atr", 0.0)),
                            "atr_expansion": float(latest.get("atr_expansion", 1.0)),
                            "compression": float(latest.get("compression", 0.0))
                        }
                        
                        # [RESEARCH] Update market state
                        intelligence.update_market_state(current_df)
                        
                        # Refresh tracked option universe every 60 seconds
                        if live_ltp is not None and (now_ts - last_option_refresh >= 60):
                            state["tracked_options"] = refresh_tracked_options(fetcher, live_ltp, subscribe_research_batch)
                            last_option_refresh = now_ts
                            
                except Exception as e:
                    log_ui_error(f"Historical API Error (Rate Limit/Timeout): {e}")
                last_historic_fetch = now_ts
            
            # 3. Volume is now handled purely asynchronously via WebSocket ticks.
            
            # 4. Execution Engine
            if current_df is not None and live_ltp is not None:
                was_pending = trader.pending_setup is not None
                pending_signal = trader.pending_setup.copy() if was_pending else None
                was_trade = trader.current_trade is not None

                if trader.current_trade is None and trader.pending_setup is None:
                    # Intraday constraint: Only take new trades before 15:15 (3:15 PM)
                    if now.hour < 15 or (now.hour == 15 and now.minute < 15):
                        # Scan for Master Setup (Breakout First)
                        signal = signal_gen.check_signal(current_df)
                        
                        # If no Breakout, scan for Rejection / Support
                        if not signal:
                            signal = signal_gen.check_rejection_signal(current_df)
                            
                        if signal:
                            signal["signal_id"] = str(uuid.uuid4())
                            trader.register_setup(signal)
                        
                elif trader.pending_setup is not None:
                    # SNIPER MODE: Hunting for Breakout Tick
                    trader.sniper_hunt(live_ltp, current_df, state["order_flow"])
                    
                elif trader.current_trade is not None:
                    # Manage Open Trade Limits
                    trader.manage_open_trade(live_ltp, current_df)
                    
                # Check Execution/Rejection State Transitions
                is_pending = trader.pending_setup is not None
                is_trade = trader.current_trade is not None
                
                if was_pending:
                    recent_candles = current_df.tail(500).to_dict('records') if current_df is not None and not current_df.empty else None
                    if not is_pending and is_trade:
                        # Setup EXECUTED
                        pending_signal['signal_category'] = 'EXECUTED'
                        research_thread = threading.Thread(
                            target=_run_research,
                            args=(intelligence, pending_signal, live_ltp, api, fetcher, subscribe_research_batch, recent_candles),
                            daemon=True
                        )
                        research_thread.start()
                    elif not is_pending and not is_trade:
                        # Setup REJECTED
                        pending_signal['signal_category'] = 'REJECTED'
                        now_dt = datetime.now()
                        if now_dt > pending_signal.get("expiry_time", now_dt):
                            pending_signal['rejection_reason'] = "3 minutes passed without breakout"
                            pending_signal['rejection_stage'] = "SETUP_EXPIRED"
                            pending_signal['filter_name'] = "TIME_EXPIRY"
                            pending_signal['filter_value'] = 180.0
                        else:
                            pending_signal['rejection_reason'] = "Negative or flat delta on breakout"
                            pending_signal['rejection_stage'] = "ENTRY_REJECTION"
                            pending_signal['filter_name'] = "OFA_DELTA"
                            pending_signal['filter_value'] = float(state["order_flow"].get("delta", 0))
                            
                        pending_signal['would_have_entered_price'] = live_ltp
                        
                        research_thread = threading.Thread(
                            target=_run_research,
                            args=(intelligence, pending_signal, live_ltp, api, fetcher, subscribe_research_batch, recent_candles),
                            daemon=True
                        )
                        research_thread.start()
                    
            # 4. Sync UI State & WebSocket Subscription
            opt_token = None
            if trader.current_trade:
                opt_token = trader.current_trade['token']
                state["active_trade"] = trader.current_trade
            elif trader.pending_setup:
                opt_token = trader.pending_setup.get('candidate_token')
                state["active_trade"] = None
            else:
                state["active_trade"] = None
                
            if opt_token and state.get("subscribed_option") != opt_token:
                subscribe_option(opt_token)
                state["subscribed_option"] = opt_token
                
        # Fast 2-Second Sniper Polling Loop
        time.sleep(2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify(state)

@app.route('/api/chart_data')
def chart_data():
    try:
        global current_df
        if current_df is None or current_df.empty:
            return jsonify([])
        
        df = current_df.copy()
        if 'timestamp' not in df.columns and df.index.name == 'timestamp':
            df = df.reset_index()
            
        # Convert to int64 safely using standard python timestamp to avoid pandas resolution issues
        df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
        df['time'] = df['timestamp_dt'].apply(lambda x: int(x.timestamp()))
        
        # Defensive check against duplicate times which crash LightweightCharts
        df = df.drop_duplicates(subset=['time'], keep='last')
        
        if 'volume' in df.columns:
            df['value'] = df['volume']
        elif 'synth_vol' in df.columns:
            df['value'] = df['synth_vol']
        else:
            df['value'] = 0
            
        df = df.fillna(0)
        
        cols = ['time', 'open', 'high', 'low', 'close', 'value']
        if 'vwap' in df.columns: cols.append('vwap')
        if 'ema_9' in df.columns: cols.append('ema_9')
        if 'vfi' in df.columns: cols.append('vfi')
        if 'vfi_ema' in df.columns: cols.append('vfi_ema')
        
        cols = [c for c in cols if c in df.columns]
        
        json_data = df[cols].to_json(orient='records')
        return app.response_class(json_data, mimetype='application/json')
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()})

# =======================================================
# INTELLIGENCE LAB ROUTES
# =======================================================
@app.route('/intelligence_lab')
def intelligence_lab():
    return render_template('intelligence_lab.html')

@app.route('/api/intelligence/<panel>')
def api_intelligence(panel):
    try:
        if panel == 'overview': return jsonify(analytics.get_overview())
        elif panel == 'strategy': return jsonify(analytics.get_strategy_intelligence())
        elif panel == 'strike': return jsonify(analytics.get_strike_intelligence())
        elif panel == 'premium': return jsonify(analytics.get_premium_intelligence())
        elif panel == 'time': return jsonify(analytics.get_time_intelligence())
        elif panel == 'filters': return jsonify(analytics.get_filter_intelligence())
        elif panel == 'orderflow': return jsonify(analytics.get_order_flow_intelligence())
        elif panel == 'execution': return jsonify(analytics.get_execution_intelligence())
        elif panel == 'scaling': return jsonify(analytics.get_scaling_intelligence())
        elif panel == 'market': return jsonify(analytics.get_market_intelligence())
        elif panel == 'summary': return jsonify(analytics.get_machine_insights())
        elif panel == 'ofa_health': return jsonify(analytics.get_ofa_health())
        elif panel == 'target_opt': return jsonify(analytics.get_target_optimization())
        elif panel == 'failure_dna': return jsonify(analytics.get_failure_dna())
        elif panel == 'vfi_edge': return jsonify(analytics.get_vfi_edge())
        elif panel == 'confidence': return jsonify(analytics.get_research_confidence())
        elif panel == 'freshness': return jsonify(analytics.get_database_freshness())
        elif panel == 'market_regime': return jsonify(analytics.get_market_regime_intelligence())
        elif panel == 'atr_intel': return jsonify(analytics.get_atr_intelligence())
        elif panel == 'vwap_health': return jsonify(analytics.get_vwap_health())
        elif panel == 'vfi_intel': return jsonify(analytics.get_vfi_intelligence_phase43())
        elif panel == 'trade_quality': return jsonify(analytics.get_trade_quality_distribution())
        elif panel == 'ml_brain': return jsonify(analytics.get_ml_intelligence())
        return jsonify({"error": "Unknown panel"})
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()})

@app.route('/api/dashboard_status')
def dashboard_status():
    return jsonify({
        "status": state["status"],
        "error_msg": state["error_msg"],
        "error_time": state["error_time"]
    })

@app.route('/api/system_health')
def system_health():
    now = time.time()
    last_tick = state['telemetry'].get('last_ws_tick')
    tick_age = int(now - last_tick) if last_tick else None
    
    ws_health = "DISCONNECTED"
    if tick_age is not None and tick_age < 30 and state['status'] == 'running':
        ws_health = "CONNECTED"
    
    return jsonify({
        "api_status": "CONNECTED" if state["status"] == "running" else "DISCONNECTED",
        "ws_health": ws_health,
        "last_tick_age": f"{tick_age}s ago" if tick_age is not None else "No ticks received"
    })

algo_thread_instance = None

@app.route('/api/control')
def control():
    global algo_thread_instance
    action = request.args.get('action')
    if action == 'start':
        state['status'] = 'initializing'
        state['error_msg'] = ''
        if algo_thread_instance is None or not algo_thread_instance.is_alive():
            algo_thread_instance = threading.Thread(target=algo_loop, daemon=True)
            algo_thread_instance.start()
    elif action == 'stop':
        state['status'] = 'stopped'
        state['telemetry'] = {}
    return jsonify({"success": True})

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    env_file = '.env'
    if request.method == 'GET':
        settings = {"ANGEL_API_KEY": "", "ANGEL_CLIENT_ID": "", "ANGEL_PASSWORD": "", "ANGEL_TOTP_SECRET": ""}
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                for line in f:
                    if '=' in line:
                        k, v = line.strip().split('=', 1)
                        if k in settings:
                            settings[k] = v
        return jsonify(settings)
    
    if request.method == 'POST':
        data = request.json
        lines = []
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                lines = f.readlines()
        
        # Update or append
        new_lines = []
        updated_keys = set()
        for line in lines:
            if '=' in line:
                k, v = line.strip().split('=', 1)
                if k in data:
                    new_lines.append(f"{k}={data[k]}\n")
                    updated_keys.add(k)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        for k, v in data.items():
            if k not in updated_keys:
                new_lines.append(f"{k}={v}\n")
                
        with open(env_file, 'w') as f:
            f.writelines(new_lines)
            
        return jsonify({"success": True})

def start_server():
    # Bind to 0.0.0.0 to allow external connections when deployed on a VPS
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    try:
        print("Starting Quant Terminal Server... (Execution Engine paused. Waiting for Start signal)")
        start_server()
    except KeyboardInterrupt:
        print("\nShutting down system safely...")
        sys.exit(0)
