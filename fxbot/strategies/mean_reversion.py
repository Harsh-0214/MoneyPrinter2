"""Mean reversion: fade the London open breakout back toward the Asian range midpoint.

The strategy bets that after price breaks out of the overnight Asian range,
it will snap back toward the midpoint rather than trend. This is the
OPPOSITE of London Breakout — instead of following the break, we fight it.

Entry: close outside Asian range after 08:00 London → trade the other way
Target: Asian range midpoint
Stop: mean_rev_stop_mult * range_width beyond the entry (default 1.5x)
Exit: 16:00 London
"""
from datetime import time

from ..brokers.base import Order


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class MeanReversion:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.range_start  = _minutes(cfg.get("range_start",  "00:00"))
        self.range_end    = _minutes(cfg.get("range_end",    "08:00"))
        self.entry_cutoff = _minutes(cfg.get("entry_cutoff", "11:00"))
        self.session_exit = _minutes(cfg.get("session_exit", "16:00"))
        self.buffer    = cfg.get("buffer_pips",         1.0) * pip
        self.min_range = cfg.get("min_range_pips",      15)
        self.max_range = cfg.get("max_range_pips",      60)
        self.stop_mult = cfg.get("mean_rev_stop_mult",  1.5)
        self.max_trades = cfg.get("max_trades_per_day", 1)
        self.day = None

    def _reset_day(self, day):
        self.day = day
        self.hi = float("-inf")
        self.lo = float("inf")
        self.trades_today = 0

    def on_bar(self, bar, local_day, local_min, broker, risk):
        if local_day != self.day:
            self._reset_day(local_day)

        if self.range_start <= local_min < self.range_end:
            self.hi = max(self.hi, bar.high)
            self.lo = min(self.lo, bar.low)
            return

        if broker.position() is not None:
            if local_min >= self.session_exit:
                broker.close_position("session_exit")
            return

        if self.trades_today >= self.max_trades:
            return
        if not (self.range_end <= local_min < self.entry_cutoff) or self.hi == float("-inf"):
            return
        width_pips = (self.hi - self.lo) / self.pip
        if not (self.min_range <= width_pips <= self.max_range):
            return
        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return

        range_px = self.hi - self.lo
        midpoint = (self.hi + self.lo) / 2
        spread_px = bar.spread_pips * self.pip

        if bar.close > self.hi + self.buffer:
            # Price broke upward → SHORT back toward midpoint
            side = -1
            entry_est = bar.close
            target = midpoint
            stop = entry_est + self.stop_mult * range_px
        elif bar.close < self.lo - self.buffer:
            # Price broke downward → LONG back toward midpoint
            side = 1
            entry_est = bar.close + spread_px
            target = midpoint
            stop = entry_est - self.stop_mult * range_px
        else:
            return

        dist_to_target = abs(entry_est - target)
        if dist_to_target <= 0:
            return
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return
        label = "rev_long" if side == 1 else "rev_short"
        if broker.submit(Order(side, units, stop, target, label)):
            self.trades_today += 1
