"""A strategy must not manage (trail / session-exit) another strategy's position."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml

from fxbot.brokers.base import Position
from fxbot.data import PIP
from fxbot.strategies import LondonBreakout, LondonSweep


class _Broker:
    def __init__(self, tag):
        self.pos = Position(1, 10000, 1.1000, pd.Timestamp("2024-01-03 09:00", tz="UTC"),
                            1.0950, None, 0.0050, 0.0, tag)
        self.stop_moves, self.closes = [], []

    def position(self): return self.pos
    def update_stop(self, px): self.stop_moves.append(px)
    def close_position(self, reason=""): self.closes.append(reason)
    def equity(self): return 50000
    def current_spread_pips(self): return 1.0


def _bar(close):
    return SimpleNamespace(Index=pd.Timestamp("2024-01-03 16:05", tz="UTC"), open=close,
                           high=close, low=close, close=close, spread_pips=1.0)


def _specs():
    cfg = yaml.safe_load(open("config.yaml"))
    m = {s["name"]: dict(s) for s in cfg["strategies"]["morning"]}
    m["london_breakout"]["trail_to_breakeven_rr"] = 1.0
    return m


def test_sweep_ignores_breakout_position():
    b = _Broker("long_break")
    s = LondonSweep(_specs()["london_sweep"], PIP)
    # 2R in profit and past session exit: Sweep must do nothing to it
    s.propose(_bar(1.1100), np.datetime64("2024-01-03"), 16 * 60 + 5, b, None)
    assert b.stop_moves == [] and b.closes == []


def test_breakout_ignores_sweep_position():
    b = _Broker("sweep_long")
    s = LondonBreakout(_specs()["london_breakout"], PIP)
    s.propose(_bar(1.1100), np.datetime64("2024-01-03"), 16 * 60 + 5, b, None)
    assert b.stop_moves == [] and b.closes == []


def test_trailing_stop_only_tightens():
    from fxbot.strategies.proposal import TrailState, trail_stop
    b = _Broker("long_break")                        # long 1.1000, stop 1.0950 -> 1R = 50 pips
    tr = TrailState()
    for hi in (1.1040, 1.1060, 1.1100, 1.1080):      # peak +2R, then a pullback
        bar = SimpleNamespace(high=hi, low=hi - 0.0005)
        tr.update(b.pos, bar)
        trail_stop(b.pos, b, tr, start_r=1.0, dist_r=0.5)
        if b.stop_moves:
            b.pos.stop_loss = b.stop_moves[-1]
    # starts at +1.2R (1.1060 - 25p = 1.1035), then peak 1.1100 -> 1.1075; never loosens
    assert [round(x, 5) for x in b.stop_moves] == [1.1035, 1.1075]


def test_breakout_manages_own_position():
    b = _Broker("long_break")
    spec = _specs()["london_breakout"]
    s = LondonBreakout(spec, PIP)
    h, m = map(int, spec["session_exit"].split(":"))
    s.propose(_bar(1.1100), np.datetime64("2024-01-03"), h * 60 + m + 5, b, None)   # just past exit
    assert b.stop_moves == [1.1000]
    assert b.closes == ["session_exit"]


def test_breakout_without_time_exit_keeps_position():
    b = _Broker("long_break")
    spec = dict(_specs()["london_breakout"], session_exit=None)
    s = LondonBreakout(spec, PIP)
    s.propose(_bar(1.1100), np.datetime64("2024-01-03"), 23 * 60 + 55, b, None)
    assert b.closes == []
