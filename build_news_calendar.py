"""Build the historical high-impact news calendar used by backtests.

    python build_news_calendar.py      # -> data/news/high_impact_2021_2025.csv

Output columns: time (UTC, ISO), currency, event. Release dates are hard-coded below
from official sources; each release's LOCAL clock time is converted to UTC with the
real time-zone rules (zoneinfo), so US/UK/EU daylight-saving shifts - including the
2-3 weeks each spring/autumn when the US and Europe are out of step - are handled.

Sources / how each list was made (checked Nov 2026):
  US NFP        BLS Employment Situation archive (bls.gov/bls/news-release/empsit.htm),
                08:30 New York. Usually the first Friday, with the known exceptions
                kept as published (e.g. 2023-03-10, 2025-07-03 Thursday, the 2025
                shutdown: Sep report on 2025-11-20, Oct+Nov on 2025-12-16).
  US CPI        BLS CPI archive (bls.gov/bls/news-release/cpi.htm), 08:30 New York.
                2025: Sep CPI delayed to 10-24, Oct CPI cancelled, Nov CPI on 12-18.
  FOMC          federalreserve.gov FOMC calendars (statement days), statement 14:00
                and press conference 14:30 New York. (The 2025-08-22 framework
                statement is not a rate decision and is left out.)
  ECB           ECB monetary policy meeting calendar. Decision 13:45 CET and press
                conference 14:30 CET until June 2022; 14:15 / 14:45 CET from the
                21 July 2022 meeting (ECB press release 27 June 2022).
  BoE           MPC announcement dates, 12:00 London (Sep 2022 moved to 09-22).
  UK CPI        ONS release dates, 07:00 London (lower confidence: compiled from
                memory of the ONS calendar; a date may be off by a week).
  EZ flash HICP Eurostat flash estimate, 11:00 CET. Dates found by probing Eurostat's
                euro-indicator release pages (2-DDMMYYYY-ap); see EZ_FLASH_HICP.

Limitations: only these 7 event types. Not included: US retail sales, PPI, GDP,
ISM/PMIs, JOLTS, jobless claims, UK GDP/labour data, German CPI/ZEW/Ifo, central
bank speeches, unscheduled/emergency moves. The live feed (fxbot/news.py) has all
Forex Factory "High" events, so live blocks somewhat more often than this backtest.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

OUT = "data/news/high_impact_2021_2025.csv"
NY, LON, CET = ZoneInfo("America/New_York"), ZoneInfo("Europe/London"), ZoneInfo("Europe/Berlin")

NFP = """
2021-01-08 2021-02-05 2021-03-05 2021-04-02 2021-05-07 2021-06-04 2021-07-02 2021-08-06
2021-09-03 2021-10-08 2021-11-05 2021-12-03 2022-01-07 2022-02-04 2022-03-04 2022-04-01
2022-05-06 2022-06-03 2022-07-08 2022-08-05 2022-09-02 2022-10-07 2022-11-04 2022-12-02
2023-01-06 2023-02-03 2023-03-10 2023-04-07 2023-05-05 2023-06-02 2023-07-07 2023-08-04
2023-09-01 2023-10-06 2023-11-03 2023-12-08 2024-01-05 2024-02-02 2024-03-08 2024-04-05
2024-05-03 2024-06-07 2024-07-05 2024-08-02 2024-09-06 2024-10-04 2024-11-01 2024-12-06
2025-01-10 2025-02-07 2025-03-07 2025-04-04 2025-05-02 2025-06-06 2025-07-03 2025-08-01
2025-09-05 2025-11-20 2025-12-16
"""
US_CPI = """
2021-01-13 2021-02-10 2021-03-10 2021-04-13 2021-05-12 2021-06-10 2021-07-13 2021-08-11
2021-09-14 2021-10-13 2021-11-10 2021-12-10 2022-01-12 2022-02-10 2022-03-10 2022-04-12
2022-05-11 2022-06-10 2022-07-13 2022-08-10 2022-09-13 2022-10-13 2022-11-10 2022-12-13
2023-01-12 2023-02-14 2023-03-14 2023-04-12 2023-05-10 2023-06-13 2023-07-12 2023-08-10
2023-09-13 2023-10-12 2023-11-14 2023-12-12 2024-01-11 2024-02-13 2024-03-12 2024-04-10
2024-05-15 2024-06-12 2024-07-11 2024-08-14 2024-09-11 2024-10-10 2024-11-13 2024-12-11
2025-01-15 2025-02-12 2025-03-12 2025-04-10 2025-05-13 2025-06-11 2025-07-15 2025-08-12
2025-09-11 2025-10-24 2025-12-18
"""
FOMC = """
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
"""
ECB = """
2021-01-21 2021-03-11 2021-04-22 2021-06-10 2021-07-22 2021-09-09 2021-10-28 2021-12-16
2022-02-03 2022-03-10 2022-04-14 2022-06-09 2022-07-21 2022-09-08 2022-10-27 2022-12-15
2023-02-02 2023-03-16 2023-05-04 2023-06-15 2023-07-27 2023-09-14 2023-10-26 2023-12-14
2024-01-25 2024-03-07 2024-04-11 2024-06-06 2024-07-18 2024-09-12 2024-10-17 2024-12-12
2025-01-30 2025-03-06 2025-04-17 2025-06-05 2025-07-24 2025-09-11 2025-10-30 2025-12-18
"""
BOE = """
2021-02-04 2021-03-18 2021-05-06 2021-06-24 2021-08-05 2021-09-23 2021-11-04 2021-12-16
2022-02-03 2022-03-17 2022-05-05 2022-06-16 2022-08-04 2022-09-22 2022-11-03 2022-12-15
2023-02-02 2023-03-23 2023-05-11 2023-06-22 2023-08-03 2023-09-21 2023-11-02 2023-12-14
2024-02-01 2024-03-21 2024-05-09 2024-06-20 2024-08-01 2024-09-19 2024-11-07 2024-12-19
2025-02-06 2025-03-20 2025-05-08 2025-06-19 2025-08-07 2025-09-18 2025-11-06 2025-12-18
"""
UK_CPI = """
2021-01-20 2021-02-17 2021-03-24 2021-04-21 2021-05-19 2021-06-16 2021-07-14 2021-08-18
2021-09-15 2021-10-20 2021-11-17 2021-12-15 2022-01-19 2022-02-16 2022-03-23 2022-04-13
2022-05-18 2022-06-22 2022-07-20 2022-08-17 2022-09-14 2022-10-19 2022-11-16 2022-12-14
2023-01-18 2023-02-15 2023-03-22 2023-04-19 2023-05-24 2023-06-21 2023-07-19 2023-08-16
2023-09-20 2023-10-18 2023-11-15 2023-12-20 2024-01-17 2024-02-14 2024-03-20 2024-04-17
2024-05-22 2024-06-19 2024-07-17 2024-08-14 2024-09-18 2024-10-16 2024-11-20 2024-12-18
2025-01-15 2025-02-19 2025-03-26 2025-04-16 2025-05-21 2025-06-18 2025-07-16 2025-08-20
2025-09-17 2025-10-22 2025-11-19 2025-12-17
"""
EZ_FLASH_HICP = """
2021-01-07 2021-02-03 2021-03-02 2021-03-31 2021-04-30 2021-06-01 2021-06-30 2021-07-30
2021-08-31 2021-10-01 2021-10-29 2021-11-30 2022-01-07 2022-02-02 2022-03-02 2022-04-01
2022-04-29 2022-05-31 2022-07-01 2022-07-29 2022-08-31 2022-09-30 2022-10-31 2022-11-30
2023-01-06 2023-02-01 2023-03-02 2023-03-31 2023-05-02 2023-06-01 2023-06-30 2023-07-31
2023-08-31 2023-09-29 2023-10-31 2023-11-30 2024-01-05 2024-02-01 2024-03-01 2024-04-03
2024-04-30 2024-05-31 2024-07-02 2024-07-31 2024-08-30 2024-10-01 2024-10-31 2024-11-29
2025-01-07 2025-02-03 2025-03-03 2025-04-01 2025-05-02 2025-06-03 2025-07-01 2025-08-01
2025-09-02 2025-10-01 2025-10-31 2025-12-02
"""

ECB_NEW_TIMES_FROM = "2022-07-21"


def _dates(block):
    return [d for d in block.split() if d]


def _utc(day, hhmm, tz):
    h, m = map(int, hhmm.split(":"))
    y, mo, d = map(int, day.split("-"))
    return pd.Timestamp(datetime(y, mo, d, h, m, tzinfo=tz)).tz_convert("UTC")


def build():
    rows = []

    def add(block, hhmm, tz, cur, name):
        for d in _dates(block):
            rows.append((_utc(d, hhmm, tz), cur, name))

    add(NFP, "08:30", NY, "USD", "US Non-Farm Payrolls")
    add(US_CPI, "08:30", NY, "USD", "US CPI")
    add(FOMC, "14:00", NY, "USD", "FOMC rate decision")
    add(FOMC, "14:30", NY, "USD", "FOMC press conference")
    for d in _dates(ECB):
        new = d >= ECB_NEW_TIMES_FROM
        rows.append((_utc(d, "14:15" if new else "13:45", CET), "EUR", "ECB rate decision"))
        rows.append((_utc(d, "14:45" if new else "14:30", CET), "EUR", "ECB press conference"))
    add(BOE, "12:00", LON, "GBP", "BoE rate decision")
    add(UK_CPI, "07:00", LON, "GBP", "UK CPI")
    add(EZ_FLASH_HICP, "11:00", CET, "EUR", "Eurozone flash CPI")
    df = pd.DataFrame(rows, columns=["time", "currency", "event"]).sort_values("time")
    df["time"] = df["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return df.reset_index(drop=True)


def main():
    df = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        f.write("# High-impact news 2021-2025, times in UTC. Built by build_news_calendar.py\n"
                "# (official release dates, local release times converted to UTC; see that\n"
                "# script for sources and what is NOT included).\n")
        df.to_csv(f, index=False)
    print(f"wrote {len(df)} events to {OUT}")
    print(df.groupby("event").size().to_string())


if __name__ == "__main__":
    main()
