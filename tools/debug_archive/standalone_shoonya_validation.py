import os
import json
import time
import traceback
import sys
import datetime
import Shoonya_API_OAuth as shoonya  # Shoonya_API_OAuth package

# ---------------------------------------------------------------------------
# Optional loading of a .env file for local development.
# If the ``python-dotenv`` package is available we load variables from a
# ``.env`` file placed in the project root.  This keeps secret values out of
# source control while allowing a simple ``cp .env.example .env`` workflow.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    # Load .env from the repository root (same directory as this script)
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    # ``python-dotenv`` is optional – the script works without it.
    pass


# Collect results for machine‑readable output
_validation_results = {}

def log_result(step, success, details=""):
    """Log a human‑readable line and store the result in the global dict.

    The function prints a ``[PASS]``/``[FAIL]`` line for interactive use and
    records a structured entry in ``_validation_results`` so that the script can
    emit a JSON summary at the end.
    """
    status = "PASS" if success else "FAIL"
    print(f"[{status}] {step}{' - ' + details if details else ''}")
    # Store a concise result for machine consumption
    _validation_results[step] = {
        "status": status,
        "details": details,
    }


def get_env(var_name, required=True):
    val = os.getenv(var_name)
    if required and not val:
        raise EnvironmentError(f"Environment variable {var_name} is required but not set")
    return val


def main():
    # Load credentials from environment variables
    try:
        userid = get_env("SHOONYA_USERID")
        password = get_env("SHOONYA_PASSWORD")
        twoFA = get_env("SHOONYA_2FA")
        vendor_code = get_env("SHOONYA_VENDOR_CODE")
        api_secret = get_env("SHOONYA_API_SECRET")
        imei = get_env("SHOONYA_IMEI")
        client_id = get_env("SHOONYA_CLIENT_ID")
        api_key = get_env("SHOONYA_API_KEY")
    except EnvironmentError as e:
        print(str(e))
        return

    # Initialize API client
    api = shoonya.NorenApiPy()
    try:
        login_resp = api.login(
            userid=userid,
            password=password,
            twoFA=twoFA,
            vendor_code=vendor_code,
            api_secret=api_secret,
            imei=imei,
        )
        # Do not log the full response as it may contain access tokens.
        login_success = login_resp.get("stat") == "Ok"
        log_result("Login", login_success, "OK" if login_success else "Failed")
    except Exception:
        log_result("Login", False, traceback.format_exc())
        return

    # Token refresh test (use internal method if available)
    try:
        # The SDK may expose a method to refresh token; if not, we simply reuse login token
        token = api.susertoken if hasattr(api, "susertoken") else None
        if token:
            # Mask the token value – only indicate presence.
            log_result("TokenRefresh", True, "Token present")
        else:
            log_result("TokenRefresh", False, "No token attribute found")
    except Exception:
        log_result("TokenRefresh", False, traceback.format_exc())

    # Profile (if available)
    try:
        if hasattr(api, "get_profile"):
            profile = api.get_profile()
            log_result("Profile", True, json.dumps(profile))
        else:
            log_result("Profile", False, "Method get_profile not found")
    except Exception:
        log_result("Profile", False, traceback.format_exc())

    # Funds (if available)
    try:
        if hasattr(api, "get_funds"):
            funds = api.get_funds()
            log_result("Funds", True, json.dumps(funds))
        else:
            log_result("Funds", False, "Method get_funds not found")
    except Exception:
        log_result("Funds", False, traceback.format_exc())

    # Instrument search
    try:
        if hasattr(api, "searchscrip"):
            instruments = api.searchscrip("RELIANCE")
            log_result("InstrumentSearch", True, json.dumps(instruments)[:200])
        else:
            log_result("InstrumentSearch", False, "Method searchscrip not found")
    except Exception:
        log_result("InstrumentSearch", False, traceback.format_exc())

    # Quotes
    try:
        if hasattr(api, "get_quotes"):
            quotes = api.get_quotes(["NSE:RELIANCE"])  # list of tokens
            log_result("Quotes", True, json.dumps(quotes)[:200])
        else:
            log_result("Quotes", False, "Method get_quotes not found")
    except Exception:
        log_result("Quotes", False, traceback.format_exc())

    # Historical intraday (time price series)
    try:
        if hasattr(api, "get_time_price_series"):
            intraday = api.get_time_price_series(
                token="NSE:RELIANCE",
                interval="5",
                from_date="2023-01-01",
                to_date="2023-01-01",
            )
            log_result("IntradayHistorical", True, json.dumps(intruder)[:200])
        else:
            log_result("IntradayHistorical", False, "Method get_time_price_series not found")
    except Exception:
        log_result("IntradayHistorical", False, traceback.format_exc())

    # Historical daily (daily price series)
    try:
        if hasattr(api, "get_daily_price_series"):
            daily = api.get_daily_price_series(
                token="NSE:RELIANCE",
                from_date="2023-01-01",
                to_date="2023-01-10",
            )
            log_result("DailyHistorical", True, json.dumps(daily)[:200])
        else:
            log_result("DailyHistorical", False, "Method get_daily_price_series not found")
    except Exception:
        log_result("DailyHistorical", False, traceback.format_exc())

    # WebSocket lifecycle
    try:
        ws = shoonya.WebSocketClient(access_token=api.susertoken, client_id=client_id, api_key=api_key)
        ws.start()
        sample_token = "NSE:RELIANCE"
        ws.subscribe(sample_token)
        # Receive a few messages
        msgs = []
        for _ in range(3):
            msg = ws.receive(timeout=5)
            if msg:
                msgs.append(msg)
        log_result("WebSocketReceive", len(msgs) > 0, f"Received {len(msgs)} messages")
        # Reconnect test
        ws.close()
        time.sleep(1)
        ws.start()
        ws.subscribe(sample_token)
        msg2 = ws.receive(timeout=5)
        log_result("WebSocketReconnect", msg2 is not None, "Reconnected and received message" if msg2 else "No message after reconnect")
        ws.close()
    except Exception:
        log_result("WebSocketLifecycle", False, traceback.format_exc())


if __name__ == "__main__":
    main()
    # Emit a JSON summary on stdout as the last line – callers can parse this.
    # Metadata for versioning and traceability
    SCHEMA_VERSION = "1.0"
    VALIDATOR_VERSION = "1.0.0"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "timestamp": timestamp,
        "broker": "SHOONYA",
        "status": "PASS" if all(v["status"] == "PASS" for v in _validation_results.values()) else "FAIL",
        "details": _validation_results,
    }
    print(json.dumps(summary))