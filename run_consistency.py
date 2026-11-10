"""Year-by-year consistency grid for a single strategy, on every pair, all years.

    python run_consistency.py tiny_range_fade
    python run_consistency.py london_close_reversal
    python run_consistency.py london_close_reversal --spread 1.5

Each grid point runs the strategy ALONE (no other strategies) on each pair.
Score = sum of R per (pair, year). A config "always works" when every
pair-year is positive. Results -> results/consistency_<strategy>.csv
"""
import argparse
import copy
import itertools
import os
from multiprocessing import Pool

import pandas as pd
import yaml

GRIDS = {
    "tiny_range_fade": {
        "mode": ["immediate", "deferred"],
        "max_range_pips": [10, 12, 15, 20],
        "target": ["mid", "opposite"],
        "min_stop_pips": [5, 8, 12],
    },
    "london_close_reversal": {
        "entry_time": ["15:00", "15:30", "16:05", "16:30"],
        "min_move_pips": [30, 45, 60, 80],
        "target_frac": [0.25, 0.38, 0.5],
        "near_extreme_pips": [None, 10],
    },
    "london_close_follow": {
        "entry_time": ["15:00", "15:30", "16:05", "16:30"],
        "min_move_pips": [30, 45, 60, 80],
        "stop_pips": [15, 25, 35],
        "target_rr": [1.5, None],
        "near_extreme_pips": [None, 10],
    },
    "trend_donchian": {
        "entry_days": [20, 40, 55, 100],
        "exit_days": [None, 10, 20],
        "stop_atr": [2.0, 3.0, 4.0],
    },
    "key_levels": {
        "mode": ["bounce", "break"],
        "levels": ["pd+pw", "swing", "pd+pw+swing"],
        "min_touches": [2, 3],
        "target": ["rr", "next"],
        "entry_end": ["12:00", "15:00"],
    },
    "trend_turtle": {
        "entry_days": [20, 40, 55, 100],
        "exit_days": [10, 20, 40],
        "stop_atr": [2.0, 4.0, 6.0],
    },
    "trend_ema": {
        "ema_fast": [20, 50],
        "ema_slow": [100, 200],
        "stop_atr": [2.0, 3.0, 4.0],
    },
}
SLOT = {"tiny_range_fade": "morning", "london_close_reversal": "afternoon",
        "london_close_follow": "afternoon", "trend_donchian": "morning", "trend_ema": "morning", "trend_turtle": "morning", "key_levels": "afternoon"}
TIMEFRAME = {"trend_donchian": "1h", "trend_ema": "1h", "trend_turtle": "1h"}   # default: the cached 5min bars
# grid name -> (strategy name, fixed params)
ALIAS = {"london_close_follow": ("london_close_reversal", {"direction": "follow"}),
         "trend_donchian": ("trend_follow", {"signal": "donchian"}),
         "trend_ema": ("trend_follow", {"signal": "ema", "exit_days": None}),
         "trend_turtle": ("trend_follow", {"signal": "donchian", "trail": False})}

_BARS = None
_CFG = None


def _init(cfg):
    global _BARS, _CFG
    from run_validate import load_pairs
    _CFG = cfg
    _BARS = load_pairs(cfg)


def _one(args):
    name, params = args
    from fxbot.backtest import run_backtest
    c = copy.deepcopy(_CFG)
    c["smt"] = {}
    c["strategies"] = {"morning": [], "afternoon": []}
    real, fixed = ALIAS.get(name, (name, {}))
    c["strategies"][SLOT[name]] = [dict(name=real, **fixed, **params)]
    out = []
    tf = TIMEFRAME.get(name)
    for sym, bars in _BARS.items():
        if tf:
            from fxbot.data import resample
            cols = [x for x in ("open", "high", "low", "close", "data_spread_pips") if x in bars]
            bars = resample(bars[cols], tf)
        t, _ = run_backtest(bars, c)
        if len(t) == 0:
            continue
        t["year"] = pd.to_datetime(t.entry_time).dt.year
        for y, g in t.groupby("year"):
            out.append(dict(params, symbol=sym, year=y, n=len(g), R=g.r_multiple.sum(),
                            win=(g.pnl > 0).mean()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy", choices=list(GRIDS))
    ap.add_argument("--spread", type=float, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-swap", action="store_true", help="zero overnight financing")
    args = ap.parse_args()
    cfg = yaml.safe_load(open("config.yaml"))
    if args.spread:
        cfg["costs"]["spread_pips"] = args.spread
    if args.no_swap:
        cfg["costs"]["swap_long_per_lot"] = cfg["costs"]["swap_short_per_lot"] = 0.0
    grid = GRIDS[args.strategy]
    keys = list(grid)
    jobs = [(args.strategy, dict(zip(keys, v))) for v in itertools.product(*grid.values())]
    print(f"{len(jobs)} configs x pairs ...", flush=True)
    rows = []
    with Pool(args.workers, initializer=_init, initargs=(cfg,)) as pool:
        for i, r in enumerate(pool.imap_unordered(_one, jobs), 1):
            rows += r
            if i % 10 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    df = pd.DataFrame(rows)
    df[keys] = df[keys].astype(str)
    suffix = f"_sp{args.spread}" if args.spread else ""
    os.makedirs("results", exist_ok=True)
    df.to_csv(f"results/consistency_{args.strategy}{suffix}.csv", index=False)

    py = df.pivot_table(index=keys, columns=["symbol", "year"], values="R", aggfunc="sum").fillna(0)
    summ = pd.DataFrame({
        "pos_pair_years": (py > 0).sum(axis=1),
        "of": py.shape[1],
        "worst_R": py.min(axis=1).round(1),
        "total_R": py.sum(axis=1).round(1),
        "trades": df.groupby(keys).n.sum(),
    })
    summ["avgR"] = (summ.total_R / summ.trades).round(3)
    if "EURUSD" in py.columns.get_level_values(0):
        eur = py["EURUSD"]
        summ["eur_pos_yrs"] = (eur > 0).sum(axis=1)
        summ["eur_R"] = eur.sum(axis=1).round(1)
        summ["eur_R_23_24"] = eur[[c for c in eur.columns if c in (2023, 2024)]].sum(axis=1).round(1)
    summ = summ.sort_values(["pos_pair_years", "worst_R"], ascending=False)
    pd.set_option("display.width", 220)
    print(summ.head(25).to_string())
    best = summ.index[0]
    print("\nbest config per pair-year R:")
    print(py.loc[best].unstack(0).round(2).to_string())


if __name__ == "__main__":
    main()
