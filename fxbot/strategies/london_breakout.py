"""London open breakout.

1. From range_start to range_end (London time) record the Asian session
   high and low.
2. Between range_end and entry_cutoff, if a bar CLOSES above high + buffer,
   buy; below low - buffer, sell. (Order fills at the next bar's open.)
3. Stop: other side of the range (or ATR-based). Target: reward_risk x stop.
4. Any open trade is closed at session_exit.

The strategy only sees the current bar and earlier ones, and only talks
to the broker interface, so the same code will run on MetaTrader.
"""
from datetime import time

from ..brokers.base import Order


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class LondonBreakout:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.range_start = _minutes(cfg["range_start"])
        self.range_end = _minutes(cfg["range_end"])
        self.entry_cutoff = _minutes(cfg["entry_cutoff"])
        self.session_exit = _minutes(cfg["session_exit"])
        self.buffer = cfg["buffer_pips"] * pip
        self.min_range = cfg["min_range_pips"]
        self.max_range = cfg["max_range_pips"]
        self.stop_mode = cfg.get("stop_mode", "range")
        self.atr_mult = cfg.get("atr_stop_mult", 1.5)
        self.rr = cfg["reward_risk"]
        self.max_trades = cfg.get("max_trades_per_day", 1)
        self.day = None
        self.skipped_days = 0

    def _reset_day(self, day):
        self.day = day
        self.hi = float("-inf")
        self.lo = float("inf")
        self.trades_today = 0

    def on_bar(self, bar, local_day, local_min, broker, risk):
        if local_day != self.day:
            self._reset_day(local_day)

        # 1) build the range
        if self.range_start <= local_min < self.range_end:
            self.hi = max(self.hi, bar.high)
            self.lo = min(self.lo, bar.low)
            return

        # 2) time exit
        if broker.position() is not None:
            if local_min >= self.session_exit:
                broker.close_position("session_exit")
            return

        # 3) look for a breakout
        if self.trades_today >= self.max_trades:
            return
        if not (self.range_end <= local_min < self.entry_cutoff) or self.hi == float("-inf"):
            return
        width = (self.hi - self.lo) / self.pip
        if not (self.min_range <= width <= self.max_range):
            return
        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return

        spread_px = bar.spread_pips * self.pip
        if bar.close > self.hi + self.buffer:
            side, entry_est = 1, bar.close + spread_px          # buy at ask
            stop = self.lo if self.stop_mode == "range" else entry_est - self.atr_mult * bar.atr
        elif bar.close < self.lo - self.buffer:
            side, entry_est = -1, bar.close                     # sell at bid
            stop = self.hi + spread_px if self.stop_mode == "range" else entry_est + self.atr_mult * bar.atr
        else:
            return

        if stop != stop:   # NaN ATR during warm-up
            return
        dist = abs(entry_est - stop)
        target = entry_est + side * self.rr * dist
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return
        if broker.submit(Order(side, units, stop, target, "long_break" if side == 1 else "short_break")):
            self.trades_today += 1
