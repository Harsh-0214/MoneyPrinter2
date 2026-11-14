"""Nov 13 2026 research code: USDJPY breakout re-entry / add-on, gold intraday entry,
weekend-gap fade. Hand-driven bars so each rule is checked exactly."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml

from fxbot.backtest import run_backtest
from fxbot.data import generate_synthetic, resample
from fxbot.strategies.daily_patterns import VolBreakout
from fxbot.strategies.trend_follow import TrendFollow
from fxbot.strategies.weekend_gap import WeekendGap


class _Risk:
    def can_trade(self, eq, t): return True
    def position_size(self, eq, entry, stop, sp): return 10


class _Broker:
    def __init__(self): self.pos = None
    def position(self): return self.pos
    def equity(self): return 50000
    def current_spread_pips(self): return 0.0
    def close_position(self, reason="x"): self.pos = None
    def update_stop(self, s, tp=None): pass


def _bar(ts, o, h, l, c):
    return SimpleNamespace(Index=ts, open=o, high=h, low=l, close=c, spread_pips=0.0)


def _feed(strat, bars, broker, risk):
    """Drive propose() over (timestamp, o, h, l, c) rows; collect proposals."""
    out = []
    for ts, o, h, l, c in bars:
        local = ts.tz_convert("Europe/London")
        p = strat.propose(_bar(ts, o, h, l, c), np.datetime64(local.date()),
                          local.hour * 60 + local.minute, broker, risk)
        if p:
            out.append((ts, p))
            strat.mark_fired()
    return out


def _vbo_days():
    """Two London days of 15-min-ish bars: day 1 range 100-101 (open 100.5), day 2 opens 100.6."""
    t0 = pd.Timestamp("2024-01-09 00:00", tz="UTC")          # Tuesday (Monday is skipped)
    rows = []
    for k in range(24):                                      # day 1, flat: open 100.5, range 100-101
        rows.append((t0 + pd.Timedelta(hours=k), 100.5, 101.0, 100.0, 100.5))
    return t0, rows


def test_vbo_add_on_fires_beyond_level_with_stop_at_level():
    """k=0.5, stop_range 0.5, range 1.0: buy level = open + 0.5, main stop = level - 0.5,
    add-on trigger (add_on_r 1.0) = level + 0.5; its stop = the level."""
    s = VolBreakout(dict(k=0.5, stop_range=0.5, trend_sma=None, add_on_r=1.0,
                         entry_start="00:00", entry_end="23:00", exit_time="23:30"), 0.01)
    t0, rows = _vbo_days()
    d2 = t0 + pd.Timedelta(days=1)
    rows += [(d2, 100.6, 100.7, 100.5, 100.6),           # day 2 open 100.6 -> buy level 101.1
             (d2 + pd.Timedelta(hours=1), 100.6, 101.3, 100.6, 101.2),   # main breakout bar
             (d2 + pd.Timedelta(hours=2), 101.2, 101.5, 101.1, 101.4),   # not yet +1R (trigger 101.6)
             (d2 + pd.Timedelta(hours=3), 101.4, 101.8, 101.3, 101.7)]   # +1R -> add-on
    out = _feed(s, rows, _Broker(), _Risk())
    assert len(out) == 1
    ts, p = out[0]
    assert ts == d2 + pd.Timedelta(hours=3) and p.order.tag == "vbo_add_long"
    assert abs(p.order.stop_loss - 101.1) < 1e-9


def test_vbo_add_on_disarms_if_main_stop_hit_first():
    s = VolBreakout(dict(k=0.5, stop_range=0.5, trend_sma=None, add_on_r=1.0,
                         entry_start="00:00", entry_end="23:00", exit_time="23:30"), 0.01)
    t0, rows = _vbo_days()
    d2 = t0 + pd.Timedelta(days=1)
    rows += [(d2, 100.6, 100.7, 100.5, 100.6),
             (d2 + pd.Timedelta(hours=1), 100.6, 101.3, 100.6, 101.2),   # main breakout
             (d2 + pd.Timedelta(hours=2), 101.2, 101.2, 100.5, 100.7),   # low 100.5 < main stop 100.6
             (d2 + pd.Timedelta(hours=3), 100.7, 101.9, 100.7, 101.8)]   # would be past the trigger
    assert _feed(s, rows, _Broker(), _Risk()) == []


def test_vbo_re_entry_allows_a_second_trade_only_when_configured():
    for n, want in ((1, 1), (2, 2)):
        s = VolBreakout(dict(k=0.5, stop_range=0.5, trend_sma=None, max_trades_per_day=n,
                             entry_start="00:00", entry_end="23:00", exit_time="23:30"), 0.01)
        t0, rows = _vbo_days()
        d2 = t0 + pd.Timedelta(days=1)
        rows += [(d2, 100.6, 100.7, 100.5, 100.6),
                 (d2 + pd.Timedelta(hours=1), 100.6, 101.3, 100.6, 101.2),   # first breakout
                 (d2 + pd.Timedelta(hours=2), 101.2, 101.2, 100.4, 100.5),   # (stopped out)
                 (d2 + pd.Timedelta(hours=3), 100.5, 101.4, 100.5, 101.3)]   # breaks out again
        out = _feed(s, rows, _Broker(), _Risk())
        assert len(out) == want and all(p.order.tag == "vbo_long" for _, p in out)


def test_vbo_re_entry_in_the_backtest_is_capped_by_the_slot():
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["smt"] = {}
    cfg["slot_max_trades"] = 2
    cfg["strategies"] = {"morning": [{"name": "vol_breakout", "k": 0.3, "stop_range": 0.3,
                                      "trend_sma": None, "max_trades_per_day": 2,
                                      "entry_start": "01:00", "entry_end": "20:00", "exit_time": "21:00"}],
                         "afternoon": []}
    bars = resample(generate_synthetic(days=120, seed=7), "15min")
    t, eq = run_backtest(bars, cfg)
    per_day = pd.to_datetime(t.entry_time).dt.date.value_counts()
    assert per_day.max() == 2


def test_trend_intraday_entry_fires_on_the_hourly_close_once_per_day():
    s = TrendFollow(dict(signal="donchian", entry_days=5, exit_days=3, atr_days=3, stop_atr=2.0,
                         long_only=True, intraday_entry=True), 0.1)
    b, risk = _Broker(), _Risk()
    t0 = pd.Timestamp("2024-01-01 12:00", tz="UTC")
    rows = []
    for i in range(8):                                      # flat days 99-101
        rows.append((t0 + pd.Timedelta(days=i), 100, 101, 99, 100))
    d = t0 + pd.Timedelta(days=8)
    rows += [(d, 100, 100.5, 99.5, 100.2),                  # day 9 first bar: no signal
             (d + pd.Timedelta(hours=2), 100.2, 101.6, 100.1, 101.5),   # hourly close > 5-day high
             (d + pd.Timedelta(hours=3), 101.5, 102.5, 101.4, 102.4)]   # same day: no 2nd entry
    out = _feed(s, rows, b, risk)
    assert len(out) == 1
    ts, p = out[0]
    assert ts == d + pd.Timedelta(hours=2) and p.order.tag == "trend_long"
    assert abs(p.order.stop_loss - (101.5 - 2.0 * s.last_atr)) < 1e-9


def test_trend_without_intraday_entry_waits_for_the_daily_close():
    s = TrendFollow(dict(signal="donchian", entry_days=5, exit_days=3, atr_days=3, stop_atr=2.0,
                         long_only=True), 0.1)
    t0 = pd.Timestamp("2024-01-01 12:00", tz="UTC")
    rows = [(t0 + pd.Timedelta(days=i), 100, 101, 99, 100) for i in range(8)]
    d = t0 + pd.Timedelta(days=8)
    rows += [(d, 100, 100.5, 99.5, 100.2), (d + pd.Timedelta(hours=2), 100.2, 101.6, 100.1, 101.5)]
    assert _feed(s, rows, _Broker(), _Risk()) == []


def test_weekend_gap_fades_towards_friday_close():
    s = WeekendGap(dict(min_gap_atr=0.2, fill_frac=1.0, stop_rr=1.0, entry_delay_min=15,
                        entry_cutoff_hours=6, exit_time="20:00", atr_days=3), 0.0001)
    rows = []
    t = pd.Timestamp("2024-01-08 00:00", tz="UTC")           # Mon 8 .. Fri 12 Jan: 5-min bars
    for day in range(5):
        for k in range(0, 24 * 60, 5):
            ts = t + pd.Timedelta(days=day, minutes=k)
            rows.append((ts, 1.1000, 1.1050, 1.0950, 1.1000))   # daily range 100 pips -> ATR 0.0100
    sun = pd.Timestamp("2024-01-14 22:00", tz="UTC")            # Sunday reopen, +40 pips gap
    rows += [(sun, 1.1040, 1.1045, 1.1035, 1.1040),
             (sun + pd.Timedelta(minutes=5), 1.1040, 1.1045, 1.1035, 1.1040),
             (sun + pd.Timedelta(minutes=15), 1.1040, 1.1045, 1.1035, 1.1040)]   # >= 15 min later
    out = _feed(s, rows, _Broker(), _Risk())
    assert len(out) == 1
    ts, p = out[0]
    assert ts == sun + pd.Timedelta(minutes=15) and p.order.side == -1 and p.order.tag == "wgap_short"
    assert abs(p.order.take_profit - 1.1000) < 1e-9          # target = Friday close
    assert abs(p.order.stop_loss - 1.1080) < 1e-9            # 1:1 beyond the entry


def test_weekend_gap_skips_small_gaps():
    s = WeekendGap(dict(min_gap_atr=0.5, atr_days=3), 0.0001)
    rows = []
    t = pd.Timestamp("2024-01-08 00:00", tz="UTC")
    for day in range(5):
        for k in range(0, 24 * 60, 60):
            rows.append((t + pd.Timedelta(days=day, hours=k // 60), 1.1, 1.105, 1.095, 1.1))
    sun = pd.Timestamp("2024-01-14 22:00", tz="UTC")
    rows += [(sun + pd.Timedelta(minutes=m), 1.1010, 1.1012, 1.1008, 1.1010) for m in (0, 15, 30)]
    assert _feed(s, rows, _Broker(), _Risk()) == []


def test_vbo_trend_block_leaves_a_skip_note():
    """2-day trend falling (closes 102 then 100.5): a close above the buy level is blocked."""
    s = VolBreakout(dict(k=0.5, stop_range=0.5, trend_sma=2, entry_start="00:00", entry_end="23:00",
                         exit_time="23:30"), 0.01)
    t0 = pd.Timestamp("2024-01-08 00:00", tz="UTC")       # Monday (skip_days default: none)
    rows = [(t0 + pd.Timedelta(hours=k), 102.0, 102.5, 101.5, 102.0) for k in range(24)]
    d1 = t0 + pd.Timedelta(days=1)
    rows += [(d1 + pd.Timedelta(hours=k), 100.5, 101.0, 100.0, 100.5) for k in range(24)]
    d2 = t0 + pd.Timedelta(days=2)
    rows += [(d2, 100.6, 100.7, 100.5, 100.6),             # buy level 100.6 + 0.5 x 1.0 = 101.1
             (d2 + pd.Timedelta(hours=1), 100.6, 101.3, 100.6, 101.2)]
    assert _feed(s, rows, _Broker(), _Risk()) == []
    assert s.skip_note[0] == "trend" and "only sells are allowed" in s.skip_note[1]


def test_risk_manager_notes_daily_loss_and_tiny_size():
    from fxbot.risk import RiskManager
    cfg = yaml.safe_load(open("config.yaml"))["risk"]
    cfg = dict(cfg, news_filter=False)
    r = RiskManager(cfg, 0.0001, "EURUSD")
    r.new_day(10000)
    assert not r.can_trade(9000, pd.Timestamp("2025-01-07 10:00", tz="UTC"))
    assert r.skip_note[0] == "daily_loss"
    r.skip_note = None
    assert r.position_size(10, 1.1, 1.0) == 0 and r.skip_note[0] == "size"


def test_live_runner_says_each_skip_once_per_day():
    import logging
    from run_live import StrategyRunner
    said = []
    h = logging.Handler(); h.emit = lambda rec: said.append(rec.getMessage())
    nl = logging.getLogger("fxbot.narrate"); nl.addHandler(h); nl.setLevel(logging.INFO)
    try:
        r = StrategyRunner.__new__(StrategyRunner)
        r.label, r.log = "London", logging.getLogger("t")
        strat = SimpleNamespace(skip_note=("trend", "the trend is DOWN"))
        r.morning, r.risk, r._skip_seen = [strat], SimpleNamespace(skip_note=None), set()
        r._collect_skips(None)                       # startup replay: cleared, not said
        assert said == [] and strat.skip_note is None
        for _ in range(3):
            strat.skip_note = ("trend", "the trend is DOWN")
            r._collect_skips("2026-11-16")
        strat.skip_note = ("trend", "the trend is DOWN")
        r._collect_skips("2026-11-17")
        assert said == ["London did not trade: the trend is DOWN."] * 2
    finally:
        nl.removeHandler(h)
