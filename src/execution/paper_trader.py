import time
import os
import csv
import json
from datetime import datetime, timedelta
import pandas as pd
from src.utils.charting import generate_trade_chart

class PaperTrader:
    def __init__(self, api, data_fetcher, history_list=None):
        self.api = api
        self.data_fetcher = data_fetcher
        self.trades_today = 0
        self.current_trade = None
        self.pending_setup = None
        self.cooldown_until = None
        self.last_trade_date = None
        self.history_list = history_list if history_list is not None else []
        self.csv_file = "trade_history.csv"
        self.depth_file = "slippage_data.json"
        
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["#", "Date", "Entry", "Exit", "Dur (min)", "Index", "Type", "Strike", "Expiry", "DTE", 
                                 "Entry ₹", "Exit ₹", "Opt Δ₹", "Opt %", "Index Entry", "Index Exit", "Nifty Pts", 
                                 "Delta", "Gamma", "Theta", "Vega", "ATM", "OTM Strikes", "Net P&L ₹", "Result", "Chart", "Description"])

    def reset_daily(self):
        today = datetime.now().date()
        if self.last_trade_date != today:
            self.trades_today = 0
            self.last_trade_date = today
            self.cooldown_until = None

    def get_instrument_params(self):
        name, exch_seg = self.data_fetcher.get_active_instrument()
        if name == "SENSEX":
            return {"premium_min": 60, "premium_max": 70, "lot_size": 20, "index_name": "SENSEX"}
        else:
            return {"premium_min": 22, "premium_max": 27, "lot_size": 25, "index_name": "NIFTY"}

    def register_setup(self, signal):
        self.reset_daily()
        now = datetime.now()
        
        # Guardrail 1: Time Filter
        if now.hour < 10:
            return
            
        # Guardrail 2: Max Trades
        if self.trades_today >= 3:
            return
            
        # Guardrail 3: Cooldown
        if self.cooldown_until and now < self.cooldown_until:
            return
            
        self.pending_setup = signal
        # Use current system time for the 3-minute expiration, NOT the dataframe timestamp
        self.pending_setup["expiry_time"] = now + timedelta(minutes=3)
        print(f"[{now.time()}] MASTER SETUP LOCKED: {signal['type']} | High: {signal['master_high']} | Low: {signal['master_low']}")
        print("Entering 3-Minute SNIPER MODE...")

    def sniper_hunt(self, live_ltp, current_nifty_df):
        if not self.pending_setup:
            return
            
        now = datetime.now()
        setup = self.pending_setup
        
        # Check 3-Minute Expiration
        if now > setup["expiry_time"]:
            print(f"[{now.time()}] SETUP ABORTED: 3 minutes passed without breakout.")
            self.pending_setup = None
            return
            
        # Tick-Level Execution Logic
        triggered = False
        if setup["type"] == "CALL" and live_ltp > (setup["master_high"] + 0.05):
            triggered = True
        elif setup["type"] == "PUT" and live_ltp < (setup["master_low"] - 0.05):
            triggered = True
            
        if triggered:
            print(f"!!! SNIPER TRIGGERED !!! Live price {live_ltp} broke Master Setup.")
            self._execute_trade(setup, current_nifty_df)

    def select_option(self, signal_type):
        weekly_opts = self.data_fetcher.get_weekly_option_tokens()
        opt_type = "CE" if signal_type == "CALL" else "PE"
        opts = weekly_opts[weekly_opts['symbol'].str.endswith(opt_type)]
        
        tokens = opts['token'].tolist()
        selected_opt = None
        entry_price = 0
        params = self.get_instrument_params()
        
        chunk_size = 50
        valid_candidates = []
        for i in range(0, len(tokens), chunk_size):
            chunk = tokens[i:i+chunk_size]
            try:
                name, exch_seg = self.data_fetcher.get_active_instrument()
                market_response = self.api.marketData("LTP", {exch_seg: chunk})
                if market_response and market_response.get('status') and market_response.get('data'):
                    fetched = market_response['data'].get('fetched', [])
                    for item in fetched:
                        ltp = item['ltp']
                        if params["premium_min"] <= ltp <= params["premium_max"]:
                            valid_candidates.append({
                                'token': item['symbolToken'],
                                'ltp': ltp
                            })
            except Exception as e:
                pass
                
        # If we found valid candidates, pick the one closest to the max premium
        if valid_candidates:
            # Sort descending by ltp, so the first one is the highest (closest to max)
            valid_candidates.sort(key=lambda x: x['ltp'], reverse=True)
            best = valid_candidates[0]
            selected_opt = opts[opts['token'] == best['token']].iloc[0]
            entry_price = best['ltp']
            
        return selected_opt, entry_price

    def _execute_trade(self, setup, current_nifty_df):
        params = self.get_instrument_params()
        opt_row, entry_price = self.select_option(setup["type"])
        
        if opt_row is None:
            print("Sniper Aborted: Could not find option in premium bounds.")
            self.pending_setup = None
            return
            
        token = opt_row['token']
        symbol = opt_row['symbol']
        expiry = opt_row['expiry']
        strike = float(opt_row['strike']) / 100 
        
        name, exch_seg = self.data_fetcher.get_active_instrument()
        
        # 1. Market Depth
        depth_data = {}
        try:
            depth_res = self.api.marketData("FULL", {exch_seg: [token]})
            if depth_res and depth_res.get('status'):
                depth_data = depth_res['data']['fetched'][0].get('depth', {})
        except: pass
            
        entry_time_full = datetime.now()
        slippage_entry = {
            "timestamp": entry_time_full.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "symbol": symbol,
            "type": setup["type"],
            "entry_price": entry_price,
            "depth": depth_data
        }
        with open(self.depth_file, 'a', encoding='utf-8') as df_json:
            df_json.write(json.dumps(slippage_entry) + "\n")
            
        # 2. Greeks
        greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        try:
            greek_res = self.api.optionGreek({"name": name, "expirydate": expiry})
            if greek_res and greek_res.get('status') and greek_res.get('data'):
                for item in greek_res['data']:
                    if str(item.get('strikePrice', '')) == str(strike) and item.get('optionType') == ("CE" if setup["type"]=="CALL" else "PE"):
                        greeks["delta"] = item.get('delta', 0.0)
                        greeks["gamma"] = item.get('gamma', 0.0)
                        greeks["theta"] = item.get('theta', 0.0)
                        greeks["vega"] = item.get('vega', 0.0)
                        break
        except: pass
            
        # 3. Setup Trade
        index_entry_price = current_nifty_df.iloc[-1]['close']
        target_price = round(entry_price * 1.10, 2)
        
        self.current_trade = {
            "symbol": symbol,
            "token": token,
            "type": setup["type"],
            "strike": strike,
            "expiry": expiry,
            "entry_price": entry_price,
            "target_price": target_price,
            "entry_time": entry_time_full,
            "index_entry": index_entry_price,
            "greeks": greeks,
            "params": params,
            "exch_seg": exch_seg,
            "setup_high": setup["master_high"],
            "setup_low": setup["master_low"],
            "status": "OPEN",
            "slippage": depth_data,
            "start_time": time.time()
        }
        
        self.trades_today += 1
        self.pending_setup = None
        print(f"--- SNIPER TRADE EXECUTED ---")
        print(f"Symbol: {symbol} (Target: ₹{target_price})")
        print(f"---------------------------")
        
    def manage_open_trade(self, live_ltp, current_nifty_df):
        if not self.current_trade:
            return
            
        t = self.current_trade
        token = t['token']
        exch_seg = t['exch_seg']
        
        try:
            # Check Option Price for TARGET
            res = self.api.ltpData(exch_seg, t['symbol'], token)
            current_opt_price = float(res['data']['ltp']) if (res and res.get('status')) else t['entry_price']
            
            # 1. Check for Gamma Stall (Time-Based Abort)
            if time.time() - t.get('start_time', 0) >= 180:
                self._close_trade(current_opt_price, current_nifty_df, "Gamma Stall Abort (3 Min Hold)")
                return
            
            # 2. Check for Target
            if current_opt_price >= t['target_price']:
                self._close_trade(current_opt_price, current_nifty_df, "10% TARGET HIT")
                return
                
            # 3. Check Index CLOSE Price for STOP LOSS
            now = datetime.now()
            # Grab the last candle that is NOT the current ticking minute
            closed_candles = current_nifty_df[current_nifty_df['timestamp'].dt.floor('min') < pd.Timestamp(now).floor('min')]
            
            if not closed_candles.empty:
                last_closed_price = float(closed_candles.iloc[-1]['close'])
                
                if t['type'] == "CALL" and last_closed_price < t["setup_low"]:
                    self._close_trade(current_opt_price, current_nifty_df, "CANDLE SL: Closed Below Master Low")
                    return
                elif t['type'] == "PUT" and last_closed_price > t["setup_high"]:
                    self._close_trade(current_opt_price, current_nifty_df, "CANDLE SL: Closed Above Master High")
                    return
                
        except Exception as e:
            print(f"Error managing trade: {e}")

    def _close_trade(self, exit_price, current_nifty_df, reason):
        exit_time = datetime.now()
        t = self.current_trade
        
        opt_diff = exit_price - t['entry_price']
        opt_pct = (opt_diff / t['entry_price']) * 100
        net_pl = opt_diff * t['params']['lot_size']
        result = "WIN" if net_pl > 0 else ("LOSS" if net_pl < -50 else "MIN LOSS")
        
        index_exit = current_nifty_df.iloc[-1]['close']
        nifty_pts = index_exit - t['index_entry']
        
        calc_delta = t['greeks']['delta']
        if calc_delta == 0.0 and nifty_pts != 0:
            calc_delta = round(opt_diff / nifty_pts, 3)
            
        try:
            exp_date = datetime.strptime(t['expiry'], "%d%b%Y").date()
            dte = (exp_date - exit_time.date()).days
        except:
            dte = 0
            
        atm = round(t['index_entry'] / 50) * 50
        otm_strikes_diff = (t['strike'] - atm) / 50
        otm_str = f"{abs(int(otm_strikes_diff))} {'above' if otm_strikes_diff > 0 else 'below'}"
        if otm_strikes_diff == 0:
            otm_str = "ATM"
            
        dur_secs = (exit_time - t['entry_time']).total_seconds()
        mins, secs = divmod(int(dur_secs), 60)
        dur_str = f"{mins:02d}:{secs:02d}"
        
        row_id = 1
        if os.path.exists(self.csv_file):
            with open(self.csv_file, 'r', encoding='utf-8') as f:
                row_id = sum(1 for line in f)
                
        chart_file = f"trade_{row_id}.png"
        generate_trade_chart(current_nifty_df, t, exit_time, net_pl, result, chart_file)
        
        row = [
            row_id, t['entry_time'].strftime("%d %b"), t['entry_time'].strftime("%H:%M:%S.%f")[:-3], exit_time.strftime("%H:%M:%S.%f")[:-3],
            dur_str, t['params']['index_name'], t['type'], t['strike'], t['expiry'], dte,
            t['entry_price'], exit_price, round(opt_diff, 2), f"{opt_pct:.2f}%", t['index_entry'], index_exit, round(nifty_pts, 2),
            calc_delta, t['greeks']['gamma'], t['greeks']['theta'], t['greeks']['vega'], atm, otm_str, round(net_pl, 2), result,
            f"/static/charts/{chart_file}", reason
        ]
        
        with open(self.csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row)
            
        # Calculate extra journal metrics
        duration_sec = time.time() - t.get('start_time', 0)
        duration_str = f"{int(duration_sec // 60)}m {int(duration_sec % 60)}s"
        
        opt_pct = ((exit_price - t['entry_price']) / t['entry_price']) * 100
        
        entry_idx = t.get('setup_high') if t['type'] == 'CALL' else t.get('setup_low')
        exit_idx = current_nifty_df.iloc[-1]['close']
        idx_pts = exit_idx - entry_idx if t['type'] == 'CALL' else entry_idx - exit_idx
        
        dte = "?"
        try:
            exp_date = datetime.strptime(t['expiry'], '%d%b%Y')
            dte = (exp_date.date() - datetime.now().date()).days
        except:
            pass
            
        self.history_list.append({
            "id": self.trades_today,
            "date": datetime.now().strftime('%H:%M:%S'),
            "duration": duration_str,
            "symbol": f"{t['type']} {t['strike']} ({dte} DTE)",
            "entry_price": t['entry_price'],
            "exit_price": exit_price,
            "opt_pct": round(opt_pct, 2),
            "idx_pts": round(idx_pts, 2),
            "net_pl": round(net_pl, 2),
            "capital_used": round(t['entry_price'] * t['params']['lot_size'], 2),
            "chart": f"/static/charts/{chart_file}",
            "reason": reason,
            "result": result,
            "slippage": t.get("slippage", {})
        })
        
        print(f"--- TRADE CLOSED ---")
        print(f"Result: {result} | P&L: ₹{round(net_pl, 2)}")
        
        # Apply 30-Minute Cooldown Guardrail
        self.cooldown_until = datetime.now() + timedelta(minutes=30)
        print(f"Entered 30-Minute Cooldown until {self.cooldown_until.strftime('%H:%M:%S')}")
        self.current_trade = None
