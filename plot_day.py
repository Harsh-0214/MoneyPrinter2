"""Visualise one trading day for any strategy.

    python plot_day.py --date 2026-03-15
    python plot_day.py --date 2026-03-15 --strategy london_breakout

Saves a PNG to results/day_YYYY-MM-DD_<strategy>.png and opens it.
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from fxbot.backtest import STRATEGY_MAP, add_atr, run_backtest
from fxbot.brokers import SimBroker, compute_spread_pips
from fxbot.data import PIP, filter_dates, load_csv, resample
from fxbot.risk import RiskManager
from fxbot.strategies.london_sweep import LondonSweep


# ---------------------------------------------------------------------------

def _london_min(ts):
    """Return minutes-since-midnight in London time."""
    local = ts.tz_convert("Europe/London")
    return local.hour * 60 + local.minute


def _run_day(bars_day, cfg, strategy_cls):
    """Run strategy on a single day's bars and collect events for plotting."""
    from fxbot.brokers.base import Order

    s_cfg = cfg["strategy"]
    c_cfg = cfg["costs"]

    bars = bars_day.copy()
    bars["spread_pips"] = compute_spread_pips(bars, c_cfg)
    bars["atr"] = add_atr(bars, s_cfg.get("atr_period", 14))
    bars["ema"] = bars["close"].ewm(span=s_cfg.get("ema_period", 50), adjust=False).mean()

    local_lon = bars.index.tz_convert("Europe/London").tz_localize(None)
    local_days = local_lon.values.astype("datetime64[D]")
    local_mins = (local_lon.hour * 60 + local_lon.minute).to_numpy()

    broker = SimBroker(cfg["account"]["starting_equity"], c_cfg["slippage_pips"],
                       c_cfg["commission_per_lot_per_side"], PIP)
    risk = RiskManager(cfg["risk"], PIP)
    strategy = strategy_cls(s_cfg, PIP)

    events = []
    for i, bar in enumerate(bars.itertuples()):
        broker.on_bar(bar)
        day = local_days[i]
        strategy.on_bar(bar, day, local_mins[i], broker, risk)
        # Snapshot swing points and state after each bar
        if isinstance(strategy, LondonSweep):
            events.append({
                "ts": bar.Index,
                "sw_lows":  list(strategy._sw_lows),
                "sw_highs": list(strategy._sw_highs),
                "asian_hi": strategy.asian_hi,
                "asian_lo": strategy.asian_lo,
                "ext_hi":   strategy.ext_hi,
                "ext_lo":   strategy.ext_lo,
                "ext_hi_idx": strategy.ext_hi_idx,
                "ext_lo_idx": strategy.ext_lo_idx,
            })

    broker.close_at_end()
    return bars, broker.trades, events, strategy


def plot_day(date_str, strategy_name, cfg, output_dir="results"):
    strategy_cls = STRATEGY_MAP.get(strategy_name)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy '{strategy_name}'. Options: {list(STRATEGY_MAP)}")

    d = cfg["data"]
    raw = load_csv(d["path"], d["source_tz"])
    bars = resample(raw, d["timeframe"])

    target_date = pd.Timestamp(date_str)
    # Get two days so the strategy can build state from prior bars
    day_start = (target_date - pd.Timedelta(days=2)).tz_localize("UTC")
    day_end   = (target_date + pd.Timedelta(days=1)).tz_localize("UTC")
    bars_window = bars[(bars.index >= day_start) & (bars.index < day_end)]

    if len(bars_window) == 0:
        print(f"No data for {date_str}. Available: {bars.index[0].date()} to {bars.index[-1].date()}")
        return

    bars_day, trades, events, strategy = _run_day(bars_window, cfg, strategy_cls)

    # Filter to just the requested day in London time
    lon_dates = bars_day.index.tz_convert("Europe/London").normalize()
    target_ts = pd.Timestamp(date_str, tz="Europe/London")
    mask = lon_dates == target_ts
    bars_plot = bars_day[mask]

    if len(bars_plot) == 0:
        print(f"No bars in London time for {date_str}")
        return

    # --- build figure ---
    fig, ax = plt.subplots(figsize=(16, 7))
    x = np.arange(len(bars_plot))
    xs = dict(zip(bars_plot.index, x))

    # Candles
    for i, (ts, row) in enumerate(bars_plot.iterrows()):
        c = "tab:green" if row.close >= row.open else "tab:red"
        ax.plot([i, i], [row.low, row.high], color=c, lw=0.8)
        ax.add_patch(plt.Rectangle((i - 0.3, min(row.open, row.close)),
                                    0.6, abs(row.close - row.open), color=c, alpha=0.9))

    # --- London Sweep annotations ---
    if isinstance(strategy, LondonSweep) and events:
        last = events[-1]
        asian_hi = last["asian_hi"] if last["asian_hi"] != float("-inf") else None
        asian_lo = last["asian_lo"] if last["asian_lo"] != float("inf") else None

        if asian_hi and asian_lo:
            s_cfg = cfg["strategy"]
            rng_start = s_cfg.get("range_start", "00:00")
            rng_end   = s_cfg.get("range_end",   "08:00")

            # Asian range box (shaded)
            rng_start_ts = pd.Timestamp(f"{date_str} {rng_start}:00", tz="Europe/London")
            rng_end_ts   = pd.Timestamp(f"{date_str} {rng_end}:00",   tz="Europe/London")
            x0 = xs.get(rng_start_ts, 0)
            x1 = xs.get(rng_end_ts, len(bars_plot) - 1)
            ax.axhspan(asian_lo, asian_hi, xmin=x0 / len(bars_plot),
                       xmax=x1 / len(bars_plot), alpha=0.08, color="blue", label="Asian range")
            ax.axhline(asian_hi, color="blue", lw=0.8, ls="--", alpha=0.6, label=f"Asian H {asian_hi:.5f}")
            ax.axhline(asian_lo, color="blue", lw=0.8, ls=":",  alpha=0.6, label=f"Asian L {asian_lo:.5f}")

        # Swing lows (confirmed, today)
        for idx, lo in last["sw_lows"]:
            if idx < len(events):
                ts = events[idx]["ts"]
                xi = xs.get(ts)
                if xi is not None:
                    ax.plot(xi, lo, "^", color="lime", ms=7, zorder=5)

        # Swing highs
        for idx, hi in last["sw_highs"]:
            if idx < len(events):
                ts = events[idx]["ts"]
                xi = xs.get(ts)
                if xi is not None:
                    ax.plot(xi, hi, "v", color="orange", ms=7, zorder=5)

        # Sweep extreme
        if last["ext_hi"] != float("-inf") and last["ext_hi_idx"] is not None:
            xi = last["ext_hi_idx"]
            if xi < len(events):
                ts = events[xi]["ts"]
                xi_plot = xs.get(ts)
                if xi_plot is not None:
                    ax.plot(xi_plot, last["ext_hi"], "*", color="red", ms=12, zorder=6,
                            label=f"Sweep H {last['ext_hi']:.5f}")

        if last["ext_lo"] != float("inf") and last["ext_lo_idx"] is not None:
            xi = last["ext_lo_idx"]
            if xi < len(events):
                ts = events[xi]["ts"]
                xi_plot = xs.get(ts)
                if xi_plot is not None:
                    ax.plot(xi_plot, last["ext_lo"], "*", color="green", ms=12, zorder=6,
                            label=f"Sweep L {last['ext_lo']:.5f}")

    # --- Trades ---
    for trade in trades:
        if trade.entry_time.date() != pd.Timestamp(date_str).date():
            continue
        xi_entry = xs.get(trade.entry_time)
        xi_exit  = xs.get(trade.exit_time)
        if xi_entry is None:
            # find nearest
            diffs = {ts: abs((ts - trade.entry_time).total_seconds()) for ts in bars_plot.index}
            xi_entry = xs[min(diffs, key=diffs.get)]
        if xi_exit is None:
            diffs = {ts: abs((ts - trade.exit_time).total_seconds()) for ts in bars_plot.index}
            xi_exit = xs.get(min(diffs, key=diffs.get), xi_entry)

        col = "tab:green" if trade.pnl > 0 else "tab:red"
        ax.annotate("", xy=(xi_exit, trade.exit_price), xytext=(xi_entry, trade.entry_price),
                    arrowprops=dict(arrowstyle="->", color=col, lw=1.5))
        ax.axhline(trade.entry_price, color=col, lw=0.6, alpha=0.5)
        if hasattr(trade, "stop_loss"):
            pass
        pnl_str = f"${trade.pnl:+.0f} ({trade.exit_reason})"
        ax.annotate(pnl_str, xy=(xi_exit, trade.exit_price), fontsize=7,
                    color=col, va="bottom")

    # --- Formatting ---
    # x-axis: show time labels every 2 hours
    ticks, labels = [], []
    for i, ts in enumerate(bars_plot.index):
        lon_min = _london_min(ts)
        if lon_min % 120 == 0:
            ticks.append(i)
            labels.append(ts.tz_convert("Europe/London").strftime("%H:%M"))
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=0, fontsize=8)
    ax.set_title(f"{date_str}  {strategy_name}  ({len(trades)} trade(s) on this day)", fontsize=11)
    ax.set_ylabel("Price")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=7, loc="upper left")

    Path(output_dir).mkdir(exist_ok=True)
    outpath = f"{output_dir}/day_{date_str}_{strategy_name}.png"
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)
    print(f"Saved {outpath}")
    return outpath


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date",     required=True, help="YYYY-MM-DD")
    ap.add_argument("--strategy", default="london_sweep")
    ap.add_argument("--config",   default="config.yaml")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    plot_day(args.date, args.strategy, cfg)


if __name__ == "__main__":
    main()
