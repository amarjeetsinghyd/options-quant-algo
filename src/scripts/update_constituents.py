import sys
import os
import json
import logging
from datetime import datetime
import csv
import io
import urllib.request
import zipfile
import traceback
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.config.engineering_config import DATA_DIR
from src.utils.logger import get_logger

logger = get_logger("update_constituents")

def fetch_shoonya_master(url, filename):
    """Downloads and extracts a Shoonya master file"""
    logger.info(f"Downloading Shoonya Master: {url}")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req, timeout=30)
    z = zipfile.ZipFile(io.BytesIO(response.read()))
    data = z.open(filename).read().decode('utf-8')
    return data

def get_nifty50_symbols():
    """Fetch Nifty 50 symbols using nsepython"""
    logger.info("Fetching Nifty 50 constituents via nsepython...")
    try:
        from nsepython import index_info
        data = index_info("NIFTY 50")
        if 'data' in data:
            symbols = [item['symbol'] for item in data['data']]
            if 'NIFTY 50' in symbols:
                symbols.remove('NIFTY 50')
            return symbols
        else:
            raise ValueError("Invalid nsepython response")
    except Exception as e:
        logger.error(f"nsepython failed: {e}")
        # Fallback to direct NSE API
        logger.info("Attempting fallback Wikipedia parsing via pandas...")
        import pandas as pd
        import requests
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        html = requests.get("https://en.wikipedia.org/wiki/NIFTY_50", headers=headers).text
        tables = pd.read_html(html)
        for df in tables:
            if 'Symbol' in df.columns:
                symbols = df['Symbol'].tolist()
                return symbols
        raise Exception("Could not find NIFTY 50 symbol column on Wikipedia")

def get_sensex30_symbols():
    """Fetch Sensex 30 symbols using bsedata"""
    logger.info("Fetching Sensex 30 constituents via bsedata...")
    try:
        from bsedata.bse import BSE
        b = BSE()
        logger.info("Attempting fallback Wikipedia parsing for Sensex...")
        import pandas as pd
        import requests
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        html = requests.get("https://en.wikipedia.org/wiki/BSE_SENSEX", headers=headers).text
        tables = pd.read_html(html)
        for df in tables:
            if 'Ticker' in df.columns:
                symbols = df['Ticker'].tolist()
                # Sensex wikipedia uses Ticker like BOM:500325
                clean_symbols = []
                for sym in symbols:
                    sym_str = str(sym)
                    if 'BOM:' in sym_str:
                        clean_symbols.append(sym_str.replace('BOM:', '').strip())
                    else:
                        clean_symbols.append(sym_str)
                return clean_symbols
        raise Exception("Could not find BSE SENSEX Ticker column on Wikipedia")
    except Exception as e:
        logger.error(f"bsedata/BSE API failed: {e}")
        raise

def map_symbols_to_tokens(symbols, master_data, fallback_to_self=False):
    """Maps exchange symbols to Shoonya tokens using the master file"""
    reader = csv.DictReader(io.StringIO(master_data))
    master_map = {}
    master_fallback_map = {}
    for row in reader:
        if row.get('Symbol'): master_map[row['Symbol']] = row.get('Token')
        if row.get('TradingSymbol'): master_fallback_map[row['TradingSymbol']] = row.get('Token')

    mapped = {}
    for sym in symbols:
        # If the symbol is already a numeric token (like BSE scrip code), just map it
        if sym.isdigit() and fallback_to_self:
            mapped[sym] = sym
            continue
            
        token = master_map.get(sym) or master_fallback_map.get(sym)
        if token:
            mapped[sym] = token
        else:
            logger.warning(f"Could not map symbol {sym} to a Shoonya Token")
            
    return mapped

def main():
    try:
        # 1. Fetch live constituent lists
        nifty_symbols = get_nifty50_symbols()
        sensex_symbols = get_sensex30_symbols()
        
        if not nifty_symbols or len(nifty_symbols) < 45:
            raise Exception("Nifty symbols fetch returned too few elements")
        if not sensex_symbols or len(sensex_symbols) < 25:
            raise Exception("Sensex symbols fetch returned too few elements")
            
        logger.info(f"Fetched {len(nifty_symbols)} Nifty symbols and {len(sensex_symbols)} Sensex symbols")
        
        # 2. Download Shoonya Masters
        nse_data = fetch_shoonya_master('https://api.shoonya.com/NSE_symbols.txt.zip', 'NSE_symbols.txt')
        bse_data = fetch_shoonya_master('https://api.shoonya.com/BSE_symbols.txt.zip', 'BSE_symbols.txt')
        
        # 3. Map to tokens
        nifty_mapped = map_symbols_to_tokens(nifty_symbols, nse_data)
        sensex_mapped = map_symbols_to_tokens(sensex_symbols, bse_data, fallback_to_self=True)
        
        # 4. Save to JSON
        institutional_memory_dir = os.path.join(DATA_DIR, '../institutional_memory')
        os.makedirs(institutional_memory_dir, exist_ok=True)
        
        output_file = os.path.join(institutional_memory_dir, "constituents.json")
        payload = {
            "nifty_50": nifty_mapped,
            "sensex_30": sensex_mapped,
            "updated_at": datetime.now().isoformat()
        }
        
        with open(output_file, 'w') as f:
            json.dump(payload, f, indent=4)
            
        logger.info(f"Successfully saved dynamically updated constituents to {output_file}")
        
        # 5. Restart the PM2 quant_bot service to cleanly reload websocket tokens
        logger.info("Triggering PM2 restart to apply new tokens...")
        os.system("pm2 restart quant_bot")
        
    except Exception as e:
        logger.error(f"Failed to update constituents: {e}\n{traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main()
