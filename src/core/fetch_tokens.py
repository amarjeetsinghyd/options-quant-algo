import pandas as pd
import requests

from src.utils.logger import get_logger
logger = get_logger("fetch_tokens")


def get_tokens():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    logger.info("Downloading token master list from Angel One...")
    try:
        data = requests.get(url).json()
        df = pd.DataFrame(data)
        
        # 1. Nifty 50 Index Token
        nifty_idx = df[(df['name'] == 'Nifty 50') & (df['exch_seg'] == 'NSE')]
        logger.info("\n--- Nifty 50 Index ---")
        logger.info(nifty_idx[['symbol', 'token', 'exch_seg']])
        
        # 2. Nifty Options (NFO)
        # Filter for NIFTY options, sorting by expiry
        nfo_nifty = df[(df['name'] == 'NIFTY') & (df['exch_seg'] == 'NFO') & (df['instrumenttype'] == 'OPTIDX')]
        
        logger.info("\n--- Sample Nifty Options ---")
        logger.info(nfo_nifty[['symbol', 'token', 'expiry', 'strike']].head(10))
        
    except Exception as e:
        logger.error(f"Error fetching tokens: {e}")

if __name__ == "__main__":
    get_tokens()
