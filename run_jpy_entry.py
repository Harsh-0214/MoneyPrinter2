"""Does the USDJPY breakout enter too late? (Nov 20 2026)

    python run_jpy_entry.py

Nov 19 the bot bought 159.898, about 52 pips above the day's open, after a 15-min candle closed
above the level (open + 0.9 x yesterday's range). Two ways to get in earlier, each tested on the
LIVE rules (05:00-12:00 London, no trend filter, 2 tries a day, breakeven at +1R, 21:00 exit,
stop 0.5 x yesterday's range):
  * a smaller k (the level sits closer to the open): 0.5 / 0.6 / 0.7 / 0.8 vs 0.9 (live) / 1.0;
  * 5-min candles instead of 15-min (the close beyond the level is confirmed sooner).
Same pass rule as always: PF >= 1.15 and >= 4/5 years up on 2021-25 (histdata), 2026 PF >= 1.0
(broker feed: M15 for 15-min variants, M5 2026 for 5-min variants).
"""
import pandas as pd

import run_more_trades as rmt

V = rmt.VBO
rmt.VARIANTS.clear()
for k in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
    tag = " (live)" if k == 0.9 else ""
    rmt.VARIANTS[f"15min k{k}{tag}"] = ("USDJPY", "15min", [rmt._v(V, k=k)], 2, "M15")
    rmt.VARIANTS[f"5min k{k}"] = ("USDJPY", "5min", [rmt._v(V, k=k)], 2, "M5_2026")


def main():
    from multiprocessing import Pool
    names = list(rmt.VARIANTS)
    with Pool(6) as pool:
        rows = pool.map(rmt._run, names)
    df = pd.DataFrame(rows)
    cols = ["name", "trades_yr", "pf", "avgR", "yrs_up", "y21", "y22", "y23", "y24", "y25",
            "R21_23", "R24_25", "n26", "R26", "pf26", "PASS"]
    pd.set_option("display.width", 250)
    print(df[cols].to_string(index=False))
    df.to_csv("results/jpy_entry.csv", index=False)


if __name__ == "__main__":
    main()
