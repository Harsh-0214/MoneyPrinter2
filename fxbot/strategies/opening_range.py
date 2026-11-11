"""Opening-range breakout (ORB) for any session open.

1. Opening range = high/low of the first `or_minutes` after `open_time` (London time).
   London open: open_time 08:00.  NY open: open_time 13:30 (US data at 08:30 NY
   = 13:30 London most of the year).
2. Until `entry_end`, the first bar that CLOSES beyond the range +/- buffer
   triggers a trade in that direction (optionally only with the daily trend).
3. Stop: other side of the opening range ("range") or its middle ("mid").
   Optional cap: skip if the stop is wider than max_stop_pips.
4. Target: target_rr x risk (None/0 = no target). Exit at `exit_time`.
"""
from datetime import time
from typing import Optional

from ..brokers.base import Order
from .proposal import TradeProposal, TrailState, manages, move_stop_to_breakeven

NAME = "opening_range"


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class OpeningRange:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.open_min    = _minutes(cfg.get("open_time", "08:00"))
        self.or_end      = self.open_min + int(cfg.get("or_minutes", 30))
        self.entry_end   = _minutes(cfg.get("entry_end", "11:00"))
        self.exit_min    = _minutes(cfg.get("exit_time", "16:00"))
        self.buffer      = cfg.get("buffer_pips", 0.5) * pip
        self.stop_mode   = cfg.get("stop_mode", "range")
        self.max_stop    = cfg.get("max_stop_pips", None)
        self.max_stop    = self.max_stop * pip if self.max_stop else None
        self.min_range   = cfg.get("min_range_pips", 0) * pip
        self.target_rr   = cfg.get("target_rr", 2.0)
        self.trend       = cfg.get("daily_trend_filter", False)
        self.be_rr       = float(cfg.get("trail_to_breakeven_rr", 0.0))
        self.score       = float(cfg.get("score", 70))
        self.max_trades  = int(cfg.get("max_trades_per_day", 1))
        self._skip_days  = set(int(d) for d in cfg.get("skip_days", []))
        self.tag_prefix  = cfg.get("tag", "orb")
        self._trail = TrailState()
        self.day = None
        self._reset(None)

    def _reset(self, day):
        self.day = day
        self.hi, self.lo = float("-inf"), float("inf")
        self.trades_today = 0
        self.skip_today = False

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        if local_day != self.day:
            self._reset(local_day)
            if self._skip_days:
                dow = int(local_day.astype("datetime64[D]").astype(object).weekday())
                self.skip_today = dow in self._skip_days
        if self.open_min <= local_min < self.or_end:
            self.hi = max(self.hi, bar.high)
            self.lo = min(self.lo, bar.low)

        pos = broker.position()
        if pos is not None:
            if manages(pos, NAME):
                self._trail.update(pos, bar)
                move_stop_to_breakeven(pos, broker, bar.close, self.be_rr)
                if local_min >= self.exit_min:
                    broker.close_position("session_exit")
            return None
        if self.skip_today or self.trades_today >= self.max_trades:
            return None
        if not (self.or_end <= local_min < self.entry_end) or self.hi == float("-inf"):
            return None
        if self.hi - self.lo < self.min_range:
            return None

        side = 1 if bar.close > self.hi + self.buffer else (-1 if bar.close < self.lo - self.buffer else 0)
        if side == 0:
            return None
        if self.trend:
            de = getattr(bar, "daily_ema", float("nan"))
            if de == de and ((side == 1 and bar.close < de) or (side == -1 and bar.close > de)):
                return None
        spread = bar.spread_pips * self.pip
        entry = bar.close + (spread if side == 1 else 0.0)
        if self.stop_mode == "mid":
            stop = (self.hi + self.lo) / 2
        else:
            stop = self.lo if side == 1 else self.hi
        if side == -1:
            stop += spread
        dist = (entry - stop) * side
        if dist <= 0 or (self.max_stop and dist > self.max_stop):
            return None
        target = entry + side * self.target_rr * dist if self.target_rr else None
        eq = broker.equity()
        if not risk.can_trade(eq, bar.Index):
            return None
        units = risk.position_size(eq, entry, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        self._trail.reset()
        return TradeProposal(Order(side, units, stop, target,
                                   f"{self.tag_prefix}_{'long' if side == 1 else 'short'}"),
                             self.score, NAME)

    def mark_fired(self):
        self.trades_today += 1

    def on_bar(self, bar, local_day, local_min, broker, risk):
        p = self.propose(bar, local_day, local_min, broker, risk)
        if p and broker.submit(p.order):
            self.mark_fired()
