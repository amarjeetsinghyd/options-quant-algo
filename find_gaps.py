import pandas as pd
from datetime import datetime, timedelta

file_path = r"C:\Users\Amarjeet Singh\quant_algo_test\data\institutional_memory\canonical_observations\options_state\2026\06\29062026.parquet"

df = pd.read_parquet(file_path)
df['ts'] = pd.to_datetime(df['local_observation_timestamp'])

min_time = df['ts'].min().replace(second=0, microsecond=0)
max_time = df['ts'].max().replace(second=0, microsecond=0)

minutes_present = set(df['ts'].dt.floor('min').dt.to_pydatetime())

current = min_time
missing = []
while current <= max_time:
    if current not in minutes_present:
        missing.append(current)
    current += timedelta(minutes=1)

if not missing:
    print("No gaps found.")
else:
    ranges = []
    start = missing[0]
    prev = missing[0]
    for m in missing[1:]:
        if m == prev + timedelta(minutes=1):
            prev = m
        else:
            ranges.append((start, prev))
            start = m
            prev = m
    ranges.append((start, prev))

    print("Missing Time Gaps:")
    for s, e in ranges:
        if s == e:
            print(f" - {s.strftime('%H:%M')}")
        else:
            print(f" - {s.strftime('%H:%M')} to {e.strftime('%H:%M')}")
