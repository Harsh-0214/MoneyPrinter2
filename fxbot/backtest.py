"""Backtest runner and performance metrics."""
import copy
import os
from dataclasses import asdict

import numpy as np
import pandas as pd

from .brokers import SimBroker, compute_spread_pips
from .data import PIP, filter_dates, load_csv, resample
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


def _build_strategies(cfg):
    """Instantiate strategies from config.

    Supports two modes:
      - Single:  cfg["strategy"]["name"] selects one strategy (legacy)
      - Multi:   cfg["strategies"] is a dict with "morning" and "afternoon" lists,
                 each being a list of {name, ...params} dicts in priority order.

    Returns (morning_strategies, afternoon_strategies).
    Morning strategies share one trade slot per day (first to fire wins).
    Afternoon strategies share a separate slot per day.
    """
    if "strategies" in cfg:
        def _make(spec):
            cls = STRATEGY_MAP[spec["name"]]
            return cls(spec, PIP)
        morning   = [_make(s) for s in cfg["strategies"].get("morning",   [])]
        afternoon = [_make(s) for s in cfg["strategies"].get("afternoon", [])]
    else:
        s_cfg = cfg["strategy"]
        cls = STRATEGY_MAP.get(s_cfg.get("name", "london_breakout"), LondonBreakout)
        morning   = [cls(s_cfg, PIP)]
        afternoon = []
    return morning, afternoon


def run_backtest(df, cfg, strategy_cls=None):
    # Allow caller to pass a single class directly (used by tests and grid scripts)
    if strategy_cls is not None:
        single_cfg = cfg.get("strategy", {})
        morning   = [strategy_cls(single_cfg, PIP)]
        afternoon = []
        ref_cfg   = single_cfg
    else:
        morning, afternoon = _build_strategies(cfg)
        ref_cfg = cfg.get("strategy", (cfg["strategies"]["morning"][0]
                                       if "strategies" in cfg else {}))

    c_cfg = cfg["costs"]
    df = df.copy()
    df["spread_pips"] = compute_spread_pips(df, c_cfg)
    df["atr"] = add_atr(df, ref_cfg.get("atr_period", 14))
    df["ema"] = df["close"].ewm(span=ref_cfg.get("ema_period", 50), adjust=False).mean()
    daily_close = df["close"].resample("1D").last().shift(1)
    daily_ema_raw = daily_close.ewm(span=ref_cfg.get("daily_ema_period", 10), adjust=False).mean()
    df["daily_ema"] = daily_ema_raw.reindex(df.index, method="ffill")
    smt_cfg = cfg.get("smt", {})
    if smt_cfg:
        df = _load_smt_pair(smt_cfg, df)

    local = df.index.tz_convert("Europe/London").tz_localize(None)
    local_days = local.values.astype("datetime64[D]")
    local_mins = (local.hour * 60 + local.minute).to_numpy()

    broker = SimBroker(cfg["account"]["starting_equity"], c_cfg["slippage_pips"],
                       c_cfg["commission_per_lot_per_side"], PIP)
    risk = RiskManager(cfg["risk"], PIP)

    equity = np.empty(len(df))
    prev_day        = None
    morning_fired   = None   # day on which the morning slot was used
    afternoon_fired = None   # day on which the afternoon slot was used

    for i, bar in enumerate(df.itertuples()):
        broker.on_bar(bar)
        day  = local_days[i]
        lmin = local_mins[i]
        if day != prev_day:
            risk.new_day(broker.equity())
            prev_day = day

        # --- Morning strategies: scored-proposal selection ---
        # propose() is ALWAYS called (not gated on morning_fired) so that each
        # strategy's internal session-exit check runs every bar.  Only the
        # submission of the resulting order is gated on morning_fired.
        morning_proposals = []
        for strat in morning:
            if hasattr(strat, "propose"):
                p = strat.propose(bar, day, lmin, broker, risk)
                # propose() handles session exit internally; collect proposals
                # only for days where the morning slot hasn't fired yet.
                if p is not None and morning_fired != day:
                    morning_proposals.append((strat, p))
            else:
                # Legacy strategy: call on_bar() only before morning fires
                if morning_fired != day:
                    n_before = len(broker.trades)
                    strat.on_bar(bar, day, lmin, broker, risk)
                    if len(broker.trades) > n_before:
                        morning_fired = day

        if morning_proposals and morning_fired != day:
            best_strat, best_prop = max(morning_proposals, key=lambda x: x[1].score)
            if broker.submit(best_prop.order):
                best_strat.mark_fired()
                morning_fired = day

        # --- Afternoon strategies: independent session ---
        for strat in afternoon:
            if hasattr(strat, "propose"):
                p = strat.propose(bar, day, lmin, broker, risk)
                if p is not None and afternoon_fired != day:
                    if broker.submit(p.order):
                        strat.mark_fired()
                        afternoon_fired = day
            else:
                if afternoon_fired != day:
                    n_before = len(broker.trades)
                    strat.on_bar(bar, day, lmin, broker, risk)
                    if len(broker.trades) > n_before:
                        afternoon_fired = day

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


def run_backtest_multi_pair(cfg):
    """Run one independent backtest per pair in cfg['pairs'], then combine PnL.

    Each pair runs the same strategies section with its own data and SMT pair.
    Pairs with missing data files are skipped with a warning.
    Falls back to run_backtest() when no 'pairs' key is present.

    Returns (combined_trades_df, combined_equity_series).
    """
    pairs = cfg.get("pairs", [])
    if not pairs:
        d = cfg["data"]
        raw = load_csv(d["path"], d["source_tz"])
        bars = resample(raw, d["timeframe"])
        if d.get("start") or d.get("end"):
            bars = filter_dates(bars, d.get("start"), d.get("end"))
        return run_backtest(bars, cfg)

    d_ref = cfg.get("data", {})
    start = d_ref.get("start")
    end = d_ref.get("end")
    starting_equity = cfg["account"]["starting_equity"]

    all_trades = []
    combined_pnl = None

    for pair in pairs:
        symbol = pair.get("symbol", "UNKNOWN")
        data_cfg = pair["data"]
        if not os.path.exists(data_cfg["path"]):
            print(f"[multi-pair] {data_cfg['path']} not found — skipping {symbol}")
            continue

        pair_cfg = copy.deepcopy(cfg)
        pair_cfg["data"] = dict(data_cfg)
        if start:
            pair_cfg["data"]["start"] = start
        if end:
            pair_cfg["data"]["end"] = end
        pair_cfg["smt"] = pair.get("smt", {})

        raw = load_csv(pair_cfg["data"]["path"], pair_cfg["data"]["source_tz"])
        bars = resample(raw, pair_cfg["data"]["timeframe"])
        if start or end:
            bars = filter_dates(bars, start, end)

        print(f"[multi-pair] Running {symbol} ({len(bars):,} bars) ...")
        t, eq = run_backtest(bars, pair_cfg)

        if len(t):
            t = t.copy()
            t.insert(0, "symbol", symbol)
        all_trades.append(t)

        pnl = eq - starting_equity
        if combined_pnl is None:
            combined_pnl = pnl
        else:
            combined_pnl = combined_pnl.add(
                pnl.reindex(combined_pnl.index, method="ffill").fillna(0),
                fill_value=0,
            )

    if not all_trades or all(len(t) == 0 for t in all_trades):
        return pd.DataFrame(), pd.Series(dtype=float, name="equity")

    combined_equity = combined_pnl + starting_equity
    non_empty = [t for t in all_trades if len(t) > 0]
    combined_trades = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()
    if len(combined_trades):
        combined_trades = combined_trades.sort_values("entry_time").reset_index(drop=True)

    return combined_trades, combined_equity
