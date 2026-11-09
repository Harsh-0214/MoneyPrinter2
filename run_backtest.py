"""Run a backtest.

    python run_backtest.py --synthetic                 # test the pipeline on random data
    python run_backtest.py                             # use data.path from config.yaml
    python run_backtest.py --start 2022-01-01 --end 2023-12-31
"""
import argparse
from pathlib import Path

import yaml

from fxbot.backtest import compute_metrics, print_metrics, run_backtest
from fxbot.data import filter_dates, generate_synthetic, load_csv, resample


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--synthetic", action="store_true", help="use random-walk data (no edge)")
    ap.add_argument("--start")
    ap.add_argument("--end")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    d = cfg["data"]

    if args.synthetic:
        print("Using SYNTHETIC random-walk data. Expect a loss of roughly the trading costs.")
        raw = generate_synthetic(days=730)
    else:
        print(f"Loading {d['path']} (timestamps in {d['source_tz']}) ...")
        raw = load_csv(d["path"], d["source_tz"])

    raw = filter_dates(raw, args.start or d.get("start"), args.end or d.get("end"))
    bars = resample(raw, d["timeframe"])
    print(f"{len(raw):,} raw bars -> {len(bars):,} {d['timeframe']} bars")

    trades, equity = run_backtest(bars, cfg)
    metrics = compute_metrics(trades, equity, cfg["account"]["starting_equity"])
    print_metrics(metrics)

    out = Path(cfg["output"]["dir"])
    out.mkdir(exist_ok=True)
    trades.to_csv(out / "trades.csv", index=False)
    equity.resample("1h").last().dropna().to_csv(out / "equity.csv")
    print(f"Saved {out/'trades.csv'} and {out/'equity.csv'}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True,
                                     gridspec_kw={"height_ratios": [3, 1]})
        eq = equity.resample("1h").last().dropna()
        a1.plot(eq.index, eq.values)
        a1.set_title("Equity")
        a1.grid(alpha=0.3)
        dd = (eq / eq.cummax() - 1) * 100
        a2.fill_between(dd.index, dd.values, 0, color="tab:red", alpha=0.4)
        a2.set_title("Drawdown %")
        a2.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "equity.png", dpi=110)
        print(f"Saved {out/'equity.png'}")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
