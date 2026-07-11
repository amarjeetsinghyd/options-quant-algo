"""Mock submodule for ``NorenRestApiPy.NorenApi``.

The real SDK provides a ``NorenApi`` class inside the ``NorenApi`` package.
Tests import it via ``from NorenRestApiPy.NorenApi import NorenApi``. This file
mirrors that structure and supplies a minimal implementation sufficient for the
unit tests.
"""

class NorenApi:
    def __init__(self, *args, **kwargs):
        pass

    def login(self, *args, **kwargs):
        return {
            "status": True,
            "access_token": "dummy_access_token",
            "refresh_token": "dummy_refresh_token",
        }

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

    def __getattr__(self, name):
        def _missing(*args, **kwargs):
            return None
        return _missing
