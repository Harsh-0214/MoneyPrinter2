"""London-close reversal: fade a large one-way London move late in the session.

Idea: by mid/late afternoon London, a big directional day often partially
retraces as London desks square up around the 16:00 London fix.

Rules
-----
1. Reference price = open of the first bar at/after `ref_time` (08:00 London).
2. At `entry_time`, move = close - ref_open. If |move| >= min_move_pips, fade:
   up-move -> sell, down-move -> buy.
   Optional: require the close to be within `near_extreme_pips` of the
   session extreme (price is still stretched, not already retracing).
3. Stop: beyond the session extreme + stop_buffer, at least min_stop_pips and
   at most max_stop_pips from entry.
4. Target: retrace `target_frac` of the move back toward ref_open.
5. Close at `exit_time` (before the NY rollover spread widening).
"""
from datetime import time
from typing import Optional

from ..brokers.base import Order
from .proposal import TradeProposal, manages, move_stop_to_breakeven

NAME = "london_close_reversal"


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class LondonCloseReversal:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.ref_time     = _minutes(cfg.get("ref_time", "08:00"))
        self.entry_time   = _minutes(cfg.get("entry_time", "16:05"))
        self.entry_window = int(cfg.get("entry_window_min", 30))
        self.exit_time    = _minutes(cfg.get("exit_time", "19:00"))
        self.min_move     = cfg.get("min_move_pips", 40) * pip
        self.max_move     = cfg.get("max_move_pips", 200) * pip
        self.near_ext     = cfg.get("near_extreme_pips", None)
        self.near_ext     = self.near_ext * pip if self.near_ext is not None else None
        self.stop_buf     = cfg.get("stop_buffer_pips", 3.0) * pip
        self.min_stop     = cfg.get("min_stop_pips", 10.0) * pip
        self.max_stop     = cfg.get("max_stop_pips", 40.0) * pip
        self.target_frac  = cfg.get("target_frac", 0.38)
        # direction: "fade" (reversal, default) or "follow" (trade WITH the move:
        # fixed stop_pips stop, target = target_rr x risk or None = hold to exit)
        self.direction    = cfg.get("direction", "fade")
        self.stop_pips    = cfg.get("stop_pips", 20.0) * pip
        self.target_rr    = cfg.get("target_rr", None)
        self.min_rr       = cfg.get("min_rr", 0.0)
        self.trail_be_rr  = float(cfg.get("trail_to_breakeven_rr", 0.0))
        self.score        = float(cfg.get("score", 50))
        self.max_trades   = cfg.get("max_trades_per_day", 1)
        self._skip_days   = set(int(d) for d in cfg.get("skip_days", []))
        self._reset_day(None)

    def _reset_day(self, day):
        self.day = day
        self.ref_open = None
        self.hi, self.lo = float("-inf"), float("inf")
        self.trades_today = 0

    def _update(self, bar, day, lmin):
        if day != self.day:
            self._reset_day(day)
            if self._skip_days:
                dow = int(day.astype("datetime64[D]").astype(object).weekday())
                if dow in self._skip_days:
                    self.trades_today = self.max_trades
        if lmin >= self.ref_time:
            if self.ref_open is None:
                self.ref_open = bar.open
            self.hi = max(self.hi, bar.high)
            self.lo = min(self.lo, bar.low)

    def _follow_order(self, side, bar, broker, risk) -> Optional[Order]:
        spread = bar.spread_pips * self.pip
        entry = bar.close + (spread if side == 1 else 0.0)
        stop = entry - side * self.stop_pips - (0.0 if side == 1 else -spread)
        dist = abs(entry - stop)
        target = entry + side * self.target_rr * dist if self.target_rr else None
        eq = broker.equity()
        if not risk.can_trade(eq, bar.Index):
            return None
        units = risk.position_size(eq, entry, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        return Order(side, units, stop, target, "lcr_long" if side == 1 else "lcr_short")

    def _order(self, side, move, bar, broker, risk) -> Optional[Order]:
        spread = bar.spread_pips * self.pip
        if side == -1:
            entry = bar.close
            stop = max(self.hi + self.stop_buf + spread, entry + self.min_stop)
            dist = stop - entry
            target = entry - self.target_frac * abs(move)
            reward = entry - target
        else:
            entry = bar.close + spread
            stop = min(self.lo - self.stop_buf, entry - self.min_stop)
            dist = entry - stop
            target = entry + self.target_frac * abs(move)
            reward = target - entry
        if dist <= 0 or dist > self.max_stop or reward <= 0 or reward / dist < self.min_rr:
            return None
        eq = broker.equity()
        if not risk.can_trade(eq, bar.Index):
            return None
        units = risk.position_size(eq, entry, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        return Order(side, units, stop, target, "lcr_long" if side == 1 else "lcr_short")

    def propose(self, bar, day, lmin, broker, risk) -> Optional[TradeProposal]:
        self._update(bar, day, lmin)
        pos = broker.position()
        if pos is not None:
            if manages(pos, NAME):
                move_stop_to_breakeven(pos, broker, bar.close, self.trail_be_rr)
                if lmin >= self.exit_time:
                    broker.close_position("session_exit")
            return None
        if self.trades_today >= self.max_trades or self.ref_open is None:
            return None
        if not (self.entry_time <= lmin < self.entry_time + self.entry_window):
            return None
        move = bar.close - self.ref_open
        if not (self.min_move <= abs(move) <= self.max_move):
            return None
        if self.near_ext is not None:
            if move > 0 and self.hi - bar.close > self.near_ext:
                return None
            if move < 0 and bar.close - self.lo > self.near_ext:
                return None
        if self.direction == "follow":
            o = self._follow_order(1 if move > 0 else -1, bar, broker, risk)
        else:
            o = self._order(-1 if move > 0 else 1, move, bar, broker, risk)
        return TradeProposal(o, self.score, NAME) if o else None

    def mark_fired(self):
        self.trades_today += 1

    def on_bar(self, bar, day, lmin, broker, risk):
        p = self.propose(bar, day, lmin, broker, risk)
        if p and broker.submit(p.order):
            self.mark_fired()
