"""Checks that the simulator charges costs and fills stops the way we expect."""
from collections import namedtuple

import pandas as pd
import pytest

from fxbot.brokers import Order, SimBroker

Bar = namedtuple("Bar", "Index open high low close spread_pips")
PIP = 0.0001
T0 = pd.Timestamp("2024-01-02 08:00", tz="UTC")


def bar(i, o, h, l, c, spread=1.0):
    return Bar(T0 + pd.Timedelta(minutes=5 * i), o, h, l, c, spread)


def test_long_fills_at_next_open_plus_spread_and_slippage():
    b = SimBroker(10_000, slippage_pips=0.2)
    b.on_bar(bar(0, 1.1000, 1.1005, 1.0995, 1.1002))
    b.submit(Order(1, 10_000, stop_loss=1.0980, take_profit=1.1040))
    assert b.position() is None                      # not filled on the signal bar
    b.on_bar(bar(1, 1.1003, 1.1006, 1.1001, 1.1004))
    assert b.position().entry_price == pytest.approx(1.1003 + 1.0 * PIP + 0.2 * PIP)


def test_long_stop_loss_costs_about_one_r():
    b = SimBroker(10_000, slippage_pips=0.0)
    b.on_bar(bar(0, 1.1000, 1.1000, 1.1000, 1.1000))
    b.submit(Order(1, 10_000, stop_loss=1.0981))
    b.on_bar(bar(1, 1.1000, 1.1002, 1.0975, 1.0978))  # entry 1.1001 (ask), stop hit
    t = b.trades[0]
    assert t.exit_reason == "stop"
    assert t.pnl == pytest.approx((1.0981 - 1.1001) * 10_000)
    assert t.r_multiple == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open_not_stop():
    b = SimBroker(10_000)
    b.on_bar(bar(0, 1.1000, 1.1000, 1.1000, 1.1000))
    b.submit(Order(1, 10_000, stop_loss=1.0980))
    b.on_bar(bar(1, 1.1000, 1.1002, 1.0999, 1.1000))
    b.on_bar(bar(2, 1.0970, 1.0972, 1.0965, 1.0968))  # opens below the stop
    t = b.trades[0]
    assert t.exit_reason == "stop_gap"
    assert t.exit_price == pytest.approx(1.0970)


def test_short_target_exits_on_ask():
    b = SimBroker(10_000)
    b.on_bar(bar(0, 1.1000, 1.1000, 1.1000, 1.1000))
    b.submit(Order(-1, 10_000, stop_loss=1.1020, take_profit=1.0970))
    b.on_bar(bar(1, 1.1000, 1.1001, 1.0990, 1.0995))
    b.on_bar(bar(2, 1.0990, 1.0991, 1.0968, 1.0975))  # ask low = 1.0969 <= target
    t = b.trades[0]
    assert t.exit_reason == "target"
    assert t.pnl == pytest.approx((1.1000 - 1.0970) * 10_000)


def test_stop_wins_when_stop_and_target_hit_in_same_bar():
    b = SimBroker(10_000)
    b.on_bar(bar(0, 1.1000, 1.1000, 1.1000, 1.1000))
    b.submit(Order(1, 10_000, stop_loss=1.0990, take_profit=1.1020))
    b.on_bar(bar(1, 1.1000, 1.1030, 1.0985, 1.1000))
    assert b.trades[0].exit_reason == "stop"
