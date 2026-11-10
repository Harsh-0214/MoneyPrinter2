"""Overnight swap: charged per 17:00 New York rollover, triple on Wednesday."""
from types import SimpleNamespace

import pandas as pd

from fxbot.brokers.base import Order
from fxbot.brokers.sim_broker import SimBroker


def _bar(ts):
    return SimpleNamespace(Index=pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
                           open=1.1, high=1.1001, low=1.0999, close=1.1, spread_pips=0.0)


def _hold(start, end, side=1):
    b = SimBroker(10000, swap_long_per_lot=-10.0, swap_short_per_lot=-2.0)
    b.on_bar(_bar(start))
    b.submit(Order(side, 100_000, 1.0 if side == 1 else 1.2, None, "trend_long"))
    for ts in pd.date_range(pd.Timestamp(start) + pd.Timedelta(hours=1), end, freq="1h"):
        b.on_bar(_bar(ts))
    return b


def test_one_night_monday_to_tuesday():
    b = _hold("2024-01-08 10:00", "2024-01-09 10:00")   # Mon -> Tue: crosses Mon 17:00
    assert abs(b.position().swap - (-10.0)) < 1e-9


def test_wednesday_counts_triple():
    b = _hold("2024-01-10 10:00", "2024-01-11 10:00")   # Wed 17:00 rollover
    assert abs(b.position().swap - (-30.0)) < 1e-9


def test_full_week_is_seven_nights():
    # Mon 10:00 -> next Mon 10:00: rollovers Mon,Tue,Wed(x3),Thu,Fri = 7 nights
    b = _hold("2024-01-08 10:00", "2024-01-15 10:00", side=-1)
    assert abs(b.position().swap - (-2.0 * 7)) < 1e-9


def test_swap_included_in_trade_pnl():
    b = _hold("2024-01-08 10:00", "2024-01-09 10:00")
    b.close_position("x")
    b.on_bar(_bar("2024-01-09 11:00"))
    t = b.trades[-1]
    assert abs(t.swap + 10.0) < 1e-9
    assert t.pnl < 0                      # flat price, spread 0 -> only swap
