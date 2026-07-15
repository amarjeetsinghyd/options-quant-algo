import sys
sys.path.append('C:\\Quant')
import urllib.request
import zipfile
import io
import csv

try:
    from src.core.data_fetcher import NIFTY_CONSTITUENTS, SENSEX_CONSTITUENTS
except ImportError as e:
    print(f"Error importing constituents: {e}")
    sys.exit(1)

def fetch_shoonya_master(url, filename):
    print(f"Downloading {url}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req)
    z = zipfile.ZipFile(io.BytesIO(response.read()))
    data = z.open(filename).read().decode('utf-8')
    return data

def verify_constituents(constituents, master_data, exchange, master_symbol_col='Symbol', token_col='Token', fallback_col='TradingSymbol'):
    reader = csv.DictReader(io.StringIO(master_data))
    master_map = {}
    master_fallback_map = {}
    for row in reader:
        # Some rows might have trailing commas making keys empty
        if row.get(master_symbol_col):
            master_map[row[master_symbol_col]] = row.get(token_col)
        if row.get(fallback_col):
            master_fallback_map[row[fallback_col]] = row.get(token_col)

    mismatches = []
    missing = []
    verified_count = 0

    for symbol, expected_token in constituents.items():
        actual_token = master_map.get(symbol)
        if not actual_token:
            actual_token = master_fallback_map.get(symbol)
            
        if not actual_token:
            missing.append(symbol)
        elif actual_token != expected_token:
            mismatches.append((symbol, expected_token, actual_token))
        else:
            verified_count += 1
            
    print(f"--- {exchange} Verification ---")
    print(f"Total verified: {verified_count}/{len(constituents)}")
    if missing:
        print(f"Missing symbols (not found in master): {missing}")
    if mismatches:
        print("Mismatches (Symbol, Old Token, Shoonya Token):")
        for m in mismatches:
            print(f"  {m[0]}: old={m[1]}, shoonya={m[2]}")
    print("\n")

if __name__ == "__main__":
    nse_data = fetch_shoonya_master('https://api.shoonya.com/NSE_symbols.txt.zip', 'NSE_symbols.txt')
    verify_constituents(NIFTY_CONSTITUENTS, nse_data, 'NSE (NIFTY 50)')
    
    bse_data = fetch_shoonya_master('https://api.shoonya.com/BSE_symbols.txt.zip', 'BSE_symbols.txt')
    verify_constituents(SENSEX_CONSTITUENTS, bse_data, 'BSE (SENSEX 30)')
