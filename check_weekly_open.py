"""Verify that weekend gaps in the downloaded data open at the expected server time.

Expected: every Monday the first bar is at 00:00 server time (= 22:00 UTC in
winter, 21:00 UTC in summer for FOREX.com NY+7).

Run after fetching data:
    python check_weekly_open.py

If summer weeks start at 23:00 server time instead of 00:00, the broker is
using a fixed UTC+2 clock (no DST). In that case, switch source_tz to
"Europe/Helsinki" in config.yaml and re-fetch.
"""
from pathlib import Path

import pandas as pd
import yaml

cfg = yaml.safe_load(open("config.yaml"))
path = cfg["data"]["path"]
source_tz = cfg["data"]["source_tz"]

if not Path(path).exists():
    raise SystemExit(f"Data file not found: {path}. Run fetch_mt5_data.py first.")

from fxbot.data import load_csv

print(f"Loading {path} (source_tz={source_tz}) ...")
df = load_csv(path, source_tz)
print(f"{len(df):,} bars loaded. Index timezone: {df.index.tz}\n")

# Find gaps > 36 h (weekend gaps are ~48 h; intra-week gaps shouldn't exist)
gaps = df.index.to_series().diff()
weekend_starts = df.index[gaps > pd.Timedelta(hours=36)]

if len(weekend_starts) == 0:
    print("No weekend gaps found — data may be too short or missing weekends.")
else:
    print(f"{'UTC time of first bar after gap':<35} {'Server time (NY+7)':<25} {'Note'}")
    print("-" * 80)
    warnings = 0
    for utc_ts in weekend_starts[:20]:  # print first 20
        import zoneinfo
        ny = utc_ts.astimezone(zoneinfo.ZoneInfo("America/New_York"))
        server_hour = (ny.hour + 7) % 24
        server_min = ny.minute
        note = ""
        if server_hour == 23:
            note = "*** UNEXPECTED 23:00 — fixed UTC+2 server? ***"
            warnings += 1
        elif server_hour != 0:
            note = f"*** UNEXPECTED {server_hour:02d}:{server_min:02d} server time ***"
            warnings += 1
        server_str = f"{(ny + pd.Timedelta(hours=7)).strftime('%Y-%m-%d %H:%M')} server"
        print(f"{str(utc_ts):<35} {server_str:<25} {note}")

    print()
    if warnings == 0:
        print("All weekend opens are at 00:00 server time. NY+7 offset is correct.")
    else:
        print(f"{warnings} unexpected open times found. Check the note above.")
        print("If you see 23:00 server time in summer, set source_tz: 'Europe/Helsinki'")
        print("in config.yaml and re-fetch the data.")
