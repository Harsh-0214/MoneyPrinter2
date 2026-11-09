"""Run all strategies against the same dataset and print a comparison table.

    python run_compare.py
    python run_compare.py --start 2025-07-01 --end 2026-11-01
"""
import argparse
import copy

import yaml

from fxbot.backtest import compute_metrics, run_backtest
from fxbot.data import filter_dates, load_csv, resample
from fxbot.strategies import LondonBreakout, MeanReversion, NYOpenBreakout, PrevDayBreakout


def _run(bars, cfg, strategy_cls, overrides=None):
    cfg = copy.deepcopy(cfg)
    if overrides:
        cfg["strategy"].update(overrides)
    trades, equity = run_backtest(bars, cfg, strategy_cls)
    return compute_metrics(trades, equity, cfg["account"]["starting_equity"]), trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--start")
    ap.add_argument("--end")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    d = cfg["data"]

    print(f"Loading {d['path']} ...")
    raw = load_csv(d["path"], d["source_tz"])
    raw = filter_dates(raw, args.start or d.get("start"), args.end or d.get("end"))
    bars = resample(raw, d["timeframe"])
    print(f"{len(raw):,} raw bars -> {len(bars):,} {d['timeframe']} bars\n")

    # Best London params from prior tuning
    best_london = {"reward_risk": 1.0, "min_range_pips": 20}

    runs = [
        ("London Breakout (best)",  LondonBreakout,  best_london),
        ("London + EMA50 filter",   LondonBreakout,  {**best_london, "ema_filter": True, "ema_period": 50}),
        ("NY Open Breakout",        NYOpenBreakout,  best_london),
        ("Prev Day H/L Breakout",   PrevDayBreakout, {"reward_risk": 1.0}),
        ("Mean Reversion",          MeanReversion,   {"reward_risk": 1.0, "min_range_pips": 20, "mean_rev_stop_mult": 1.5}),
    ]

    results = []
    for name, cls, overrides in runs:
        print(f"  Running: {name} ...")
        m, trades = _run(bars, cfg, cls, overrides)
        m["name"] = name
        m["trades_df"] = trades
        results.append(m)

    # Print comparison table
    cols = [
        ("Strategy",        lambda m: m["name"],                        "<32"),
        ("Trades",          lambda m: str(m["trades"]),                 ">7"),
        ("Return",          lambda m: f"{m['total_return_pct']:+.2f}%", ">9"),
        ("MaxDD",           lambda m: f"{m['max_drawdown_pct']:.2f}%",  ">8"),
        ("Sharpe",          lambda m: f"{m['sharpe']:.2f}",             ">7"),
        ("Win%",            lambda m: f"{m['win_rate_pct']:.1f}%" if m["trades"] else "—", ">7"),
        ("PF",              lambda m: f"{m['profit_factor']:.2f}" if m["trades"] else "—", ">6"),
        ("AvgR",            lambda m: f"{m['avg_r']:.3f}" if m["trades"] else "—", ">7"),
        ("Exp$/tr",         lambda m: f"${m['expectancy_usd']:.2f}" if m["trades"] else "—", ">9"),
    ]

    sep = "  "
    header = sep.join(f"{h:{fmt}}" for h, _, fmt in cols)
    divider = "-" * len(header)
    print("\n" + divider)
    print(header)
    print(divider)
    for m in results:
        row = sep.join(f"{fn(m):{fmt}}" for _, fn, fmt in cols)
        print(row)
    print(divider)

    # Rank by total return
    ranked = sorted(results, key=lambda m: m["total_return_pct"], reverse=True)
    print(f"\nBest return:  {ranked[0]['name']}  ({ranked[0]['total_return_pct']:+.2f}%)")
    best_pf = max(results, key=lambda m: m.get("profit_factor", 0) if m.get("profit_factor", 0) != float("inf") else 0)
    print(f"Best PF:      {best_pf['name']}  ({best_pf.get('profit_factor', 0):.2f})")
    best_sharpe = max(results, key=lambda m: m["sharpe"])
    print(f"Best Sharpe:  {best_sharpe['name']}  ({best_sharpe['sharpe']:.2f})")


if __name__ == "__main__":
    main()
