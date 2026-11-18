"""IBS on US indices with a realistic decision time (Nov 18 2026, follow-up to run_round3.py).

    python run_ibs_realistic.py

The broker's daily candle closes at 17:00 New York (rollover: wide spread, CFD halted 17-18).
Here the day is 18:00 NY (previous evening) to 16:00 NY (US cash close) and everything is decided
on the 16:00 price: IBS = (16:00 price - day low) / (day high - day low) using bars up to 16:00.
Buy at 16:00 when IBS < 0.2 (optionally above the 200-day average of 16:00 prices); sell at a
later 16:00: the next day, or the first day the 16:00 price is above the previous day's high
(max 5 days). Broker H1 bars 2000-2026 (hours missing in early years are skipped); NAS100 also
on Dukascopy M1 2021-26 (an independent feed). Costs: 2x the broker spread + 6%/yr financing.
"""
import sys

import numpy as np
import pandas as pd

from run_round3 import verdict, FINANCE

SPREAD = {"SPX500": 0.6, "NAS100": 3.0, "US30": 6.6}


def daily_from_intraday(b):
    """b: OHLC indexed by UTC. Returns per NY trading day: high, low (18:00 prev -> 16:00), c16."""
    ny = b.copy()
    ny.index = ny.index.tz_convert("America/New_York")
    end = ny.index + pd.Timedelta(hours=1) if len(ny) and (ny.index[1] - ny.index[0]) >= pd.Timedelta("1h") else ny.index
    # assign each bar to the trading day it belongs to: bars from 18:00 belong to the next day
    day = (ny.index + pd.Timedelta(hours=6)).normalize()
    keep = (ny.index.hour < 16) | (ny.index.hour >= 18)
    ny, day = ny[keep], day[keep]
    g = ny.groupby(day)
    d = pd.DataFrame({"high": g.high.max(), "low": g.low.min(), "c16": g.close.last(), "n": g.close.size(),
                      "last_hour": g.apply(lambda x: x.index[-1].hour)})
    return d[(d.last_hour == 15) & (d.n >= 5)]            # the 15:00-16:00 bar must exist


def trades(d, spread, trend, exit_rule):
    c, h, lo, idx = d.c16.to_numpy(), d.high.to_numpy(), d.low.to_numpy(), d.index
    ibs = (c - lo) / np.where(h > lo, h - lo, np.nan)
    sma = pd.Series(c).rolling(200).mean().to_numpy()
    out, i, n = [], 200, len(d)
    while i < n - 1:
        if ibs[i] < 0.2 and (not trend or c[i] > sma[i]):
            j = i + 1
            if exit_rule == "high":
                while j < n - 1 and j - i < 5 and c[j] <= h[j - 1]:
                    j += 1
            out.append((idx[j].tz_localize(None), c[j] / c[i] - 1 - 2 * spread / c[i] - FINANCE * (idx[j] - idx[i]).days))
            i = j
        else:
            i += 1
    return pd.Series(dict(out)).sort_index()


def main():
    import MetaTrader5 as mt5
    from fxbot.data import server_ts_to_utc
    mt5.initialize()
    feeds = {}
    for s in SPREAD:
        r = pd.DataFrame(mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 99999))
        b = r[["open", "high", "low", "close"]].copy()
        b.index = server_ts_to_utc(r.time.values)
        feeds[(s, "broker H1")] = b[b.index.notna()].sort_index()
    mt5.shutdown()
    try:
        import run_fvg123 as F
        from fxbot.data import resample
        feeds[("NAS100", "Dukascopy M1->1h")] = resample(F._load("NAS100"), "1h")
    except Exception as e:
        print("no Dukascopy NAS100:", e)
    rows = []
    for (s, feed), b in feeds.items():
        d = daily_from_intraday(b)
        cover = d.groupby(d.index.year).size()
        print(f"{s} {feed}: {len(d)} usable days; per year: {cover.to_dict()}")
        for trend in (False, True):
            for ex in ("next day", "high"):
                rows.append(dict(feed=feed, **verdict(trades(d, SPREAD[s], trend, ex),
                                                      f"{s} IBS<0.2{' >200d' if trend else ''} exit {ex}")))
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 260)
    print(df.to_string(index=False))
    df.to_csv("results/ibs_realistic.csv", index=False)


if __name__ == "__main__":
    main()
