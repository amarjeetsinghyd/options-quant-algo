import pandas as pd
import requests

def get_tokens():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    print("Downloading token master list from Angel One...")
    try:
        data = requests.get(url).json()
        df = pd.DataFrame(data)
        
        # 1. Nifty 50 Index Token
        nifty_idx = df[(df['name'] == 'Nifty 50') & (df['exch_seg'] == 'NSE')]
        print("\n--- Nifty 50 Index ---")
        print(nifty_idx[['symbol', 'token', 'exch_seg']])
        
        # 2. Nifty Options (NFO)
        # Filter for NIFTY options, sorting by expiry
        nfo_nifty = df[(df['name'] == 'NIFTY') & (df['exch_seg'] == 'NFO') & (df['instrumenttype'] == 'OPTIDX')]
        
        print("\n--- Sample Nifty Options ---")
        print(nfo_nifty[['symbol', 'token', 'expiry', 'strike']].head(10))
        
    except Exception as e:
        print(f"Error fetching tokens: {e}")

if __name__ == "__main__":
    get_tokens()
