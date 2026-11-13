"""Build data/cot/cot.csv: weekly CFTC Commitments of Traders (legacy, futures only) for the
markets the bot trades, from the public yearly files at cftc.gov (download them first):

    for y in 1986_2016 2017 ... 2026: https://www.cftc.gov/files/dea/history/deacot<y>.zip
    python fetch_cot.py

Columns: report_date (Tuesday positions), release (Friday 15:30 New York, in UTC), market,
spec_long/short (non-commercial), comm_long/short, small_long/short, open_interest.
Positions are in FUTURES terms: long = long the foreign currency (or gold) vs USD.
"""
import glob
import zipfile

import pandas as pd

CODES = {"099741": "EUR", "096742": "GBP", "097741": "JPY", "232741": "AUD",
         "090741": "CAD", "092741": "CHF", "088691": "XAU"}
COLS = {"As of Date in Form YYYY-MM-DD": "report_date", "CFTC Contract Market Code": "code",
        "Noncommercial Positions-Long (All)": "spec_long", "Noncommercial Positions-Short (All)": "spec_short",
        "Commercial Positions-Long (All)": "comm_long", "Commercial Positions-Short (All)": "comm_short",
        "Nonreportable Positions-Long (All)": "small_long", "Nonreportable Positions-Short (All)": "small_short",
        "Open Interest (All)": "open_interest"}


def main():
    frames = []
    for z in sorted(glob.glob("data/cot/deacot*.zip")):
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                df = pd.read_csv(zf.open(n), dtype={"CFTC Contract Market Code": str}, low_memory=False)
                df.columns = [c.strip() for c in df.columns]
                df = df[list(COLS)].rename(columns=COLS)
                df["code"] = df["code"].str.strip()
                frames.append(df[df["code"].isin(CODES)])
    d = pd.concat(frames, ignore_index=True)
    d["market"] = d["code"].map(CODES)
    d["report_date"] = pd.to_datetime(d["report_date"])
    d = d.drop_duplicates(["market", "report_date"]).sort_values(["market", "report_date"])
    # published Friday 15:30 New York for the Tuesday before (holidays delay it; +3 days is the rule)
    rel = (d["report_date"] + pd.Timedelta(days=3, hours=15, minutes=30)).dt.tz_localize("America/New_York")
    d["release"] = rel.dt.tz_convert("UTC")
    d = d[d["report_date"] >= "2000-01-01"].drop(columns="code")
    d.to_csv("data/cot/cot.csv", index=False)
    print(d.groupby("market").report_date.agg(["count", "min", "max"]))


if __name__ == "__main__":
    main()
