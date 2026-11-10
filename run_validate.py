"""Walk-forward + robustness validation for the multi-pair config.

    python run_validate.py                      # walk-forward + per-year + robustness
    python run_validate.py --only walk          # just the in/out-of-sample split
    python run_validate.py --only robust        # just the parameter / cost stress tests

Loads each pair's M1 file ONCE (cached as parquet/pickle under data/cache/),
then re-runs the engine with config overrides. Nothing here changes config.yaml.
"""
import argparse
import copy
import os
import pickle
import time

import numpy as np
import pandas as pd
import yaml

from fxbot.backtest import compute_metrics, run_backtest
from fxbot.data import filter_dates, load_csv, resample

CACHE_DIR = "data/cache"


# --------------------------------------------------------------------------- #
#  Data loading (cached)                                                       #
# --------------------------------------------------------------------------- #

def _bars(path, tz, tf):
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = os.path.join(CACHE_DIR, f"{os.path.basename(path)}.{tf}.pkl")
    if os.path.exists(key) and os.path.getmtime(key) > os.path.getmtime(path):
        with open(key, "rb") as f:
            return pickle.load(f)
    bars = resample(load_csv(path, tz), tf)
    with open(key, "wb") as f:
        pickle.dump(bars, f)
    return bars


def load_pairs(cfg):
    """Return {symbol: bars_with_smt_columns} for every pair whose file exists."""
    out = {}
    for pair in cfg["pairs"]:
        d = pair["data"]
        if not os.path.exists(d["path"]):
            print(f"  skip {pair['symbol']}: {d['path']} missing")
            continue
        bars = _bars(d["path"], d["source_tz"], d["timeframe"]).copy()
        smt = pair.get("smt")
        if smt and os.path.exists(smt["path"]):
            sb = _bars(smt["path"], smt["source_tz"], smt["timeframe"])
            m = sb[["high", "low"]].reindex(bars.index)
            bars["smt_high"] = m["high"]
            bars["smt_low"] = m["low"]
        out[pair["symbol"]] = bars
    return out


# --------------------------------------------------------------------------- #
#  Running                                                                     #
# --------------------------------------------------------------------------- #

def run_multi(pair_bars, cfg, start=None, end=None, symbols=None):
    """Run every pair independently on the same equity base and combine PnL."""
    start_eq = cfg["account"]["starting_equity"]
    c = copy.deepcopy(cfg)
    c["smt"] = {}                      # SMT columns are already merged in
    trades_all, pnl = [], None
    for sym, bars in pair_bars.items():
        if symbols and sym not in symbols:
            continue
        b = filter_dates(bars, start, end)
        if len(b) == 0:
            continue
        t, eq = run_backtest(b, c)
        if len(t):
            t = t.copy()
            t.insert(0, "symbol", sym)
            trades_all.append(t)
        p = eq - start_eq
        pnl = p if pnl is None else pnl.add(p.reindex(pnl.index, method="ffill").fillna(0), fill_value=0)
    if pnl is None:
        return pd.DataFrame(), pd.Series(dtype=float)
    trades = pd.concat(trades_all, ignore_index=True).sort_values("entry_time") if trades_all else pd.DataFrame()
    return trades, pnl + start_eq


def summarize(trades, equity, start_eq):
    m = compute_metrics(trades, equity, start_eq)
    return {
        "trades": m["trades"],
        "ret%": round(m["total_return_pct"], 2),
        "cagr%": round(m["cagr_pct"], 2),
        "dd%": round(m["max_drawdown_pct"], 2),
        "sharpe": round(m["sharpe"], 2),
        "win%": round(m.get("win_rate_pct", 0), 1),
        "pf": round(m.get("profit_factor", 0), 2),
        "avgR": round(m.get("avg_r", 0), 3),
    }


def per_year(trades, equity, start_eq):
    rows = []
    for y in sorted(set(equity.index.year)):
        eq = equity[equity.index.year == y]
        if len(eq) < 2:
            continue
        t = trades[pd.to_datetime(trades.entry_time).dt.year == y] if len(trades) else trades
        base = eq.iloc[0]
        r = summarize(t, eq / base * start_eq, start_eq)
        rows.append({"year": y, **r})
    return pd.DataFrame(rows)


def set_param(cfg, dotted, value):
    """Set e.g. 'sweep.swing_k' on the london_sweep spec, 'breakout.x' on breakout,
    'costs.spread_pips' / 'risk.risk_per_trade_pct' on the root."""
    c = copy.deepcopy(cfg)
    head, key = dotted.split(".", 1)
    if head in ("sweep", "breakout"):
        name = "london_sweep" if head == "sweep" else "london_breakout"
        for s in c["strategies"]["morning"]:
            if s["name"] == name:
                s[key] = value
    else:
        c[head][key] = value
    return c


# --------------------------------------------------------------------------- #
#  Reports                                                                     #
# --------------------------------------------------------------------------- #

def walk_forward(pair_bars, cfg):
    se = cfg["account"]["starting_equity"]
    rows = []
    for label, s, e in [("IN-SAMPLE 2021-2023", "2021-01-01", "2023-12-31"),
                        ("OUT-OF-SAMPLE 2024-2025", "2024-01-01", "2025-12-31"),
                        ("FULL 2021-2025", None, None)]:
        for syms, name in [(None, "combined"), (["EURUSD"], "EURUSD"), (["GBPUSD"], "GBPUSD")]:
            t, eq = run_multi(pair_bars, cfg, s, e, syms)
            rows.append({"period": label, "pairs": name, **summarize(t, eq, se)})
    df = pd.DataFrame(rows)
    print("\n=== WALK-FORWARD (config.yaml unchanged) ===")
    print(df.to_string(index=False))

    t, eq = run_multi(pair_bars, cfg)
    print("\n=== PER-YEAR (combined) ===")
    print(per_year(t, eq, se).to_string(index=False))
    if len(t):
        print("\n=== BY STRATEGY TAG (full period) ===")
        g = t.groupby(["symbol", "tag"]).agg(n=("pnl", "size"), pnl=("pnl", "sum"),
                                              win=("pnl", lambda x: (x > 0).mean() * 100),
                                              avgR=("r_multiple", "mean"))
        print(g.round(2).to_string())
        print("\n=== EXIT REASONS ===")
        print(t.groupby(["tag", "exit_reason"]).size().unstack(fill_value=0).to_string())
    return df


ROBUST_GRID = [
    ("costs.spread_pips", [1.0, 1.5, 2.0]),
    ("costs.slippage_pips", [0.2, 0.5]),
    ("sweep.swing_k", [1, 2, 3]),
    ("sweep.sweep_max_pips", [10.0, 15.0, 20.0]),
    ("sweep.max_stop_pips", [20, 25, 30]),
    ("sweep.min_rr", [1.25, 1.5, 2.0]),
    ("sweep.max_bars_after_sweep", [8, 12, 18]),
    ("sweep.trail_to_breakeven_rr", [0.0, 1.0, 1.5]),
    ("sweep.smt_filter", [False, True]),
    ("sweep.skip_days", [[], [0], [0, 1], [0, 1, 4]]),
    ("breakout.min_range_pips", [20, 25, 30]),
    ("breakout.max_defer_extension_pips", [10, 15, 25, None]),
    ("breakout.reward_risk", [1.5, 2.0, 2.5]),
]


def robustness(pair_bars, cfg, grid=ROBUST_GRID):
    se = cfg["account"]["starting_equity"]
    rows = []
    for dotted, values in grid:
        for v in values:
            c = set_param(cfg, dotted, v)
            r = {"param": dotted, "value": str(v)}
            for label, s, e in [("IS", "2021-01-01", "2023-12-31"), ("OOS", "2024-01-01", "2025-12-31")]:
                t, eq = run_multi(pair_bars, c, s, e)
                m = summarize(t, eq, se)
                r[f"{label}_ret%"] = m["ret%"]
                r[f"{label}_pf"] = m["pf"]
                r[f"{label}_dd%"] = m["dd%"]
                r[f"{label}_n"] = m["trades"]
            rows.append(r)
            print(f"  {dotted}={v!s:<10} IS {r['IS_ret%']:+6.2f}% pf {r['IS_pf']:.2f} | "
                  f"OOS {r['OOS_ret%']:+6.2f}% pf {r['OOS_pf']:.2f} dd {r['OOS_dd%']:.2f}", flush=True)
    df = pd.DataFrame(rows)
    print("\n=== ROBUSTNESS (one parameter at a time, rest = config.yaml) ===")
    print(df.to_string(index=False))
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--only", choices=["walk", "robust"])
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config))
    t0 = time.time()
    pair_bars = load_pairs(cfg)
    print(f"loaded {list(pair_bars)} in {time.time()-t0:.0f}s")
    os.makedirs(args.out, exist_ok=True)
    if args.only in (None, "walk"):
        walk_forward(pair_bars, cfg).to_csv(f"{args.out}/walk_forward.csv", index=False)
    if args.only in (None, "robust"):
        robustness(pair_bars, cfg).to_csv(f"{args.out}/robustness.csv", index=False)
    print(f"done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
