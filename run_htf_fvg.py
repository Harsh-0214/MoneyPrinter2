"""Fair value gaps on HIGHER timeframes (1 h / 4 h), the one FVG angle not yet tested.

    python run_htf_fvg.py

Earlier FVG tests (all rejected): 5 / 15-min FVG + IFVG retests (run_smc.py), the daily-FVG
"1-2-3" model on 1-3 min bars (run_fvg123.py), CRT + FVG (run_crt_fvg.py). Here the same strict
fvg / ifvg rules from fxbot/strategies/smc.py run on 1-hour and 4-hour candles, either closed at
21:00 London (intraday) or held until stop / target (hold_overnight). x trend filter on/off x
target 2R / 3R. Markets: EURUSD, GBPUSD, XAUUSD, USDJPY (histdata 2021-25), NAS100 (Dukascopy
2021 - Nov 2026). Real costs, 1% risk.
Pass (fixed before the run, as in every earlier test): PF >= 1.15 on 2021-25 and >= 4 of 5 years up.
"""
import os
from multiprocessing import Pool

import pandas as pd

import run_fvg123 as F

_BARS = {}
TFS = ("1h", "4h")


def _init(markets):
    from fxbot.data import resample
    from run_validate import _bars
    for m in markets:
        one = F._load(m) if m == "NAS100" else None
        for tf in TFS:
            _BARS[(m, tf)] = resample(one, tf) if m == "NAS100" else _bars(F.FILES[m], "UTC", tf)


def run_one(job):
    from fxbot.backtest import run_backtest
    from fxbot.strategies.smc import SMC
    mk, setup, tf, trend, rr, hold = job
    c = F.make_cfg(mk, dict(name="smc", setup=setup, trend_filter=trend, rr=rr, daily_ema_period=50,
                            hold_overnight=hold, zone_bars=60 if tf == "1h" else 30, max_per_day=1))
    c["data"]["timeframe"] = tf
    t, _ = run_backtest(_BARS[(mk, tf)], c, strategy_cls=SMC)
    row = dict(setup=setup, market=mk, tf=tf, trend=trend, rr=rr, hold=hold, trades=len(t))
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
               y26=round(t[yr == 2026].r_multiple.sum(), 1) if mk == "NAS100" else None)
    row["PASS"] = bool(row["pf"] >= 1.15 and row["yrs_up"] >= 4)
    return row


def main():
    markets = [m for m in F.FILES if os.path.exists(F.FILES[m])]
    jobs = [(m, s, tf, tr, rr, hold) for s in ("fvg", "ifvg") for m in markets for tf in TFS
            for tr in (False, True) for rr in (2.0, 3.0) for hold in (False, True)]
    print(f"{len(jobs)} runs ...", flush=True)
    rows = []
    with Pool(6, initializer=_init, initargs=(markets,)) as pool:
        for i, r in enumerate(pool.imap_unordered(run_one, jobs), 1):
            rows.append(r)
            if i % 40 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    df = pd.DataFrame(rows).sort_values(["setup", "market", "tf", "trend", "rr", "hold"])
    os.makedirs("results", exist_ok=True)
    df.to_csv("results/htf_fvg.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(df.to_string(index=False))
    print(f"\nPASS: {int(df.PASS.fillna(False).sum())} of {len(df)}; median PF by setup/tf:")
    print(df.groupby(["setup", "tf", "hold"]).pf.median().round(2).to_string())


if __name__ == "__main__":
    main()
