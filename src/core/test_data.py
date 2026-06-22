from angel_connection import get_angel_connection
import json

def test_data_api():
    try:
        print("Connecting to Angel One...")
        smartApi, session_data = get_angel_connection()
        
        # We grabbed this token from the master list: NIFTY07JUL2621850CE
        token = "44476"  
        
        print(f"\n--- Testing Historical Data (1-min) for Nifty Option (Token: {token}) ---")
        historicParam = {
            "exchange": "NFO",
            "symboltoken": token,
            "interval": "ONE_MINUTE",
            "fromdate": "2026-06-19 09:15", 
            "todate": "2026-06-19 09:17"
        }
        candle_response = smartApi.getCandleData(historicParam)
        print("1-Minute Candles: [Timestamp, Open, High, Low, Close, Volume]")
        print(json.dumps(candle_response, indent=2))
        
        print("\n--- Testing Market Depth for Nifty Option ---")
        # 'FULL' mode returns market depth (Top 5 Bids and Asks)
        market_response = smartApi.getMarketData("FULL", {"NFO": [token]})
        print("Market Data (with Level 2 Depth):")
        print(json.dumps(market_response, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_data_api()
