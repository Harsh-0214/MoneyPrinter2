"""Backtest the ICT "1-2-3" fair-value-gap strategy (fxbot/strategies/fvg123.py) on 1-minute data.

    python run_fvg123.py                     # every market x variant (~30-60 min, 6 workers)
    python run_fvg123.py --markets NAS100 --show-day 2026-11-04

Markets: EURUSD, GBPUSD, XAUUSD, USDJPY (histdata M1 2021-25), NAS100 (Dukascopy M1 2021 - Nov 2026,
download_dukascopy.py --instrument USATECHIDXUSD --point 1000). Real spreads + slippage, 1% risk.
Variants: target (15-min FVG as in the video, 15-min FVG but only if >= 1R, fixed 2R / 3R, time exit
only) x session (all day / active hours) x confirmation (1-2-3 as in the video / 1-2-3-5 stricter).
Pass (decided before the run, same bar as every other test): PF >= 1.15 on 2021-25, profitable in
>= 4 of 5 years, and (NAS100) 2026 profitable.
"""
import argparse
import copy
import os
from multiprocessing import Pool

import pandas as pd
import yaml

BASE = yaml.safe_load(open("config.yaml"))
_P = {p["symbol"]: p for p in BASE["pairs"]}
FILES = {"EURUSD": "data/EURUSD_M1_histdata.csv", "GBPUSD": "data/GBPUSD_M1_histdata.csv",
         "XAUUSD": "data/XAUUSD_M1_histdata.csv", "USDJPY": "data/USDJPY_M1_histdata.csv",
         "NAS100": "data/NAS100_M1_duka.csv"}
SESSIONS = {"all day": ["00:00", "23:59"],
            "active": {"NAS100": ["14:30", "20:00"], "default": ["07:00", "17:00"]}}
TARGETS = ["fvg15", "fvg15_min1r", "2r", "3r", "none"]
CONFIRM = {"1-2-3": [1, 2, 3], "1-2-3-5": [1, 2, 3, 5]}
_BARS = {}


def _load(mk):
    from run_validate import _bars
    b = _bars(FILES[mk], "UTC", "1min")
    if mk == "NAS100":
        # Dukascopy pads closed hours (weekends, holidays) with flat bars: drop them, or the
        # weekend would become a fake zero-range "day" and create false daily gaps
        flat = (b.high == b.low) & (b.open == b.close) & (b.open == b.high)
        ny = b.index.tz_convert("America/New_York")
        weekend = (ny.dayofweek == 5) | ((ny.dayofweek == 4) & (ny.hour >= 17)) | ((ny.dayofweek == 6) & (ny.hour < 18))
        b = b[~(flat | weekend)]
    return b


def _init(markets):
    for m in markets:
        _BARS[m] = _load(m)


def make_cfg(mk, spec):
    from fxbot.backtest import pair_config
    if mk == "NAS100":
        pe = {"symbol": "NAS100", "spread_pips": 3.0, "instrument": {"pip": 1.0, "min_units": 1},
              "costs": {"rollover_spread_pips": 0.0, "slippage_pips": 0.5, "swap_long_per_lot": 0.0,
                        "swap_short_per_lot": 0.0}, "data": {"path": FILES[mk], "source_tz": "UTC"}}
    else:
        pe = _P[mk]
    c = pair_config(BASE, pe)
    c["smt"] = {}
    c["data"]["timeframe"] = "1min"
    c["account"]["starting_equity"] = 1_000_000
    c["risk"]["risk_per_trade_pct"] = 1.0
    c["risk"]["max_leverage"] = 1000
    if mk == "NAS100":
        c["risk"]["news_currencies"] = ["USD"]
    c["strategy"] = dict(spec)
    c["slot_max_trades"] = 3
    return c


def _pf(t):
    gl = -t.pnl[t.pnl <= 0].sum() if len(t) else 0
    return round(t.pnl[t.pnl > 0].sum() / gl, 2) if gl > 0 else float("inf")


def run_one(job):
    from fxbot.backtest import run_backtest
    from fxbot.strategies.fvg123 import FVG123
    mk, target, sess, conf = job
    s = SESSIONS[sess]
    if isinstance(s, dict):
        s = s.get(mk, s["default"])
    spec = dict(name="fvg123", target=target, session=s, timeframes=CONFIRM[conf],
                exit_time="21:00", window_min=30)
    c = make_cfg(mk, spec)
    t, _ = run_backtest(_BARS[mk], c, strategy_cls=FVG123)
    row = dict(market=mk, target=target, session=sess, confirm=conf, trades=len(t))
    if not len(t):
        return row, t
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    yr = t.entry_time.dt.year
    h = t[yr <= 2025]
    row.update(trades_yr=round(len(h) / 5, 1), win=round((h.r_multiple > 0).mean() * 100),
               avgR=round(h.r_multiple.mean(), 3), pf=_pf(h), R21_25=round(h.r_multiple.sum(), 1),
               yrs_up=int(sum(h[h.entry_time.dt.year == y].r_multiple.sum() > 0 for y in range(2021, 2026))))
    row.update({f"y{y % 100}": round(t[yr == y].r_multiple.sum(), 1) for y in range(2021, 2027)})
    row["PASS"] = bool(row["pf"] >= 1.15 and row["yrs_up"] >= 4 and (mk != "NAS100" or row["y26"] > 0))
    t.insert(0, "market", mk)
    return row, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default=",".join(FILES))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--show-day", default=None, help="print the trades of this date (e.g. 2026-11-04)")
    a = ap.parse_args()
    markets = [m for m in a.markets.split(",") if os.path.exists(FILES[m])]
    jobs = [(m, tg, se, co) for m in markets for tg in TARGETS for se in SESSIONS for co in CONFIRM]
    print(f"{len(jobs)} runs on {markets} ...", flush=True)
    rows, trades = [], []
    with Pool(a.workers, initializer=_init, initargs=(markets,)) as pool:
        for row, t in pool.imap_unordered(run_one, jobs):
            rows.append(row)
            if len(t):
                trades.append(t.assign(target=row["target"], session=row["session"], confirm=row["confirm"]))
            print(f"  {row['market']:<7} {row['target']:<12} {row['session']:<8} {row['confirm']:<8} "
                  f"{row.get('trades_yr', 0):6.1f}/yr win {row.get('win', 0)}% PF {row.get('pf', 0)} "
                  f"avgR {row.get('avgR', 0):+.3f} yrs {row.get('yrs_up', 0)}/5 R {row.get('R21_25', 0):+.1f} "
                  f"2026 {row.get('y26', 0):+.1f}" + ("  PASS" if row.get("PASS") else ""), flush=True)
    df = pd.DataFrame(rows).sort_values(["market", "target", "session", "confirm"])
    df.to_csv("results/fvg123.csv", index=False)
    if trades:
        pd.concat(trades).to_csv("results/fvg123_trades.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(df.to_string(index=False))
    if a.show_day and trades:
        tt = pd.concat(trades)
        d = tt[tt.entry_time.dt.tz_convert("America/New_York").dt.date.astype(str) == a.show_day]
        print(f"\nTrades on {a.show_day} (New York date):")
        print(d[["market", "target", "session", "confirm", "entry_time", "side", "entry_price", "exit_time",
                 "exit_price", "exit_reason", "r_multiple"]].to_string(index=False))


if __name__ == "__main__":
    main()
