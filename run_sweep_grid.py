"""Robustness grid for London Sweep: sweep_max_pips x swing_k x target_mode.
Report only — no optimization. Looking for a stable region.

    python run_sweep_grid.py
"""
import copy
import yaml

from fxbot.backtest import compute_metrics, run_backtest
from fxbot.data import filter_dates, load_csv, resample
from fxbot.strategies.london_sweep import LondonSweep


def main():
    cfg = yaml.safe_load(open("config.yaml"))
    d = cfg["data"]
    print(f"Loading {d['path']} ...")
    raw = load_csv(d["path"], d["source_tz"])
    raw = filter_dates(raw, d.get("start"), d.get("end"))
    bars = resample(raw, d["timeframe"])
    print(f"{len(bars):,} {d['timeframe']} bars\n")

    sweep_max_vals  = [10, 15, 20]
    swing_k_vals    = [2, 3]
    target_modes    = ["opposite_range", "rr"]

    rows = []
    for smp in sweep_max_vals:
        for sk in swing_k_vals:
            for tm in target_modes:
                c = copy.deepcopy(cfg)
                c["strategy"].update({
                    "name":          "london_sweep",
                    "sweep_max_pips": smp,
                    "swing_k":        sk,
                    "target_mode":    tm,
                    "reward_risk":    2.0,   # spec default for sweep
                })
                trades, equity = run_backtest(bars, c, LondonSweep)
                m = compute_metrics(trades, equity, c["account"]["starting_equity"])
                rows.append({
                    "sweep_max": smp,
                    "swing_k":   sk,
                    "target":    tm[:3],  # 'opp' or 'rr'
                    **m,
                })
                print(f"  sweep_max={smp:2d}  swing_k={sk}  target={tm[:3]:3s} -> "
                      f"trades={m['trades']:3d}  return={m['total_return_pct']:+.2f}%  "
                      f"PF={m.get('profit_factor',0):.2f}  "
                      f"DD={m['max_drawdown_pct']:.2f}%")

    # Print full table
    cols = [
        ("sweep_max", ">9"),
        ("swing_k",   ">7"),
        ("target",    ">6"),
        ("trades",    ">7"),
        ("return",    ">9"),
        ("MaxDD",     ">8"),
        ("Sharpe",    ">7"),
        ("Win%",      ">7"),
        ("PF",        ">6"),
        ("AvgR",      ">7"),
    ]
    print("\n" + "=" * 80)
    hdr = "  ".join(f"{h:{f}}" for h, f in cols)
    print(hdr)
    print("-" * 80)
    for r in rows:
        pf = r.get("profit_factor", 0)
        pf = min(pf, 99.0) if pf != float("inf") else 99.0
        win = r.get("win_rate_pct", 0)
        avg_r = r.get("avg_r", 0)
        print("  ".join([
            f"{r['sweep_max']:>9}",
            f"{r['swing_k']:>7}",
            f"{r['target']:>6}",
            f"{r['trades']:>7}",
            f"{r['total_return_pct']:>+8.2f}%",
            f"{r['max_drawdown_pct']:>7.2f}%",
            f"{r.get('sharpe', 0):>7.2f}",
            f"{win:>6.1f}%",
            f"{pf:>6.2f}",
            f"{avg_r:>7.3f}",
        ]))
    print("=" * 80)

    # Highlight best cells
    pos = [r for r in rows if r["total_return_pct"] > 0]
    if pos:
        best = max(pos, key=lambda r: r["total_return_pct"])
        print(f"\nBest return: sweep_max={best['sweep_max']} swing_k={best['swing_k']} "
              f"target={best['target']}  ({best['total_return_pct']:+.2f}%  "
              f"PF={min(best.get('profit_factor',0),99):.2f}  trades={best['trades']})")
    else:
        print("\nNo combination was profitable on this dataset.")

    best_pf_row = max(rows, key=lambda r: min(r.get("profit_factor", 0), 99))
    print(f"Best PF:     sweep_max={best_pf_row['sweep_max']} swing_k={best_pf_row['swing_k']} "
          f"target={best_pf_row['target']}  PF={min(best_pf_row.get('profit_factor',0),99):.2f}")


if __name__ == "__main__":
    main()
