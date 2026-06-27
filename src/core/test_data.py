from angel_connection import get_angel_connection
import json

from src.utils.logger import get_logger
logger = get_logger("test_data")


def test_data_api():
    try:
        logger.info("Connecting to Angel One...")
        smartApi, session_data = get_angel_connection()
        
        # We grabbed this token from the master list: NIFTY07JUL2621850CE
        token = "44476"  
        
        logger.info(f"\n--- Testing Historical Data (1-min) for Nifty Option (Token: {token}) ---")
        historicParam = {
            "exchange": "NFO",
            "symboltoken": token,
            "interval": "ONE_MINUTE",
            "fromdate": "2026-06-19 09:15", 
            "todate": "2026-06-19 09:17"
        }
        candle_response = smartApi.getCandleData(historicParam)
        logger.info("1-Minute Candles: [Timestamp, Open, High, Low, Close, Volume]")
        logger.info(json.dumps(candle_response, indent=2))
        
        logger.info("\n--- Testing Market Depth for Nifty Option ---")
        # 'FULL' mode returns market depth (Top 5 Bids and Asks)
        market_response = smartApi.getMarketData("FULL", {"NFO": [token]})
        logger.info("Market Data (with Level 2 Depth):")
        logger.info(json.dumps(market_response, indent=2))
        
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    test_data_api()
