import sqlite3
try:
    conn = sqlite3.connect('/home/opc/quant_bot/data/instruments.db', timeout=5.0)
    c = conn.cursor()
    c.execute('BEGIN IMMEDIATE;')
    print('Lock acquired successfully')
    c.execute('ROLLBACK;')
    conn.close()
except Exception as e:
    print('Error:', e)
