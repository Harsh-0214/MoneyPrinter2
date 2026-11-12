"""Rule checks for the published setups in fxbot/strategies/raschke.py."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from fxbot.strategies.raschke import EightyTwenty, IDNR4, TurtleSoup


class _Risk:
    def can_trade(self, eq, t): return True
    def position_size(self, eq, entry, stop, sp): return 1000


class _Broker:
    pos = None
    def position(self): return self.pos
    def equity(self): return 50000
    def current_spread_pips(self): return 0.0


T0 = pd.Timestamp("2024-01-01 12:00", tz="UTC")


def _feed(strat, days, extra=()):
    """days: list of (open, high, low, close) completed days; extra: bars for the next day.
    Each completed day is fed as 4 bars (o, h, l, c) at 08:00-11:00 London."""
    b, out = _Broker(), []
    def bar(i, hr, o, h, l, c):
        ts = T0 + pd.offsets.BDay(i) + pd.Timedelta(hours=hr - 12)       # weekdays only
        p = strat.propose(SimpleNamespace(Index=ts, open=o, high=h, low=l, close=c, spread_pips=0.0),
                          np.datetime64(ts.date()), hr * 60, b, _Risk())
        if p:
            out.append(p.order); strat.mark_fired()
    for i, (o, h, l, c) in enumerate(days):
        bar(i, 8, o, o, o, o); bar(i, 9, o, h, o, h); bar(i, 10, h, h, l, l); bar(i, 11, l, l, c, c)
    n = len(days)
    for hr, (o, h, l, c) in zip(range(8, 8 + len(extra)), extra):
        bar(n, hr, o, h, l, c)
    return out


def _flat(n, lo=99.0, hi=101.0):
    return [(100.0, hi, lo, 100.0)] * n


def test_turtle_soup_buys_back_above_old_low():
    days = _flat(35)[:-6] + [(100, 101, 98.0, 100)] + _flat(4) + [(99.0, 99.2, 97.0, 97.5)]   # old low 98 (5d), close 97.5
    s = TurtleSoup(dict(lookback=20, min_age=4, entry_start="07:00", entry_end="16:00"), 0.01)
    assert _feed(s, days, extra=[(97.6, 97.9, 97.4, 97.8)]) == []                 # still below 98: waits
    s = TurtleSoup(dict(lookback=20, min_age=4, entry_start="07:00", entry_end="16:00"), 0.01)
    orders = _feed(s, days, extra=[(97.6, 98.5, 97.4, 98.3)])                     # closes back above 98
    assert len(orders) == 1 and orders[0].side == 1 and orders[0].stop_loss == 97.0
    assert abs(orders[0].take_profit - (98.3 + 2 * 1.3)) < 1e-9                  # 2R


def test_eighty_twenty_needs_probe_then_reclaim():
    days = _flat(35) + [(100.9, 101.0, 99.0, 99.1)]       # opened top 20%, closed bottom 20%
    s = EightyTwenty(dict(entry_start="07:00", entry_end="16:00"), 0.01)
    assert _feed(s, days, extra=[(99.2, 99.5, 99.1, 99.4)]) == []          # never traded below 99
    s = EightyTwenty(dict(entry_start="07:00", entry_end="16:00"), 0.01)
    orders = _feed(s, days, extra=[(99.2, 99.3, 98.6, 98.7), (98.7, 99.3, 98.7, 99.2)])
    assert len(orders) == 1 and orders[0].side == 1 and orders[0].stop_loss == 98.6


def test_id_nr4_brackets_inside_narrow_day():
    days = _flat(35) + [(100.0, 100.4, 99.7, 100.1)]      # inside and narrower than the last 3
    s = IDNR4(dict(entry_start="07:00", entry_end="16:00"), 0.01)
    orders = _feed(s, days, extra=[(100.1, 100.6, 100.0, 100.5)])
    assert len(orders) == 1 and orders[0].side == 1 and orders[0].stop_loss == 99.7


def test_td_sequential_fires_after_nine_lower_closes():
    from fxbot.strategies.raschke import TDSequential
    days = _flat(30) + [(100 - i, 100.5 - i, 99.0 - i, 99.5 - i) for i in range(1, 14)]   # long decline
    s = TDSequential(dict(count=9, trail_to_breakeven_rr=0.0, target_rr=None, entry_start="07:00",
                          entry_end="16:00"), 0.01)
    assert any(o.side == 1 for o in _feed(s, days[:-4], extra=[(96.0, 96.2, 95.8, 96.1)]))   # exactly 9th
    s = TDSequential(dict(count=9, entry_start="07:00", entry_end="16:00"), 0.01)
    assert _feed(s, days[:-6], extra=[(96.0, 96.2, 95.8, 96.1)]) == []                      # only 7 so far
