"""Backtest CRT, Candle Range Theory (fxbot/strategies/crt.py), with real costs at 1% risk.

    python run_crt.py

Markets: EURUSD, GBPUSD, XAUUSD, USDJPY (histdata 2021-25), NAS100 (Dukascopy 2021 - Nov 2026).
Variants: range candle + entry timeframe (daily on 1 h, daily on 15 min, 4-hour on 15 min) x
manipulation read on the candle close or intrabar x entry on a market structure shift or a fair
value gap x minimum reward/risk 0 or 1.5. Pass: PF >= 1.15 on 2021-25, >= 4 of 5 years up.
"""
import os
from multiprocessing import Pool

import pandas as pd

import run_fvg123 as F

COMBOS = {"D on 1h": ("D", "1h"), "D on 15m": ("D", "15min"), "4H on 15m": ("4H", "15min")}
_BARS = {}


def _init(markets):
    from fxbot.data import resample
    for m in markets:
        b1 = F._load(m)
        for tf in ("15min", "1h"):
            _BARS[(m, tf)] = resample(b1, tf)


def run_one(job):
    from fxbot.backtest import run_backtest
    from fxbot.strategies.crt import CRT
    mk, combo, mode, trig, rr = job
    htf, tf = COMBOS[combo]
    c = F.make_cfg(mk, dict(name="crt", htf=htf, mode=mode, trigger=trig, min_rr=rr))
    c["data"]["timeframe"] = tf
    t, _ = run_backtest(_BARS[(mk, tf)], c, strategy_cls=CRT)
    row = dict(market=mk, combo=combo, mode=mode, trigger=trig, min_rr=rr, trades=len(t))
    if not len(t):
        return row
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    yr = t.entry_time.dt.year
    h = t[yr <= 2025]
    row.update(trades_yr=round(len(h) / 5, 1), win=round((h.r_multiple > 0).mean() * 100),
               avgR=round(h.r_multiple.mean(), 3), pf=F._pf(h), R21_25=round(h.r_multiple.sum(), 1),
               yrs_up=int(sum(h[h.entry_time.dt.year == y].r_multiple.sum() > 0 for y in range(2021, 2026))),
               y26=round(t[yr == 2026].r_multiple.sum(), 1))
    row["PASS"] = bool(row["pf"] >= 1.15 and row["yrs_up"] >= 4 and (mk != "NAS100" or row["y26"] > 0))
    return row


def main():
    markets = [m for m in F.FILES if os.path.exists(F.FILES[m])]
    jobs = [(m, cb, mo, tr, rr) for m in markets for cb in COMBOS for mo in ("close", "intrabar")
            for tr in ("mss", "fvg") for rr in (0.0, 1.5)]
    print(f"{len(jobs)} runs ...", flush=True)
    with Pool(6, initializer=_init, initargs=(markets,)) as pool:
        rows = list(pool.imap_unordered(run_one, jobs))
    df = pd.DataFrame(rows).sort_values(["market", "combo", "mode", "trigger", "min_rr"])
    df.to_csv("results/crt.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
