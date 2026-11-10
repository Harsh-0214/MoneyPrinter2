"""New York open breakout.

Build a 2-hour pre-NY consolidation range (11:00-13:00 London), then trade
the breakout between 13:00-15:00. Exit at 17:00. Same risk/entry logic as
the London Breakout but targeting the NY session momentum.
"""
from datetime import time

from ..brokers.base import Order


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class NYOpenBreakout:
    RANGE_START  = _minutes("11:00")
    RANGE_END    = _minutes("13:00")
    ENTRY_CUTOFF = _minutes("15:00")
    SESSION_EXIT = _minutes("17:00")

    def __init__(self, cfg, pip):
        self.pip = pip
        self.buffer   = cfg.get("buffer_pips",    1.0) * pip
        self.min_range = cfg.get("min_range_pips", 15)
        self.max_range = cfg.get("max_range_pips", 60)
        self.rr        = cfg["reward_risk"]
        self.stop_mode = cfg.get("stop_mode",      "range")
        self.atr_mult  = cfg.get("atr_stop_mult",  1.5)
        self.max_trades = cfg.get("max_trades_per_day", 1)
        raw_skip = cfg.get("skip_days", [])
        self._skip_days = set(int(d) for d in raw_skip)
        self.day = None

    def _reset_day(self, day):
        self.day = day
        self.hi = float("-inf")
        self.lo = float("inf")
        self.trades_today = 0

    def on_bar(self, bar, local_day, local_min, broker, risk):
        if local_day != self.day:
            self._reset_day(local_day)
            if self._skip_days:
                dow = int(local_day.astype("datetime64[D]").astype(object).weekday())
                if dow in self._skip_days:
                    self.trades_today = self.max_trades

        if self.RANGE_START <= local_min < self.RANGE_END:
            self.hi = max(self.hi, bar.high)
            self.lo = min(self.lo, bar.low)
            return

        if broker.position() is not None:
            if local_min >= self.SESSION_EXIT:
                broker.close_position("session_exit")
            return

        if self.trades_today >= self.max_trades:
            return
        if not (self.RANGE_END <= local_min < self.ENTRY_CUTOFF) or self.hi == float("-inf"):
            return
        width = (self.hi - self.lo) / self.pip
        if not (self.min_range <= width <= self.max_range):
            return
        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return

        spread_px = bar.spread_pips * self.pip
        if bar.close > self.hi + self.buffer:
            side, entry_est = 1, bar.close + spread_px
            stop = self.lo if self.stop_mode == "range" else entry_est - self.atr_mult * bar.atr
        elif bar.close < self.lo - self.buffer:
            side, entry_est = -1, bar.close
            stop = self.hi + spread_px if self.stop_mode == "range" else entry_est + self.atr_mult * bar.atr
        else:
            return

        if stop != stop:
            return
        dist = abs(entry_est - stop)
        if dist <= 0:
            return
        target = entry_est + side * self.rr * dist
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return
        if broker.submit(Order(side, units, stop, target, "ny_long" if side == 1 else "ny_short")):
            self.trades_today += 1
