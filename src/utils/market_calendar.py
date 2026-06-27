from datetime import datetime, date

# NSE Holidays for 2026 and 2027 (Major fixed ones, dynamically adjustable)
NSE_HOLIDAYS = [
    # 2026 Holidays (Placeholder dates - exact dates change each year)
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 3),   # Mahashivratri (Estimate)
    date(2026, 3, 23),  # Holi (Estimate)
    date(2026, 4, 3),   # Good Friday (Estimate)
    date(2026, 4, 14),  # Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Gandhi Jayanti
    date(2026, 11, 8),  # Diwali (Estimate)
    date(2026, 12, 25), # Christmas
]

def is_trading_day(dt: datetime = None) -> bool:
    """
    Checks if a given datetime is a trading day on the NSE.
    Returns False if it is a weekend or a known public holiday.
    """
    if dt is None:
        dt = datetime.now()
        
    # Check if Saturday (5) or Sunday (6)
    if dt.weekday() >= 5:
        return False
        
    # Check if public holiday
    if dt.date() in NSE_HOLIDAYS:
        return False
        
    return True
