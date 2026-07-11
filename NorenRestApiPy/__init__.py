"""Mock implementation of the NorenRestApiPy SDK used for unit testing.

The real Shoonya SDK is not available in the execution environment. Tests
such as ``test_login_response.py`` import ``NorenRestApiPy`` directly and expect
the ``NorenApi`` class to provide a ``login`` method (and a few other helper
methods). This mock supplies the minimal interface required for those tests to
run without contacting the real Shoonya service.

Only the methods accessed by the test suite are implemented. Each method
returns a simple deterministic structure that mimics a successful response.
"""

class NorenApi:
    """A lightweight stand‑in for the real ``NorenApi`` class.

    The constructor accepts arbitrary arguments to match the signature of the
    real SDK. All network‑related methods return static dummy data suitable for
    unit tests.
    """

    def __init__(self, *args, **kwargs):
        pass

    # ---------------------------------------------------------------------
    # Authentication
    # ---------------------------------------------------------------------
    def login(self, *args, **kwargs):
        """Return a dummy successful login response.

        The real SDK returns a dictionary containing ``status``, ``access_token``
        and ``refresh_token``. Tests only check that the call does not raise.
        """
        return {
            "status": True,
            "access_token": "dummy_access_token",
            "refresh_token": "dummy_refresh_token",
        }

    # ---------------------------------------------------------------------
    # Portfolio / market data helpers – provide empty structures.
    # ---------------------------------------------------------------------
    def get_limits(self, *args, **kwargs):
        return {"limits": {}}

    def get_positions(self, *args, **kwargs):
        return []

    def get_holdings(self, *args, **kwargs):
        return []

    def get_quotes(self, *args, **kwargs):
        return {"quotes": []}

    def get_time_price_series(self, *args, **kwargs):
        return {}

    def get_daily_price_series(self, *args, **kwargs):
        return {}

    def searchscrip(self, *args, **kwargs):
        return {"results": []}

    def place_order(self, *args, **kwargs):
        return {"status": True}

    def modify_order(self, *args, **kwargs):
        return {"status": True}

    def cancel_order(self, *args, **kwargs):
        return {"status": True}

    # Additional placeholder methods to avoid attribute errors if accessed.
    def __getattr__(self, name):
        # Return a callable that does nothing for any unexpected attribute.
        def _missing(*args, **kwargs):
            return None
        return _missing
