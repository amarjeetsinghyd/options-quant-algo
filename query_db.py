import sqlite3
import pandas as pd
conn = sqlite3.connect('/home/opc/quant_bot/data/instruments.db')
print('FUTURES WITH MAPPINGS:')
query = """
SELECT m.broker_token, i.symbol, i.expiry
FROM instruments i
JOIN broker_mappings m ON i.instrument_id = m.instrument_id
WHERE m.broker_name = 'SHOONYA' AND i.name = 'NIFTY' AND i.exch_seg = 'NFO' AND i.instrumenttype = 'FUTIDX'
"""
print(pd.read_sql(query, conn))
print('OPTIONS WITH MAPPINGS:')
query2 = """
SELECT m.broker_token, i.symbol, i.expiry
FROM instruments i
JOIN broker_mappings m ON i.instrument_id = m.instrument_id
WHERE m.broker_name = 'SHOONYA' AND i.name = 'NIFTY' AND i.exch_seg = 'NFO' AND i.instrumenttype = 'OPTIDX'
"""
print(pd.read_sql(query2, conn))
