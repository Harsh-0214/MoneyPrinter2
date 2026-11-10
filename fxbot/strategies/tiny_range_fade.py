"""Tiny-range fade: trade breakouts of very tight Asian ranges BACK into the range.

Motivation: in the 2021-2025 data, London Breakout trades from Asian ranges
under ~15 pips lost in every period on both pairs. A very tight range tends to
produce a false break: price pokes out, runs stops, and returns.

Rules
-----
1. Asian range 00:00-08:00 London; trade only if min_range <= width <= max_range.
2. Trigger (mode):
     immediate : first bar between 08:00 and trigger_end that CLOSES beyond
                 range +/- buffer -> fade it on that bar.
     deferred  : a break is seen 08:00-defer_until, and at defer_until price
                 is STILL beyond the range -> fade then (the exact trades the
                 Breakout used to lose on).
3. Stop: beyond the day's extreme since 08:00 + stop_buffer, at least
   min_stop_pips and at most max_stop_pips from entry.
4. Target: range midpoint ("mid") or the opposite side ("opposite").
5. Close at session_exit if still open.
"""
from datetime import time
from typing import Optional

from ..brokers.base import Order
from .proposal import TradeProposal, manages, move_stop_to_breakeven

NAME = "tiny_range_fade"


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class TinyRangeFade:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.range_start  = _minutes(cfg.get("range_start", "00:00"))
        self.range_end    = _minutes(cfg.get("range_end", "08:00"))
        self.mode         = cfg.get("mode", "immediate")
        self.trigger_end  = _minutes(cfg.get("trigger_end", "10:30"))
        self.defer_until  = _minutes(cfg.get("defer_until", "10:30"))
        self.entry_cutoff = _minutes(cfg.get("entry_cutoff", "11:00"))
        self.session_exit = _minutes(cfg.get("session_exit", "16:00"))
        self.min_range    = cfg.get("min_range_pips", 5)
        self.max_range    = cfg.get("max_range_pips", 15)
        self.buffer       = cfg.get("buffer_pips", 0.5) * pip
        self.stop_buf     = cfg.get("stop_buffer_pips", 2.0) * pip
        self.min_stop     = cfg.get("min_stop_pips", 8.0) * pip
        self.max_stop     = cfg.get("max_stop_pips", 25.0) * pip
        self.target_mode  = cfg.get("target", "mid")
        self.min_rr       = cfg.get("min_rr", 0.0)
        self.trail_be_rr  = float(cfg.get("trail_to_breakeven_rr", 0.0))
        self.score        = float(cfg.get("score", 90))   # below Sweep (100+), above Breakout
        self.max_trades   = cfg.get("max_trades_per_day", 1)
        self._skip_days   = set(int(d) for d in cfg.get("skip_days", []))
        self._reset_day(None)

    def _reset_day(self, day):
        self.day = day
        self.hi, self.lo = float("-inf"), float("inf")
        self.sess_hi, self.sess_lo = float("-inf"), float("inf")
        self.break_side = 0          # +1 broke up, -1 broke down (first break)
        self.trades_today = 0

    def _update(self, bar, day, lmin):
        if day != self.day:
            self._reset_day(day)
            if self._skip_days:
                dow = int(day.astype("datetime64[D]").astype(object).weekday())
                if dow in self._skip_days:
                    self.trades_today = self.max_trades
        if self.range_start <= lmin < self.range_end:
            self.hi = max(self.hi, bar.high)
            self.lo = min(self.lo, bar.low)
            return
        if lmin >= self.range_end:
            self.sess_hi = max(self.sess_hi, bar.high)
            self.sess_lo = min(self.sess_lo, bar.low)
        if self.break_side == 0 and self.range_end <= lmin < self.trigger_end \
                and self.hi != float("-inf"):
            if bar.close > self.hi + self.buffer:
                self.break_side = 1
            elif bar.close < self.lo - self.buffer:
                self.break_side = -1

    def _order(self, side, bar, broker, risk) -> Optional[Order]:
        spread = bar.spread_pips * self.pip
        if side == -1:                        # fade an up-break: sell
            entry = bar.close
            stop = self.sess_hi + self.stop_buf + spread
            stop = max(stop, entry + self.min_stop)
            dist = stop - entry
            target = (self.hi + self.lo) / 2 if self.target_mode == "mid" else self.lo
            reward = entry - target
        else:                                 # fade a down-break: buy
            entry = bar.close + spread
            stop = self.sess_lo - self.stop_buf
            stop = min(stop, entry - self.min_stop)
            dist = entry - stop
            target = (self.hi + self.lo) / 2 if self.target_mode == "mid" else self.hi
            reward = target - entry
        if dist <= 0 or dist > self.max_stop or reward <= 0:
            return None
        if reward / dist < self.min_rr:
            return None
        eq = broker.equity()
        if not risk.can_trade(eq, bar.Index):
            return None
        units = risk.position_size(eq, entry, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        return Order(side, units, stop, target, "fade_long" if side == 1 else "fade_short")

    def propose(self, bar, day, lmin, broker, risk) -> Optional[TradeProposal]:
        self._update(bar, day, lmin)
        pos = broker.position()
        if pos is not None:
            if manages(pos, NAME):
                move_stop_to_breakeven(pos, broker, bar.close, self.trail_be_rr)
                if lmin >= self.session_exit:
                    broker.close_position("session_exit")
            return None
        if self.trades_today >= self.max_trades or self.hi == float("-inf"):
            return None
        width = (self.hi - self.lo) / self.pip
        if not (self.min_range <= width <= self.max_range):
            return None
        if self.break_side == 0:
            return None
        side = -self.break_side
        if self.mode == "immediate":
            # fire on the break bar itself (still beyond the range now)
            if not (self.range_end <= lmin < self.trigger_end):
                return None
            beyond = bar.close > self.hi + self.buffer if self.break_side == 1 \
                else bar.close < self.lo - self.buffer
            if not beyond:
                return None
        else:   # deferred
            if not (self.defer_until <= lmin < self.entry_cutoff):
                return None
            still = bar.close > self.hi + self.buffer if self.break_side == 1 \
                else bar.close < self.lo - self.buffer
            if not still:
                return None
        o = self._order(side, bar, broker, risk)
        return TradeProposal(o, self.score, NAME) if o else None

    def mark_fired(self):
        self.trades_today += 1

    def on_bar(self, bar, day, lmin, broker, risk):
        p = self.propose(bar, day, lmin, broker, risk)
        if p and broker.submit(p.order):
            self.mark_fired()
