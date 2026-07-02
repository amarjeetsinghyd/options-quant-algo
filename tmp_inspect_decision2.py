import os
import pandas as pd

path = os.path.join(os.getcwd(), 'data', 'decision_history.parquet')
df = pd.read_parquet(path, engine='pyarrow')
df['ts'] = pd.to_datetime(df['timestamp'], errors='coerce')
window = df[(df['ts'] >= pd.Timestamp('2026-07-01 14:40:00')) & (df['ts'] <= pd.Timestamp('2026-07-01 14:45:30'))].sort_values('ts')
print('TOTAL WINDOW', len(window))
for _, row in window.iterrows():
    if row['status'] == 'ACCEPTED' or row['ts'].minute == 42:
        print(row['ts'], row['status'], row['decision_action'], row['human_reason'])
