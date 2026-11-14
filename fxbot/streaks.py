"""Losing streaks per strategy: count them, compare with the tests, optionally trade smaller.

Settings in config.yaml, live.losing_streak:
    alert_after: 3     # say it in the terminal / Telegram when a strategy has lost this many in a row
    size_after: null   # null = off. N = after N losses in a row, trade at size_mult until a win
    size_mult: 0.5

Nov 14 2026 (run_streak_sizing.py): half size after 3 losses until a win, on top of the account
brake: avg month 4.06 -> 4.02 / 6.54 -> 6.56 / 7.04 -> 6.76 (2021-23 / 2024-25 / 2026), max drawdown
-17.2 -> -16.0 / -19.7 -> -19.6 / -8.5 -> -7.3. Slightly smoother, slightly less money: off by default.
"""
import os
from datetime import datetime, timedelta, timezone

import pandas as pd


def trailing_losses(pnls):
    """Losses in a row at the end of a list of closed-trade results (oldest first)."""
    n = 0
    for p in reversed(pnls):
        if p <= 0:
            n += 1
        else:
            break
    return n


def closed_pnls(mt5, magic, symbol=None, days=180):
    """Results of this strategy's closed trades in MT5's history, oldest first."""
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    by_pos = {}
    for d in deals:
        if d.magic == magic and (symbol is None or d.symbol == symbol):
            by_pos.setdefault(d.position_id, []).append(d)
    out = []
    for ds in by_pos.values():
        exits = [d for d in ds if d.entry == mt5.DEAL_ENTRY_OUT]
        if not exits:
            continue
        pnl = sum(d.profit + d.commission + getattr(d, "swap", 0.0) for d in ds)
        out.append((max(d.time for d in exits), pnl))
    return [p for _, p in sorted(out)]


def test_history(unit_key, files=("results/portfolio_trades_hist.csv", "results/portfolio_trades_mt5.csv")):
    """{streak length: how many times the tests had a streak at least that long, 'longest': n}."""
    frames = [pd.read_csv(f) for f in files if os.path.exists(f)]
    if not frames:
        return None
    t = pd.concat(frames)
    t = t[t.unit == unit_key].drop_duplicates(["entry_time"]).sort_values("entry_time")
    if not len(t):
        return None
    runs, k = [], 0
    for r in t.r_multiple:
        if r <= 0:
            k += 1
        else:
            if k:
                runs.append(k)
            k = 0
    if k:
        runs.append(k)
    years = max((pd.to_datetime(t.entry_time.iloc[-1]) - pd.to_datetime(t.entry_time.iloc[0])).days / 365.25, 1)
    return {"runs": runs, "longest": max(runs) if runs else 0, "years": years, "trades": len(t)}


def alert_text(label, n, hist):
    if not hist:
        return f"{label} has lost {n} trades in a row. It keeps trading normally."
    times = sum(1 for r in hist["runs"] if r >= n)
    yrs = f"{hist['years']:.0f} years"
    if times == 0:
        seen = (f"The tests never had a streak this long in {yrs} (longest {hist['longest']}), so this is "
                f"unusual - worth a look at the log.")
    else:
        seen = (f"In the tests this happened {times} time{'s' if times != 1 else ''} in {yrs} "
                f"(about {times / hist['years']:.1f} a year); the longest streak was {hist['longest']}.")
    return f"{label} has lost {n} trades in a row. {seen} It keeps trading normally."
