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


def test_trend_add_on_waits_for_progress_and_stops_at_main_entry():
    """Add-on arms on the trend signal, buys only after +add_on_r R, stop = main entry."""
    import numpy as np
    import pandas as pd
    from types import SimpleNamespace
    from fxbot.strategies.trend_follow import TrendFollow
    class R:
        def can_trade(self, eq, t): return True
        def position_size(self, eq, entry, stop, sp): return 10
    class B:
        def __init__(self): self.pos = None
        def position(self): return self.pos
        def equity(self): return 50000
        def current_spread_pips(self): return 0.0
    s = TrendFollow(dict(signal="donchian", entry_days=5, exit_days=3, atr_days=3, stop_atr=2.0,
                         long_only=True, add_on_r=0.5), 0.1)
    b, risk, out = B(), R(), []
    t0 = pd.Timestamp("2024-01-01 12:00", tz="UTC")
    def day(i, h, l, c, hours=(12,)):
        for hr in hours:
            ts = t0 + pd.Timedelta(days=i, hours=hr - 12)
            bar = SimpleNamespace(Index=ts, open=c, high=h, low=l, close=c, spread_pips=0.0)
            p = s.propose(bar, np.datetime64(ts.date()), hr * 60, b, risk)
            if p: out.append((i, p.order.stop_loss, p.order.tag)); s.mark_fired()
    for i in range(8):                                  # flat range: 99-101, ATR ~2
        day(i, 101, 99, 100)
    day(8, 104, 100, 103.5)                             # breakout close 103.5
    day(9, 104, 103, 103.6)                             # signal day: armed, +0.5R not reached yet
    assert out == []
    side, trigger, stop, _ = s.armed                  # main "entry" = 103.6, 1R = 2 x ATR(2.67)
    assert side == 1 and abs(stop - 103.6) < 1e-9 and abs(trigger - (103.6 + 0.5 * 2 * s.last_atr)) < 1e-9
    day(10, 106, 103.5, 105.9)                          # not far enough yet (trigger ~106.3)
    assert out == []
    day(11, 107.5, 105.5, 107.0)                        # +0.5R reached -> add-on buys
    assert len(out) == 1 and out[0][2] == "trend_add"
    assert abs(out[0][1] - 103.6) < 1e-9                # its stop = the main trade's entry
    assert s.armed is None                              # one add-on per trend


def test_compounding_drawdown_uses_peak(monkeypatch):
    from types import SimpleNamespace
    import run_live
    monkeypatch.setattr(run_live.DrawdownBreaker, "peak", classmethod(lambda cls: 100000.0))
    mt5 = SimpleNamespace(account_info=lambda: SimpleNamespace(equity=90000.0))
    assert run_live.account_drawdown_pct(mt5, 50000) == 20.0                     # fixed $50k sizing
    assert run_live.account_drawdown_pct(mt5, 50000, compounding=True) == 10.0   # % of the peak
