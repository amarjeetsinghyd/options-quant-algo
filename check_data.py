import pandas as pd
from pathlib import Path
import datetime

file_path = r"C:\Users\Amarjeet Singh\quant_algo_test\data\institutional_memory\canonical_observations\options_state\2026\06\29062026.parquet"

df = pd.read_parquet(file_path)
df['ts'] = pd.to_datetime(df['local_observation_timestamp'])

min_time = df['ts'].min()
max_time = df['ts'].max()

print(f"Total Rows: {len(df)}")
print(f"Data Starts At: {min_time}")
print(f"Data Ends At: {max_time}")

minutes_present = df['ts'].dt.floor('min').dt.time.unique()
minutes_present = sorted(list(minutes_present))

start = min_time.replace(second=0, microsecond=0)
end = max_time.replace(second=0, microsecond=0)

all_minutes = []
current = start
while current <= end:
    all_minutes.append(current.time())
    current += datetime.timedelta(minutes=1)

missing = [m.strftime("%H:%M") for m in all_minutes if m not in minutes_present]
print(f"Missing Minutes Count: {len(missing)}")
if len(missing) > 0:
    print(f"First 10 Missing: {missing[:10]}")
