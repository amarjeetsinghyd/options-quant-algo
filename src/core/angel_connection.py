import os
import pyotp
from dotenv import load_dotenv
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import urllib.request

# Load environment variables from .env file
load_dotenv()

# Fetch credentials
api_key = os.getenv("ANGEL_API_KEY")
client_id = os.getenv("ANGEL_CLIENT_ID")
password = os.getenv("ANGEL_PASSWORD")
totp_secret = os.getenv("ANGEL_TOTP_SECRET")

def get_angel_connection():
    """
    Initializes and returns the Angel One SmartConnect object.
    """
    load_dotenv(override=True)
    api_key = os.getenv("ANGEL_API_KEY")
    client_id = os.getenv("ANGEL_CLIENT_ID")
    password = os.getenv("ANGEL_PASSWORD")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")

    if not all([api_key, client_id, password, totp_secret]):
        raise ValueError("Angel API credentials not fully provided. Please check your .env file or Settings.")
        
    # Initialize the SmartConnect API client
    smartApi = SmartConnect(api_key=api_key)
    
    # Generate TOTP
    try:
        totp = pyotp.TOTP(totp_secret).now()
    except Exception as e:
        raise ValueError(f"Invalid TOTP Secret. Error: {e}")

    # Login
    data = smartApi.generateSession(client_id, password, totp)
    
    if data['status']:
        return smartApi, data['data']
    else:
        raise Exception(f"Login failed: {data}")

def get_websocket_connection(auth_token, api_key, client_id, feed_token):
    """
    Initializes and returns the Angel One SmartWebSocketV2 object.
    """
    sws = SmartWebSocketV2(auth_token, api_key, client_id, feed_token)
    return sws

if __name__ == "__main__":
    try:
        smartApi, session_data = get_angel_connection()
        
        # A simple API call to check profile, validating the connection
        profile = smartApi.getProfile(session_data['refreshToken'])
        print("Successfully connected to Angel One!")
        print(f"Logged in as: {profile['data']['name']}")
    except Exception as e:
        print(f"Error connecting to Angel One: {e}")
