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
}
SLOT = {"tiny_range_fade": "morning", "london_close_reversal": "afternoon",
        "london_close_follow": "afternoon"}
# grid name -> (strategy name, fixed params)
ALIAS = {"london_close_follow": ("london_close_reversal", {"direction": "follow"})}

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
    for sym, bars in _BARS.items():
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
    args = ap.parse_args()
    cfg = yaml.safe_load(open("config.yaml"))
    if args.spread:
        cfg["costs"]["spread_pips"] = args.spread
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
    summ = summ.sort_values(["pos_pair_years", "worst_R"], ascending=False)
    pd.set_option("display.width", 220)
    print(summ.head(25).to_string())
    best = summ.index[0]
    print("\nbest config per pair-year R:")
    print(py.loc[best].unstack(0).round(2).to_string())


if __name__ == "__main__":
    main()
