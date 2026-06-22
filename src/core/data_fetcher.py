import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE_FILE = "data/OpenAPIScripMaster.json"

# All 50 Nifty 50 Constituents (Source: NSE MW-NIFTY-50-22-Jun-2026.csv)
# Replicates TradingView's volume aggregation for the Cash Index exactly
NIFTY_CONSTITUENTS = {
    "ADANIENT": "25",
    "ADANIPORTS": "15083",
    "APOLLOHOSP": "157",
    "ASIANPAINT": "236",
    "AXISBANK": "5900",
    "BAJAJ-AUTO": "16669",
    "BAJAJFINSV": "16675",
    "BAJFINANCE": "317",
    "BEL": "383",
    "BHARTIARTL": "10604",
    "CIPLA": "694",
    "COALINDIA": "20374",
    "DRREDDY": "881",
    "EICHERMOT": "910",
    "ETERNAL": "5097",
    "GRASIM": "1232",
    "HCLTECH": "7229",
    "HDFCBANK": "1333",
    "HDFCLIFE": "467",
    "HINDALCO": "1363",
    "HINDUNILVR": "1394",
    "ICICIBANK": "4963",
    "INDIGO": "11195",
    "INFY": "1594",
    "ITC": "1660",
    "JIOFIN": "18143",
    "JSWSTEEL": "11723",
    "KOTAKBANK": "1922",
    "LT": "11483",
    "M&M": "2031",
    "MARUTI": "10999",
    "MAXHEALTH": "22377",
    "NESTLEIND": "17963",
    "NTPC": "11630",
    "ONGC": "2475",
    "POWERGRID": "14977",
    "RELIANCE": "2885",
    "SBILIFE": "21808",
    "SBIN": "3045",
    "SHRIRAMFIN": "4306",
    "SUNPHARMA": "3351",
    "TATACONSUM": "3432",
    "TATASTEEL": "3499",
    "TCS": "11536",
    "TECHM": "13538",
    "TITAN": "3506",
    "TMPV": "3456",
    "TRENT": "1964",
    "ULTRACEMCO": "11532",
    "WIPRO": "3787",
}

# Sensex 30 Constituents (Source: BSE 22-Jun-2026)
# Used on Wednesday/Thursday for synthetic volume
SENSEX_CONSTITUENTS = {
    "ADANIPORTS": "532921",
    "ASIANPAINT": "500820",
    "AXISBANK": "532215",
    "BAJAJFINSV": "532978",
    "BAJFINANCE": "500034",
    "BEL": "500049",
    "BHARTIARTL": "532454",
    "ETERNAL": "543320",
    "HCLTECH": "532281",
    "HDFCBANK": "500180",
    "HINDUNILVR": "500696",
    "ICICIBANK": "532174",
    "INDIGO": "539448",
    "INFY": "500209",
    "ITC": "500875",
    "KOTAKBANK": "500247",
    "LT": "500510",
    "M&M": "500520",
    "MARUTI": "532500",
    "NTPC": "532555",
    "POWERGRID": "532898",
    "RELIANCE": "500325",
    "SBIN": "500112",
    "SUNPHARMA": "524715",
    "TATASTEEL": "500470",
    "TCS": "532540",
    "TECHM": "532755",
    "TITAN": "500114",
    "TRENT": "500251",
    "ULTRACEMCO": "532538",
}

# Cash Index tokens
NIFTY_CASH_TOKEN = "99926000"
SENSEX_CASH_TOKEN = "99919000"

class DataFetcher:
    def __init__(self, smartApi):
        self.api = smartApi
        self.token_df = self._load_tokens()

    def _load_tokens(self):
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(CACHE_FILE):
            print("Downloading token master list (this happens once a day)...")
            data = requests.get(MASTER_URL).json()
            with open(CACHE_FILE, 'w') as f:
                json.dump(data, f)
        
        # Load from cache
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
        return pd.DataFrame(data)

    def get_active_instrument(self):
        """
        Returns the Name and Exchange Segment based on the day of the week.
        Wed (2), Thu (3) -> SENSEX (BFO)
        Mon (0), Tue (1), Fri (4) -> NIFTY (NFO)
        """
        day = datetime.now().weekday()
        if day in [2, 3]:
            return "SENSEX", "BFO"
        else:
            return "NIFTY", "NFO"

    def get_current_futures_token(self):
        name, exch_seg = self.get_active_instrument()
        df = self.token_df
        fut_df = df[(df['name'] == name) & (df['exch_seg'] == exch_seg) & (df['instrumenttype'] == 'FUTIDX')].copy()
        
        if fut_df.empty:
            print(f"ERROR: Could not find Futures for {name} on {exch_seg}.")
            return None, None, None
            
        fut_df['expiry_dt'] = pd.to_datetime(fut_df['expiry'], format='%d%b%Y', errors='coerce')
        now = datetime.now()
        future_expiries = fut_df[fut_df['expiry_dt'] >= now]
        
        if future_expiries.empty:
            return None, None, None
            
        nearest = future_expiries.sort_values('expiry_dt').iloc[0]
        return nearest['token'], nearest['symbol'], exch_seg

    def get_cash_index_token(self):
        """Returns the Cash Index token for the active instrument."""
        name, _ = self.get_active_instrument()
        if name == "NIFTY":
            return NIFTY_CASH_TOKEN, "Nifty 50", "NSE"
        else:
            return SENSEX_CASH_TOKEN, "SENSEX", "BSE"

    def get_active_constituents(self):
        """Returns the correct constituent list for the active instrument."""
        name, _ = self.get_active_instrument()
        if name == "NIFTY":
            return NIFTY_CONSTITUENTS
        else:
            return SENSEX_CONSTITUENTS

    def _call_api_with_retry(self, api_func, *args, max_retries=5, initial_delay=1.0, **kwargs):
        """
        Executes an Angel One API call with exponential backoff retry logic.
        Handles rate limits ('exceeding access rate') dynamically.
        """
        delay = initial_delay
        for attempt in range(max_retries):
            try:
                # Execute the API function
                return api_func(*args, **kwargs)
            except Exception as e:
                err_msg = str(e)
                if "exceeding access rate" in err_msg or "Access denied" in err_msg or "rate limit" in err_msg.lower():
                    # Back off and try again
                    if attempt < max_retries - 1:
                        print(f"    API Rate Limit hit (attempt {attempt+1}/{max_retries}). Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                        delay *= 2.0
                        continue
                # If it's a different error or we've run out of retries, raise
                if attempt < max_retries - 1:
                    print(f"    API call failed (attempt {attempt+1}/{max_retries}): {e}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    delay *= 2.0
                else:
                    raise e
        raise Exception("Max retries exceeded for API call")

    def _fetch_constituent_volume(self, days_back=5, minutes_back=None, exact_fromdate=None):
        """
        Fetches 1-min historical data for all constituents of the active index
        (Nifty 50 or Sensex 30) and returns a DataFrame with the summed volume.
        Replicates TradingView's exact volume aggregation for the Cash Index.
        Uses staggered API calls with sleep to avoid rate-limit bans.
        """
        constituents = self.get_active_constituents()
        todate = datetime.now()
        if exact_fromdate is not None:
            fromdate = exact_fromdate
        elif minutes_back is not None:
            fromdate = todate - timedelta(minutes=minutes_back)
        else:
            fromdate = todate - timedelta(days=days_back)
        
        # Determine the exchange segment dynamically based on active instrument
        name, _ = self.get_active_instrument()
        exchange = "NSE" if name == "NIFTY" else "BSE"
        
        all_volumes = None
        fetched_count = 0
        
        for stock_name, token in constituents.items():
            try:
                historicParam = {
                    "exchange": exchange,
                    "symboltoken": token,
                    "interval": "ONE_MINUTE",
                    "fromdate": fromdate.strftime("%Y-%m-%d %H:%M"),
                    "todate": todate.strftime("%Y-%m-%d %H:%M")
                }
                response = self._call_api_with_retry(self.api.getCandleData, historicParam)
                
                if response and response.get('status') and response.get('data'):
                    columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                    stock_df = pd.DataFrame(response['data'], columns=columns)
                    stock_df['timestamp'] = pd.to_datetime(stock_df['timestamp'])
                    stock_df = stock_df.set_index('timestamp')[['volume']].rename(columns={'volume': stock_name})
                    
                    if all_volumes is None:
                        all_volumes = stock_df
                    else:
                        all_volumes = all_volumes.join(stock_df, how='outer')
                    
                    fetched_count += 1
                    
                # Sleep 1200ms between calls to stay under strict rate limit
                time.sleep(1.2)
                
            except Exception as e:
                print(f"  Warning: Could not fetch volume for {stock_name}: {e}")
                time.sleep(1.0)
                continue
        
        if all_volumes is not None:
            # Sum across all constituent columns to get synthetic volume
            all_volumes = all_volumes.fillna(0)
            all_volumes['synthetic_volume'] = all_volumes.sum(axis=1)
            print(f"  Synthetic Volume Engine: {fetched_count}/{len(constituents)} constituents loaded.")
            return all_volumes[['synthetic_volume']]
        
        return None

    def get_historical_candles(self, exchange, token, interval, days_back=5, minutes_back=None):
        todate = datetime.now()
        if minutes_back is not None:
            fromdate = todate - timedelta(minutes=minutes_back)
        else:
            fromdate = todate - timedelta(days=days_back)
        
        historicParam = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": interval,
            "fromdate": fromdate.strftime("%Y-%m-%d %H:%M"), 
            "todate": todate.strftime("%Y-%m-%d %H:%M")
        }
        try:
            response = self._call_api_with_retry(self.api.getCandleData, historicParam)
            if response and response.get('status') and response.get('data'):
                columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                df = pd.DataFrame(response['data'], columns=columns)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                return df
        except Exception as e:
            print(f"Error fetching candles for token {token}: {e}")
        return pd.DataFrame()

    def get_historical_candles_with_synthetic_volume(self, days_back=5):
        """
        Fetches the Cash Index price data (Nifty 50 or Sensex 30) and injects
        synthetic volume from its constituents. This replicates TradingView's
        volume aggregation approach for the Cash Index.
        """
        token, name, exchange = self.get_cash_index_token()
        print(f"Fetching {name} Cash Index price data from {exchange}...")
        price_df = self.get_historical_candles(exchange, token, "ONE_MINUTE", days_back=days_back)
        
        if price_df.empty:
            print(f"ERROR: Could not fetch {name} Cash Index price data.")
            return pd.DataFrame()
        
        # --- PRECISION SCOUTING LOGIC ---
        price_df['date'] = price_df['timestamp'].dt.date
        unique_dates = price_df['date'].unique()
        if len(unique_dates) > 2:
            target_dates = unique_dates[-2:]
            price_df = price_df[price_df['date'].isin(target_dates)]
            
        min_timestamp = price_df['timestamp'].min()
        price_df = price_df.drop(columns=['date'])
        
        print(f"{name} Cash Index: {len(price_df)} candles loaded. Volume is all zeros (expected).")
        constituents = self.get_active_constituents()
        print(f"Building Synthetic Volume from {len(constituents)} Constituents starting exactly at {min_timestamp}...")
        
        vol_df = self._fetch_constituent_volume(exact_fromdate=min_timestamp)
        
        if vol_df is not None:
            # Merge synthetic volume into the price DataFrame
            price_df = price_df.set_index('timestamp')
            price_df = price_df.join(vol_df, how='left')
            price_df['volume'] = price_df['synthetic_volume'].fillna(0).astype(int)
            price_df = price_df.drop(columns=['synthetic_volume'])
            price_df = price_df.reset_index()
            print(f"Synthetic Volume injected! Avg volume per candle: {price_df['volume'].mean():.0f}")
        else:
            print("WARNING: Could not build synthetic volume. VFI/RVOL will be unreliable.")
        
        return price_df
        
    def get_weekly_option_tokens(self):
        name, exch_seg = self.get_active_instrument()
        df = self.token_df
        opt_df = df[(df['name'] == name) & (df['exch_seg'] == exch_seg) & (df['instrumenttype'] == 'OPTIDX')].copy()
        
        if opt_df.empty:
            return pd.DataFrame()
            
        opt_df['expiry_dt'] = pd.to_datetime(opt_df['expiry'], format='%d%b%Y', errors='coerce')
        now = datetime.now()
        future_expiries = opt_df[opt_df['expiry_dt'] >= now]
        if future_expiries.empty:
            return pd.DataFrame()
            
        nearest_expiry = future_expiries.sort_values('expiry_dt').iloc[0]['expiry_dt']
        weekly_opts = future_expiries[future_expiries['expiry_dt'] == nearest_expiry]
        return weekly_opts
