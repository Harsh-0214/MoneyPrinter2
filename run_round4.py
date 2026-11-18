"""Strategy search, round 4 (Nov 18 2026): three families never tested here.

    python run_round4.py

E. Stock -> FX lead-lag (broker D1, 2000 - Nov 2026): when the S&P 500 rose (fell) more than 0.5%
   / 1% on the day, buy (sell) AUDJPY / USDJPY / AUDUSD at the same daily close, hold one day.
   (Risk-on / risk-off spills into the "risk" currencies with a lag - a documented idea.) Cost:
   3x the broker's spread (the daily close is the 17:00 NY rollover, when spreads are wide).
F. Turnaround Tuesday on US indices (broker D1, 2000 - Nov 2026): after a down Monday (or down
   more than 0.5%), buy at Monday's close, sell at Tuesday's close. 2x spread + 6%/yr financing.
G. London 4 pm fix reversal (histdata M1 2021-25 + broker M5 2026): the move from 15:30 to the
   16:00 London fix, faded from 16:00 to 16:30 / 17:00. Only moves bigger than the 20-day median.
   EURUSD, GBPUSD, USDJPY at the bots' spreads.
Pass (fixed before the run, as always): PF >= 1.15 over 2021-25 with >= 4 of 5 years up, 2026 not
negative; daily ideas must also be profitable 2000-20.
"""
import numpy as np
import pandas as pd

from run_round3 import load_daily, verdict

INDICES = ["SPX500", "NAS100", "US30"]


def part_e(d, cost):
    rows = []
    spx = d["SPX500"].close.pct_change()
    for fx in ("AUDJPY.", "USDJPY.", "AUDUSD."):
        r = d[fx].close.pct_change().shift(-1)                # next day's FX return
        j = spx.index.intersection(r.index)
        for thr in (0.005, 0.01):
            s = spx[j]
            side = np.where(s > thr, 1, np.where(s < -thr, -1, 0))
            t = pd.Series(side * r[j].to_numpy(), index=j)[side != 0] - 1.5 * cost[fx]
            rows.append(verdict(t.dropna(), f"E SPX {thr * 100:.1f}% day -> {fx} next day"))
    return rows


def part_f(d, cost):
    rows = []
    for s in INDICES:
        c = d[s].close
        r = c.pct_change()
        nxt = r.shift(-1)
        mon = c.index.dayofweek == 0
        for thr in (0.0, 0.005):
            m = mon & (r < -thr) & (pd.Series(c.index.dayofweek, index=c.index).shift(-1) == 1)
            t = (nxt[m] - cost[s] - 0.06 / 365).dropna()
            t.index = t.index + pd.Timedelta(days=1)
            rows.append(verdict(t, f"F {s} Turnaround Tuesday (Monday down > {thr * 100:.1f}%)"))
    return rows


def part_g():
    from fxbot.data import load_csv, resample
    rows = []
    spread = {"EURUSD": 1.4, "GBPUSD": 2.0, "USDJPY": 1.6}
    pip = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01}
    mt5sym = {"EURUSD": "EURUSD.", "GBPUSD": "GBPUSD.", "USDJPY": "USDJPY."}
    try:
        import MetaTrader5 as mt5
        from fxbot.data import server_ts_to_utc
        mt5.initialize()
        m26 = {}
        for s, ms in mt5sym.items():
            r = pd.DataFrame(mt5.copy_rates_from_pos(ms, mt5.TIMEFRAME_M5, 0, 99999))
            m26[s] = pd.Series(r.close.values, index=server_ts_to_utc(r.time.values)).sort_index()
        mt5.shutdown()
    except Exception:
        m26 = {}
    for s in spread:
        px = resample(load_csv(f"data/{s}_M1_histdata.csv", "UTC"), "5min").close
        if s in m26:
            px = pd.concat([px, m26[s][m26[s].index >= "2026-01-01"]])
        lon = px.copy()
        lon.index = lon.index.tz_convert("Europe/London")
        hm = lon.index.strftime("%H:%M")
        def at(h):
            x = lon[hm == h]
            x.index = x.index.normalize()
            return x[~x.index.duplicated()]
        p = pd.DataFrame({"a": at("15:25"), "f": at("15:55"), "x30": at("16:25"), "x60": at("16:55")}).dropna()
        pre = p.f - p.a                                       # 15:30 -> 16:00 (bars close 5 min later)
        med = pre.abs().rolling(20).median().shift(1)
        for ex in ("x30", "x60"):
            m = pre.abs() > med
            side = -np.sign(pre[m])
            pips = (p[ex][m] - p.f[m]) * side / pip[s] - spread[s]
            t = pips * pip[s] / p.f[m]                          # as a fraction of price
            t.index = t.index.tz_localize(None)
            rows.append(verdict(t.dropna(), f"G {s} fade the move into the 4pm fix, out {'16:30' if ex == 'x30' else '17:00'}"))
    return rows


def main():
    d, cost = load_daily(INDICES + ["AUDJPY.", "USDJPY.", "AUDUSD."])
    rows = part_e(d, cost) + part_f(d, cost) + part_g()
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 260)
    print(df.to_string(index=False))
    print(f"\nPASS: {int(df.PASS.fillna(False).sum())} of {len(df)}")
    df.to_csv("results/round4.csv", index=False)


if __name__ == "__main__":
    main()
