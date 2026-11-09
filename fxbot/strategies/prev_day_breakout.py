"""Previous Day High/Low breakout.

Yesterday's daily high and low become the range. If today's price breaks
above yesterday's high or below yesterday's low during the London/NY window,
we trade the continuation. Stop is at the other side of the prev-day range.
"""
from datetime import time

from ..brokers.base import Order


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class PrevDayBreakout:
    ENTRY_START  = _minutes("07:00")
    ENTRY_CUTOFF = _minutes("14:00")
    SESSION_EXIT = _minutes("16:00")

    def __init__(self, cfg, pip):
        self.pip = pip
        self.buffer    = cfg.get("buffer_pips",    1.0) * pip
        self.min_range = cfg.get("min_range_pips", 20)
        self.max_range = cfg.get("max_range_pips", 150)
        self.rr        = cfg["reward_risk"]
        self.max_trades = cfg.get("max_trades_per_day", 1)
        self.today = None
        self.today_hi = float("-inf")
        self.today_lo = float("inf")
        self.prev_hi = None
        self.prev_lo = None
        self.trades_today = 0

    def on_bar(self, bar, local_day, local_min, broker, risk):
        if local_day != self.today:
            if self.today_hi != float("-inf"):
                self.prev_hi = self.today_hi
                self.prev_lo = self.today_lo
            self.today = local_day
            self.today_hi = float("-inf")
            self.today_lo = float("inf")
            self.trades_today = 0

        self.today_hi = max(self.today_hi, bar.high)
        self.today_lo = min(self.today_lo, bar.low)

        if broker.position() is not None:
            if local_min >= self.SESSION_EXIT:
                broker.close_position("session_exit")
            return

        if self.prev_hi is None:
            return
        if self.trades_today >= self.max_trades:
            return
        if not (self.ENTRY_START <= local_min < self.ENTRY_CUTOFF):
            return

        width = (self.prev_hi - self.prev_lo) / self.pip
        if not (self.min_range <= width <= self.max_range):
            return
        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return

        spread_px = bar.spread_pips * self.pip
        if bar.close > self.prev_hi + self.buffer:
            side, entry_est = 1, bar.close + spread_px
            stop = self.prev_lo + spread_px
        elif bar.close < self.prev_lo - self.buffer:
            side, entry_est = -1, bar.close
            stop = self.prev_hi
        else:
            return

        dist = abs(entry_est - stop)
        if dist <= 0:
            return
        target = entry_est + side * self.rr * dist
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return
        label = "prev_long" if side == 1 else "prev_short"
        if broker.submit(Order(side, units, stop, target, label)):
            self.trades_today += 1
