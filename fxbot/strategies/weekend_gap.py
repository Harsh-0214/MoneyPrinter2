"""Weekend gap fade: when Sunday's open gaps away from Friday's close, trade back
towards Friday's close.

Why it might work: weekend gaps in FX and gold are mostly thin-liquidity moves that
get "filled" early in the week far more often than not. Why it might not: the
Sunday-open spread is wide, and the gaps that don't fill are the big news gaps.

Rules (decided before the test):
  * weekend = a gap of >= 40 hours between bars. Friday close = last close before
    it, Sunday open = first open after it. gap = open - Friday close.
  * entry: at the first bar closing >= `entry_delay_min` minutes after the reopen
    (spreads have narrowed), if the remaining gap (close vs Friday close) is still
    >= `min_gap_atr` x the 20-day ATR and in the same direction. Fade it.
  * target: Friday's close (`fill_frac` = 1.0) or part of the way (`fill_frac` 0.5).
  * stop: `stop_rr` x the remaining gap beyond the entry (1.0 = 1:1).
  * time exit: `exit_time` London on Monday if neither is hit.
One trade per weekend. Runs on 5/15-minute bars.
"""
from datetime import time
from typing import Optional

import pandas as pd

from ..brokers.base import Order
from .daily_patterns import _Daily, _order
from .proposal import TradeProposal, manages


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class WeekendGap:
    NAME = "weekend_gap"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.min_gap_atr = float(cfg.get("min_gap_atr", 0.2))
        self.fill_frac = float(cfg.get("fill_frac", 1.0))
        self.stop_rr = float(cfg.get("stop_rr", 1.0))
        self.delay = int(cfg.get("entry_delay_min", 15))
        self.entry_cutoff_h = float(cfg.get("entry_cutoff_hours", 6))   # hours after the reopen
        self.exit_min = _minutes(cfg.get("exit_time", "20:00"))
        self.atr_n = int(cfg.get("atr_days", 20))
        self.score = float(cfg.get("score", 50))
        self.d = _Daily()
        self.prev_time = None
        self.prev_close = None
        self.gap = None            # (friday_close, reopen_time, sign)
        self.traded = False

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        self.d.update(bar, local_day)
        t = bar.Index
        if self.prev_time is not None and (t - self.prev_time) >= pd.Timedelta(hours=40):
            g = bar.open - self.prev_close
            self.gap = (self.prev_close, t, 1 if g > 0 else (-1 if g < 0 else 0))
            self.traded = False
        self.prev_time, self.prev_close = t, bar.close

        pos = broker.position()
        if pos is not None:
            if manages(pos, self.NAME) and local_min >= self.exit_min and local_day.astype(
                    "datetime64[D]").astype(object).weekday() == 0:
                broker.close_position("session_exit")
            return None
        if self.traded or not self.gap or self.gap[2] == 0:
            return None
        fri_close, t0, sign = self.gap
        age = (t - t0) / pd.Timedelta(minutes=1)
        if age < self.delay:
            return None
        if age > self.entry_cutoff_h * 60:
            self.traded = True
            return None
        atr = self.d.atr(self.atr_n)
        if atr is None:
            return None
        remaining = (bar.close - fri_close) * sign
        if remaining < self.min_gap_atr * atr:
            self.traded = True            # already filled (or too small): nothing to fade
            return None
        side = -sign
        target = bar.close + side * self.fill_frac * remaining
        stop = bar.close - side * self.stop_rr * remaining
        o = _order(side, bar.close, stop, target, bar, self.pip, broker, risk,
                   "wgap_long" if side == 1 else "wgap_short")
        return TradeProposal(o, self.score, self.NAME) if o else None

    def mark_fired(self):
        self.traded = True

    def describe(self, local_min=None):
        out = {"lines": [], "boxes": [], "status": "Weekend gap: waiting for the Sunday open"}
        if self.gap:
            fri, t0, sign = self.gap
            out["lines"].append({"price": fri, "label": "Friday close (gap target)", "color": "silver",
                                 "style": "dot"})
            out["status"] = (f"Weekend gap: {'up' if sign > 0 else 'down'} gap from {fri:.5f}; "
                             + ("traded / done" if self.traded else "fade it if still open"))
        return out

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()
