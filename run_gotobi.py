"""Gotobi: does USDJPY rise into the Tokyo 9:55 fix on the 5th/10th/15th/20th/25th/30th?

    python run_gotobi.py [--spread 1.6]

Japanese importers settle on "gotobi" days (dates divisible by 5, plus month end; a weekend date
moves to the Friday before) and buy dollars for the 9:55 Tokyo (00:55 UTC) fix. Known flow effect;
never tested here. Rules: BUY at 22:00 / 23:00 / 00:00 UTC, SELL at 00:55 UTC; and the reverse
(SELL 00:55, BUY back 02:00 / 03:00) after the fix. Each against the same window on ordinary
weekdays (control). Cost: the spread once per trade (histdata bars are BID). Japanese holidays
are not removed (a few fake gotobi days a year: makes the test slightly harder to pass).
Data: histdata USDJPY M1 2021-25 (UTC) + the broker's M5 2026 if MT5 is open.
Pass (fixed before the run): PF >= 1.15 on 2021-25, >= 4 of 5 years up, 2026 not negative.
"""
import argparse

import numpy as np
import pandas as pd


def gotobi_dates(start, end):
    """JST calendar dates that are gotobi business days."""
    days = pd.date_range(start, end, freq="D")
    out = set()
    for d in days:
        last = (d + pd.offsets.MonthEnd(0)).day
        if d.day % 5 == 0 or d.day == last:
            g = d
            while g.dayofweek >= 5:          # Sat/Sun -> the Friday before
                g -= pd.Timedelta(days=1)
            out.add(g.normalize())
    return out


def window_returns(px, gdays, t_in, t_out, side):
    """px: close prices indexed by UTC time. Returns a frame per JST business day: pips, gotobi flag."""
    rows = []
    idx = px.index
    for d in pd.date_range(idx[0].normalize(), idx[-1].normalize(), freq="B"):
        fix = pd.Timestamp(d.date(), tz="UTC")          # 00:55 UTC on d = 09:55 JST on d
        tin = pd.Timedelta(t_in)
        a = fix + tin - (pd.Timedelta(days=1) if tin > pd.Timedelta("12h") else pd.Timedelta(0))
        b = fix + pd.Timedelta(t_out)
        ia, ib = idx.searchsorted(a, "right") - 1, idx.searchsorted(b, "right") - 1
        if ia < 0 or ib < 0 or a - idx[ia] > pd.Timedelta("10min") or b - idx[ib] > pd.Timedelta("10min"):
            continue                                      # no price near one of the two times
        rows.append(dict(day=d, gotobi=d.tz_localize(None).normalize() in gdays if d.tzinfo else d.normalize() in gdays, pips=(px.iloc[ib] - px.iloc[ia]) * side / 0.01))
    return pd.DataFrame(rows)


def stats(p, spread):
    net = p - spread
    gw, gl = net[net > 0].sum(), -net[net <= 0].sum()
    return dict(n=len(net), gross=round(p.mean(), 2), net=round(net.mean(), 2), win=round((net > 0).mean() * 100),
                pf=round(gw / gl, 2) if gl > 0 else np.inf, tot=round(net.sum(), 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spread", type=float, default=1.6)
    a = ap.parse_args()
    from fxbot.data import load_csv, resample
    px = resample(load_csv("data/USDJPY_M1_histdata.csv", "UTC"), "5min").close
    sources = {"2021-25": px}
    try:
        import MetaTrader5 as mt5
        from fxbot.data import server_ts_to_utc
        if mt5.initialize():
            r = pd.DataFrame(mt5.copy_rates_range("USDJPY.", mt5.TIMEFRAME_M5,
                                                  pd.Timestamp("2025-12-28").to_pydatetime(), pd.Timestamp.now().to_pydatetime()))
            mt5.shutdown()
            if len(r):
                s = pd.Series(r.close.values, index=server_ts_to_utc(r.time.values))
                sources["2026"] = s[s.index >= "2026-01-01"].sort_index()
    except Exception as e:
        print("no MT5 2026 data:", e)
    gd = gotobi_dates("2020-12-01", "2026-12-31")
    rules = [("BUY 22:00 -> SELL 00:55", "22:00:00", "00:55:00", 1),
             ("BUY 23:00 -> SELL 00:55", "23:00:00", "00:55:00", 1),
             ("BUY 00:00 -> SELL 00:55", "00:00:00", "00:55:00", 1),
             ("SELL 00:55 -> BUY 02:00", "00:55:00", "02:00:00", -1),
             ("SELL 00:55 -> BUY 03:00", "00:55:00", "03:00:00", -1)]
    rows = []
    for name, ti, to, side in rules:
        for src, p in sources.items():
            w = window_returns(p, gd, ti, to, side)
            if w.empty:
                continue
            for flag, g in w.groupby("gotobi"):
                st = stats(g.pips, a.spread)
                row = dict(rule=name, days="gotobi" if flag else "ordinary", data=src, **st)
                if src == "2021-25":
                    yrs = g.assign(y=g.day.dt.year).groupby("y").pips.apply(lambda x: (x - a.spread).sum())
                    row["yrs_up"] = int((yrs > 0).sum())
                    row["by_year"] = " ".join(f"{v:+.0f}" for v in yrs.values)
                rows.append(row)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(f"spread {a.spread} pips per trade; pips are net of it (gross = before)")
    print(df.to_string(index=False))
    df.to_csv("results/gotobi.csv", index=False)


if __name__ == "__main__":
    main()
