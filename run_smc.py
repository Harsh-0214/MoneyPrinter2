"""Backtest the ICT / "smart money" setups (fxbot/strategies/smc.py) on 5 markets, real costs, 1% risk.

    python run_smc.py                 # 11 setups x 5 markets x 5/15-min x trend filter on/off (~1 h)
    python run_smc.py --setups ob,ote

Markets: EURUSD, GBPUSD, XAUUSD, USDJPY (histdata 2021-25), NAS100 (Dukascopy 2021 - Nov 2026).
Pass (fixed before the run): PF >= 1.15 on 2021-25 and >= 4 of 5 years up (NAS100: 2026 up too).
"""
import argparse
import os
from multiprocessing import Pool

import pandas as pd

import run_fvg123 as F
from fxbot.strategies.smc import SETUPS

_BARS = {}


def _init(markets):
    from fxbot.data import resample
    from run_validate import _bars
    for m in markets:
        for tf in ("5min", "15min"):
            _BARS[(m, tf)] = resample(F._load(m), tf) if m == "NAS100" else _bars(F.FILES[m], "UTC", tf)


def run_one(job):
    from fxbot.backtest import run_backtest
    from fxbot.strategies.smc import SMC
    mk, setup, tf, trend, rr = job
    c = F.make_cfg(mk, dict(name="smc", setup=setup, trend_filter=trend, rr=rr, daily_ema_period=50))
    c["data"]["timeframe"] = tf
    t, _ = run_backtest(_BARS[(mk, tf)], c, strategy_cls=SMC)
    row = dict(setup=setup, market=mk, tf=tf, trend_filter=trend, rr=rr, trades=len(t))
    if not len(t):
        return row
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    yr = t.entry_time.dt.year
    h = t[yr <= 2025]
    if not len(h):
        return row
    row.update(trades_yr=round(len(h) / 5, 1), win=round((h.r_multiple > 0).mean() * 100),
               avgR=round(h.r_multiple.mean(), 3), pf=F._pf(h), R21_25=round(h.r_multiple.sum(), 1),
               yrs_up=int(sum(h[h.entry_time.dt.year == y].r_multiple.sum() > 0 for y in range(2021, 2026))),
               y26=round(t[yr == 2026].r_multiple.sum(), 1))
    row["PASS"] = bool(row["pf"] >= 1.15 and row["yrs_up"] >= 4 and (mk != "NAS100" or row["y26"] > 0))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setups", default=",".join(SETUPS))
    ap.add_argument("--markets", default=",".join(F.FILES))
    ap.add_argument("--rr", default="2")
    ap.add_argument("--out", default="results/smc.csv")
    a = ap.parse_args()
    markets = [m for m in a.markets.split(",") if os.path.exists(F.FILES[m])]
    jobs = [(m, s, tf, tr, float(rr)) for s in a.setups.split(",") for m in markets for tf in ("5min", "15min")
            for tr in (False, True) for rr in a.rr.split(",")]
    print(f"{len(jobs)} runs ...", flush=True)
    rows = []
    with Pool(6, initializer=_init, initargs=(markets,)) as pool:
        for i, r in enumerate(pool.imap_unordered(run_one, jobs), 1):
            rows.append(r)
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    df = pd.DataFrame(rows).sort_values(["setup", "market", "tf", "trend_filter"])
    df.to_csv(a.out, index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
