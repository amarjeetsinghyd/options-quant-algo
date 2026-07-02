import os
import pandas as pd
from datetime import datetime

def main():
    path = os.path.join(os.getcwd(), 'data', 'decision_history.parquet')
    print('PARQUET:', path)
    df = pd.read_parquet(path, engine='pyarrow')
    print('ROWS:', len(df))
    print('COLS:', list(df.columns))
    if 'timestamp' not in df.columns:
        print('MISSING timestamp')
        return
    df['ts'] = pd.to_datetime(df['timestamp'], errors='coerce')
    target = pd.Timestamp('2026-07-01 14:42:00')
    window = df[(df['ts'] >= target - pd.Timedelta('5min')) & (df['ts'] <= target + pd.Timedelta('5min'))].sort_values('ts')
    print('WINDOW COUNT:', len(window))
    if window.empty:
        return
    print(window[['ts', 'status', 'decision_action', 'human_reason']].to_string(index=False))

if __name__ == '__main__':
    main()
