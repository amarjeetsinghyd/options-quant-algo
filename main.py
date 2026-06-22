import time
import threading
from datetime import datetime, timedelta
import os
import json
import pandas as pd
from flask import Flask, render_template, jsonify, request
from src.core.angel_connection import get_angel_connection, get_websocket_connection
from src.core.data_fetcher import DataFetcher
from src.strategy.indicators import append_all_indicators
from src.strategy.signal_generator import SignalGenerator
from src.execution.paper_trader import PaperTrader
import webbrowser
import sys

app = Flask(__name__, template_folder='src/web/templates', static_folder='src/web/static')

# Global State for Telemetry
state = {
    "status": "stopped",
    "telemetry": {},
    "active_trade": None,
    "history": []
}

def algo_loop():
    print("Algorithm background thread initialized.")
    api, session_data = get_angel_connection()
    if not api:
        print("Failed to connect to API.")
        return
        
    fetcher = DataFetcher(api)
    signal_gen = SignalGenerator()
    trader = PaperTrader(api, fetcher, state["history"])
    
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
    last_volume_fetch_minute = datetime.now().minute
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
    
    current_minute_volume_tracker = {}
    live_volume_minute = datetime.now().minute
    live_ltp = None
    
    def subscribe_option(option_token):
        print(f"[WebSocket] Subscribing to active option: {option_token}")
        correlation_id = "option_sub"
        mode = 3 # SNAPQUOTE
        token_payload = [{"exchangeType": 2, "tokens": [option_token]}] # 2 is NFO
        try:
            ws.subscribe(correlation_id, mode, token_payload)
        except Exception as e:
            print(f"WS Subscribe error: {e}")

    def on_data(wsapp, message):
        nonlocal live_volume_minute, cached_volume_df, current_minute_volume_tracker, live_ltp
        now = datetime.now()
        
        # When minute rolls over, flush the tracked volume to cache
        if now.minute != live_volume_minute:
            total_vol = sum(current_minute_volume_tracker.values())
            print(f"[WebSocket] Minute {live_volume_minute} closed. Total Synthetic Vol: {total_vol}")
            
            # Create a dataframe for this minute
            ts = now.replace(minute=live_volume_minute, second=0, microsecond=0)
            new_row = pd.DataFrame({'timestamp': [ts], 'synth_vol': [total_vol]}).set_index('timestamp')
            
            if cached_volume_df is not None:
                cached_volume_df = new_row.combine_first(cached_volume_df)
            else:
                cached_volume_df = new_row
                
            # Reset tracker for the new minute
            current_minute_volume_tracker = {}
            live_volume_minute = now.minute
            
        # Accumulate tick volume and update LTP
        if isinstance(message, dict):
            token = message.get('token')
            ltq = message.get('last_traded_quantity', 0)
            ltp = message.get('last_traded_price', 0)
            
            if token and ltq > 0:
                current_minute_volume_tracker[token] = current_minute_volume_tracker.get(token, 0) + ltq
                
                # Stream Live Volume to Dashboard
                live_vol = sum(current_minute_volume_tracker.values())
                state["telemetry"]["volume"] = live_vol
                state["telemetry"]["volume_time"] = datetime.now().strftime("%H:%M:%S")
                state["telemetry"]["volume_seconds"] = datetime.now().second
                
            if token == anchor_token and ltp > 0:
                live_ltp = float(ltp / 100) # Angel One sends price in paise
                state["telemetry"]["ltp"] = live_ltp
                state["telemetry"]["ltp_time"] = datetime.now().strftime("%H:%M:%S")
                
            if trader.current_trade and token == trader.current_trade['token'] and ltp > 0:
                state["active_trade"]["current_ltp"] = float(ltp / 100)

    def on_open(wsapp):
        print("[WebSocket] Connected. Subscribing to 50 Nifty constituents and anchor...")
        correlation_id = "nifty50_sub"
        action = 1
        mode = 3 # SNAPQUOTE
        sub_tokens = token_list + [anchor_token]
        token_payload = [{"exchangeType": 1, "tokens": sub_tokens}]
        ws.subscribe(correlation_id, mode, token_payload)

    def on_error(wsapp, error):
        print(f"[WebSocket] Error: {error}")

    def on_close(wsapp):
        print("[WebSocket] Closed.")

    ws.on_open = on_open
    ws.on_data = on_data
    ws.on_error = on_error
    ws.on_close = on_close
    
    ws_thread = threading.Thread(target=ws.connect, daemon=True)

    # Fallback Checker Thread
    def fallback_checker():
        while True:
            time.sleep(300) # Check every 5 minutes
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
            print(f"BOOT ERROR: {e}")
    
    while True:
        if state["status"] == "stopped":
            time.sleep(2)
            continue
            
        now = datetime.now()
        is_market_open = (now.hour == 9 and now.minute >= 15) or (9 < now.hour < 15) or (now.hour == 15 and now.minute <= 30)
        
        if is_market_open:
            now_ts = time.time()
            
            # 1. Live LTP is now updated asynchronously via WebSocket
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
                except Exception as e:
                    print(f"Historical API Error (Rate Limit/Timeout): {e}")
                last_historic_fetch = now_ts
            
            # 3. Volume is now handled purely asynchronously via WebSocket ticks.
            
            # 4. Execution Engine
            if current_df is not None and live_ltp is not None:
                if trader.current_trade is None and trader.pending_setup is None:
                    # Scan for Master Setup
                    signal = signal_gen.check_signal(current_df)
                    if signal:
                        trader.register_setup(signal)
                        
                elif trader.pending_setup is not None:
                    # SNIPER MODE: Hunting for Breakout Tick
                    trader.sniper_hunt(live_ltp, current_df)
                    
                elif trader.current_trade is not None:
                    # Manage Open Trade Limits
                    trader.manage_open_trade(live_ltp, current_df)
                    
            # 4. Sync UI State
            if trader.current_trade:
                # Dynamically subscribe to the option if not already subscribed
                if state.get("subscribed_option") != trader.current_trade['token']:
                    subscribe_option(trader.current_trade['token'])
                    state["subscribed_option"] = trader.current_trade['token']
                
                state["active_trade"] = trader.current_trade
                # Option LTP is seamlessly handled by the WebSocket `on_data` event
            else:
                state["active_trade"] = None
                state["subscribed_option"] = None
                
        # Fast 2-Second Sniper Polling Loop
        time.sleep(2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify(state)

@app.route('/api/control')
def control():
    action = request.args.get('action')
    if action == 'start':
        state['status'] = 'running'
    elif action == 'stop':
        state['status'] = 'stopped'
        state['telemetry'] = {}
    return jsonify({"success": True})

def start_server():
    app.run(port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    try:
        algo_thread = threading.Thread(target=algo_loop, daemon=True)
        algo_thread.start()
        start_server()
    except KeyboardInterrupt:
        print("\nShutting down system safely...")
        sys.exit(0)
