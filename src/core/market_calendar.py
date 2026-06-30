import sys
from datetime import datetime, date, time, timedelta

from src.utils.logger import get_logger
logger = get_logger("market_calendar")


# Indian Stock Market Holidays 2026 (Extendable)
# Reference: NSE/BSE Official Holiday List
HOLIDAYS_2026 = {
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 6),    # Holi
    date(2026, 3, 27),   # Good Friday
    date(2026, 4, 2),    # Ram Navami
    date(2026, 4, 14),   # Ambedkar Jayanti
    date(2026, 5, 1),    # May Day / Maharashtra Day
    date(2026, 5, 25),   # Bakri Id
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 10, 22),  # Dussehra
    date(2026, 11, 12),  # Diwali (Muhurat session date)
    date(2026, 12, 25),  # Christmas
}

# Muhurat Trading Sessions (Diwali evening)
MUHURAT_SESSIONS = {
    date(2026, 11, 12): (time(18, 0), time(19, 0)) # 6:00 PM to 7:00 PM
}

class MarketCalendar:
    """
    Market Calendar Engine for Indian Stock Exchanges (NSE/BSE).
    This serves as the single source of truth for session tracking and time validation.
    """
    @staticmethod
    def is_weekend(dt=None):
        dt = dt or datetime.now()
        return dt.weekday() >= 5 # Saturday (5) or Sunday (6)

    @staticmethod
    def is_holiday(dt=None):
        dt = dt or datetime.now()
        d = dt.date() if isinstance(dt, datetime) else dt
        return d in HOLIDAYS_2026

    @staticmethod
    def is_muhurat(dt=None):
        dt = dt or datetime.now()
        d = dt.date() if isinstance(dt, datetime) else dt
        return d in MUHURAT_SESSIONS

    @staticmethod
    def is_market_open(dt=None):
        """Checks if current time falls within official live market trading hours."""
        dt = dt or datetime.now()
        d = dt.date()
        
        # Weekends
        if MarketCalendar.is_weekend(dt):
            return False
            
        # Holidays
        if MarketCalendar.is_holiday(dt):
            # Check if it falls inside Muhurat special session
            if MarketCalendar.is_muhurat(dt):
                t = dt.time()
                m_start, m_end = MUHURAT_SESSIONS[d]
                return m_start <= t <= m_end
            return False
            
        # Standard Market hours (09:15 to 15:30)
        t = dt.time()
        market_start = time(9, 15, 0)
        market_end = time(15, 30, 0)
        return market_start <= t <= market_end

    @staticmethod
    def is_preopen(dt=None):
        """Checks if current time falls within pre-open session (09:00 to 09:15)."""
        dt = dt or datetime.now()
        
        if MarketCalendar.is_weekend(dt) or (MarketCalendar.is_holiday(dt) and not MarketCalendar.is_muhurat(dt)):
            return False
            
        t = dt.time()
        preopen_start = time(9, 0, 0)
        preopen_end = time(9, 15, 0)
        return preopen_start <= t < preopen_end

    @staticmethod
    def is_after_market(dt=None):
        """Checks if current time is outside standard trading and preopen hours."""
        dt = dt or datetime.now()
        
        if MarketCalendar.is_weekend(dt) or (MarketCalendar.is_holiday(dt) and not MarketCalendar.is_muhurat(dt)):
            return True
            
        t = dt.time()
        market_end = time(15, 30, 0)
        preopen_start = time(9, 0, 0)
        return t > market_end or t < preopen_start

    @staticmethod
    def get_session_type(dt=None):
        """
        Classifies the market environment for records and logs.
        Session Hierarchy: REPLAY / SIMULATION > HOLIDAY > LIVE > PREOPEN > AFTER_MARKET
        """
        # Command line arguments override live time for testing / simulations
        if any("replay" in arg.lower() for arg in sys.argv):
            return "REPLAY"
        if any("sim" in arg.lower() for arg in sys.argv):
            return "SIMULATION"
            
        dt = dt or datetime.now()
        
        if MarketCalendar.is_weekend(dt) or MarketCalendar.is_holiday(dt):
            # Special Muhurat live check
            if MarketCalendar.is_muhurat(dt) and MarketCalendar.is_market_open(dt):
                return "LIVE"
            return "HOLIDAY"
            
        if MarketCalendar.is_market_open(dt):
            return "LIVE"
        elif MarketCalendar.is_preopen(dt):
            return "PREOPEN"
        else:
            return "AFTER_MARKET"

    @staticmethod
    def next_market_open(dt=None):
        """Finds the next trading day's open datetime."""
        dt = dt or datetime.now()
        
        # If today is a trading day and we are before 9:15 AM, the next open is today
        if not MarketCalendar.is_weekend(dt) and not MarketCalendar.is_holiday(dt):
            if dt.time() < time(9, 15, 0):
                return datetime.combine(dt.date(), time(9, 15, 0))
                
        current = dt
        for _ in range(10): # Safe limit to look forward
            current += timedelta(days=1)
            if not MarketCalendar.is_weekend(current) and not MarketCalendar.is_holiday(current):
                return datetime.combine(current.date(), time(9, 15, 0))
        return None

    @staticmethod
    def next_market_close(dt=None):
        """Finds the close datetime of the next open session."""
        dt = dt or datetime.now()
        if MarketCalendar.is_market_open(dt):
            return datetime.combine(dt.date(), time(15, 30, 0))
            
        nxt_open = MarketCalendar.next_market_open(dt)
        if nxt_open:
            return datetime.combine(nxt_open.date(), time(15, 30, 0))
        return None

if __name__ == "__main__":
    # Small self-test
    logger.info("Market Open Now?", MarketCalendar.is_market_open())
    logger.info("Session Type:", MarketCalendar.get_session_type())
