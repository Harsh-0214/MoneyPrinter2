"""Smoke tests for the tested-but-unused strategies: they run, tag trades
correctly, and lose on random data (no lookahead edge)."""
import copy

import pandas as pd
import yaml

from fxbot.backtest import run_backtest
from fxbot.data import generate_synthetic, resample


def _run(slot, spec):
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["smt"] = {}
    cfg["strategies"] = {"morning": [], "afternoon": []}
    cfg["strategies"][slot] = [spec]
    bars = resample(generate_synthetic(days=200), "5min")
    return run_backtest(bars, cfg)


def test_tiny_range_fade_runs_and_tags():
    t, eq = _run("morning", {"name": "tiny_range_fade", "mode": "immediate",
                             "max_range_pips": 30, "min_range_pips": 0})
    assert len(t) > 0
    assert set(t.tag) <= {"fade_long", "fade_short"}
    assert eq.iloc[-1] < eq.iloc[0]          # random walk: costs win


def test_trend_follow_holds_overnight_and_pays_swap():
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["smt"] = {}
    cfg["strategies"] = {"morning": [{"name": "trend_follow", "entry_days": 10,
                                      "exit_days": 5, "atr_days": 5}], "afternoon": []}
    bars = resample(generate_synthetic(days=300), "1h")
    t, eq = run_backtest(bars, cfg)
    assert len(t) > 0
    assert set(t.tag) <= {"trend_long", "trend_short"}
    held = (pd.to_datetime(t.exit_time) - pd.to_datetime(t.entry_time)).dt.days
    assert held.max() >= 1                     # multi-day holds happen
    assert (t.swap <= 0).all() and t.swap.sum() < 0   # pessimistic swap is charged


def test_opening_range_runs_and_tags():
    t, eq = _run("morning", {"name": "opening_range", "open_time": "13:30", "or_minutes": 15,
                             "entry_end": "15:30", "exit_time": "19:30", "tag": "orbny"})
    assert len(t) > 0
    assert set(t.tag) <= {"orbny_long", "orbny_short"}
    assert eq.iloc[-1] < eq.iloc[0]


def test_trend_pullback_can_trade_several_times_a_day():
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["smt"] = {}
    cfg["slot_max_trades"] = 3
    cfg["strategies"] = {"morning": [{"name": "trend_pullback", "daily_trend_filter": False,
                                      "max_trades_per_day": 3, "cooldown_bars": 1}],
                         "afternoon": []}
    bars = resample(generate_synthetic(days=60), "15min")
    t, eq = run_backtest(bars, cfg)
    assert len(t) > 0 and set(t.tag) <= {"pb_long", "pb_short"}
    per_day = pd.to_datetime(t.entry_time).dt.date.value_counts()
    assert per_day.max() >= 2 and per_day.max() <= 3      # several, but capped at 3


def test_gold_instrument_pip_and_units():
    """Gold: pip 0.1, units = ounces (min 1), P&L in USD."""
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["smt"] = {}
    cfg["instrument"] = {"pip": 0.1, "min_units": 1}
    cfg["costs"]["spread_pips"] = 8.0
    cfg["strategies"] = {"morning": [{"name": "opening_range", "open_time": "08:00",
                                      "or_minutes": 30, "entry_end": "11:00", "tag": "orbl"}],
                         "afternoon": []}
    raw = generate_synthetic(days=60, start_price=2000.0)
    raw[["open", "high", "low", "close"]] = 2000 + (raw[["open", "high", "low", "close"]] - 2000) * 1000
    t, eq = run_backtest(resample(raw, "5min"), cfg)
    assert len(t) > 0
    assert t.units.max() < 2000                   # ounces, not 1,000-unit FX lots
    assert t.units.min() >= 1


def test_london_close_reversal_both_directions():
    for d in ("fade", "follow"):
        t, eq = _run("afternoon", {"name": "london_close_reversal", "direction": d,
                                   "min_move_pips": 5, "target_rr": 1.5})
        assert len(t) > 0
        assert set(t.tag) <= {"lcr_long", "lcr_short"}
        assert eq.iloc[-1] < eq.iloc[0]
