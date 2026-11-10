"""Backtest runner and performance metrics."""
from dataclasses import asdict

import numpy as np
import pandas as pd

from .brokers import SimBroker, compute_spread_pips
from .data import PIP, load_csv, resample
from .risk import RiskManager
from .strategies import (LondonBreakout, LondonSweep, MeanReversion,
                          NYOpenBreakout, PrevDayBreakout)

STRATEGY_MAP = {
    "london_breakout":  LondonBreakout,
    "london_sweep":     LondonSweep,
    "ny_breakout":      NYOpenBreakout,
    "prev_day_breakout": PrevDayBreakout,
    "mean_reversion":   MeanReversion,
}


def add_atr(df, period):
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _load_smt_pair(smt_cfg, main_df):
    """Load the SMT confirmation pair and merge its high/low onto the main dataframe.

    Returns the main dataframe with two new columns: smt_high, smt_low.
    Both are NaN when the SMT pair has no bar at that timestamp.
    """
    path = smt_cfg.get("path")
    if not path:
        return main_df
    import os
    if not os.path.exists(path):
        print(f"[SMT] Warning: {path} not found — SMT filter disabled")
        return main_df
    tz   = smt_cfg.get("source_tz", "UTC")
    tf   = smt_cfg.get("timeframe", "5min")
    raw  = load_csv(path, tz)
    bars = resample(raw, tf)
    # Align to main df index; keep only high and low
    merged = bars[["high", "low"]].reindex(main_df.index, method=None)
    main_df = main_df.copy()
    main_df["smt_high"] = merged["high"]
    main_df["smt_low"]  = merged["low"]
    return main_df


def run_backtest(df, cfg, strategy_cls=None):
    s_cfg, c_cfg = cfg["strategy"], cfg["costs"]
    df = df.copy()
    df["spread_pips"] = compute_spread_pips(df, c_cfg)
    df["atr"] = add_atr(df, s_cfg.get("atr_period", 14))
    # Intrabar EMA (used by LondonBreakout's ema_filter)
    df["ema"] = df["close"].ewm(span=s_cfg.get("ema_period", 50), adjust=False).mean()
    # Daily-close EMA: shift(1) so each bar only sees *previous* day's close — no lookahead
    daily_close = df["close"].resample("1D").last().shift(1)
    daily_ema_raw = daily_close.ewm(span=s_cfg.get("daily_ema_period", 10), adjust=False).mean()
    df["daily_ema"] = daily_ema_raw.reindex(df.index, method="ffill")
    # SMT pair (e.g. GBPUSD for EURUSD strategy): merge high/low columns
    smt_cfg = cfg.get("smt", {})
    if smt_cfg:
        df = _load_smt_pair(smt_cfg, df)

    local = df.index.tz_convert("Europe/London").tz_localize(None)
    local_days = local.values.astype("datetime64[D]")
    local_mins = (local.hour * 60 + local.minute).to_numpy()

    broker = SimBroker(cfg["account"]["starting_equity"], c_cfg["slippage_pips"],
                       c_cfg["commission_per_lot_per_side"], PIP)
    risk = RiskManager(cfg["risk"], PIP)
    if strategy_cls is None:
        strategy_cls = STRATEGY_MAP.get(s_cfg.get("name", "london_breakout"), LondonBreakout)
    strategy = strategy_cls(s_cfg, PIP)

    equity = np.empty(len(df))
    prev_day = None
    for i, bar in enumerate(df.itertuples()):
        broker.on_bar(bar)                     # fills + stops/targets
        day = local_days[i]
        if day != prev_day:
            risk.new_day(broker.equity())
            prev_day = day
        strategy.on_bar(bar, day, local_mins[i], broker, risk)   # decisions at bar close
        equity[i] = broker.equity()
    broker.close_at_end()
    if len(equity):
        equity[-1] = broker.equity()

    trades = pd.DataFrame([asdict(t) for t in broker.trades])
    return trades, pd.Series(equity, index=df.index, name="equity")


def compute_metrics(trades, equity, starting_equity):
    m = {}
    m["start"] = equity.index[0].date() if len(equity) else None
    m["end"] = equity.index[-1].date() if len(equity) else None
    m["trades"] = len(trades)
    final = equity.iloc[-1] if len(equity) else starting_equity
    m["final_equity"] = final
    m["total_return_pct"] = (final / starting_equity - 1) * 100
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9) if len(equity) else 1
    m["cagr_pct"] = ((final / starting_equity) ** (1 / years) - 1) * 100 if final > 0 else -100
    dd = equity / equity.cummax() - 1
    m["max_drawdown_pct"] = dd.min() * 100 if len(dd) else 0.0

    daily = equity.resample("1D").last().dropna().pct_change().dropna()
    m["sharpe"] = daily.mean() / daily.std() * np.sqrt(252) if len(daily) > 1 and daily.std() > 0 else 0.0

    if len(trades):
        wins = trades[trades.pnl > 0]
        losses = trades[trades.pnl <= 0]
        m["win_rate_pct"] = len(wins) / len(trades) * 100
        gl = -losses.pnl.sum()
        m["profit_factor"] = wins.pnl.sum() / gl if gl > 0 else float("inf")
        m["avg_r"] = trades.r_multiple.mean()
        m["expectancy_usd"] = trades.pnl.mean()
        streak = best = 0
        for p in trades.pnl:
            streak = streak + 1 if p <= 0 else 0
            best = max(best, streak)
        m["max_losing_streak"] = best
        m["exit_reasons"] = trades.exit_reason.value_counts().to_dict()
    return m


def print_metrics(m):
    print("\n" + "=" * 46)
    print(f"  Backtest {m['start']} -> {m['end']}")
    print("=" * 46)
    rows = [
        ("Trades", f"{m['trades']}"),
        ("Final equity", f"${m['final_equity']:,.2f}"),
        ("Total return", f"{m['total_return_pct']:.2f}%"),
        ("CAGR", f"{m['cagr_pct']:.2f}%"),
        ("Max drawdown", f"{m['max_drawdown_pct']:.2f}%"),
        ("Sharpe (daily)", f"{m['sharpe']:.2f}"),
    ]
    if m["trades"]:
        rows += [
            ("Win rate", f"{m['win_rate_pct']:.1f}%"),
            ("Profit factor", f"{m['profit_factor']:.2f}"),
            ("Avg R per trade", f"{m['avg_r']:.3f}"),
            ("Expectancy / trade", f"${m['expectancy_usd']:.2f}"),
            ("Max losing streak", f"{m['max_losing_streak']}"),
            ("Exit reasons", ", ".join(f"{k}: {v}" for k, v in m["exit_reasons"].items())),
        ]
    for k, v in rows:
        print(f"  {k:<20}{v}")
    print("=" * 46)
