"""London open breakout.

1. From range_start to range_end (London time) record the Asian session
   high and low.
2. Between range_end and entry_cutoff, if a bar CLOSES above high + buffer,
   buy; below low - buffer, sell.
3. Stop: other side of the range (or ATR-based). Target: reward_risk x stop.
4. Any open trade is closed at session_exit.

propose() — deferred execution for multi-strategy mode
-------------------------------------------------------
When used alongside a higher-priority strategy (e.g. LondonSweep), propose()
does NOT fire during the sweep window (08:00-10:30).  Instead it:
  1. Tracks whether a breakout occurred during 08:00-10:30 (without submitting)
  2. At defer_until (default 10:30) it checks: is the breakout still valid?
     If yes → returns a scored TradeProposal.
     If price reversed back inside the range → proposal is None (false breakout filtered).

This gives the Sweep a full 2.5-hour window to form.  Only if no Sweep fires
by 10:30 will the Breakout's proposal be executed.

on_bar() — immediate, single-strategy / test mode (unchanged behaviour)
------------------------------------------------------------------------
Fires as soon as bar.close crosses the range, exactly as before.  Tests
continue to use on_bar() and are unaffected.

Scoring
-------
Score = 60 base
  + 12  range < 20 pips (very tight = strong consolidation)
  +  7  range 20-25 pips
  +  3  range 25-30 pips
  +  min(breakout_distance_pips, 5)  (momentum confirmation)
Maximum: ~77 — always below LondonSweep minimum (100).
"""
from datetime import time
from typing import Optional

from ..brokers.base import Order
from .proposal import TradeProposal


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class LondonBreakout:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.range_start  = _minutes(cfg["range_start"])
        self.range_end    = _minutes(cfg["range_end"])
        self.entry_cutoff = _minutes(cfg["entry_cutoff"])
        self.session_exit = _minutes(cfg["session_exit"])
        # In multi-strategy mode, only propose after the sweep window closes
        self.defer_until  = _minutes(cfg.get("defer_until", "10:30"))
        self.buffer       = cfg["buffer_pips"] * pip
        self.min_range    = cfg["min_range_pips"]
        self.max_range    = cfg["max_range_pips"]
        self.stop_mode    = cfg.get("stop_mode", "range")
        self.atr_mult     = cfg.get("atr_stop_mult", 1.5)
        self.rr           = cfg["reward_risk"]
        self.max_trades   = cfg.get("max_trades_per_day", 1)
        self.ema_filter   = cfg.get("ema_filter", False)
        raw_skip = cfg.get("skip_days", [])
        self._skip_days   = set(int(d) for d in raw_skip)
        self.day          = None
        self._reset_day(None)

    def _reset_day(self, day):
        self.day  = day
        self.hi   = float("-inf")
        self.lo   = float("inf")
        self.trades_today        = 0
        # Deferred tracking: direction of the first valid breakout signal seen
        # during the pre-defer window.  0 = no breakout yet.
        self._deferred_side = 0

    # ------------------------------------------------------------------ #
    #  State update (pure — no broker side-effects)                       #
    # ------------------------------------------------------------------ #

    def _update_state(self, bar, local_day, local_min):
        if local_day != self.day:
            self._reset_day(local_day)
            if self._skip_days:
                dow = int(local_day.astype("datetime64[D]").astype(object).weekday())
                if dow in self._skip_days:
                    self.trades_today = self.max_trades

        if self.range_start <= local_min < self.range_end:
            self.hi = max(self.hi, bar.high)
            self.lo = min(self.lo, bar.low)
            return

        # Track deferred breakout during 08:00-defer_until (don't fire yet)
        if self.range_end <= local_min < self.defer_until and self._deferred_side == 0:
            if bar.close > self.hi + self.buffer:
                self._deferred_side = 1
            elif bar.close < self.lo - self.buffer:
                self._deferred_side = -1

    # ------------------------------------------------------------------ #
    #  Setup quality score                                                 #
    # ------------------------------------------------------------------ #

    def _compute_score(self, bar, side: int) -> float:
        """Score this breakout setup.  Always < 100 (below LondonSweep minimum)."""
        score = 60.0

        # Range tightness: strong consolidation → more reliable breakout
        range_pips = (self.hi - self.lo) / self.pip
        if range_pips < 20:
            score += 12
        elif range_pips < 25:
            score += 7
        elif range_pips < 30:
            score += 3

        # Breakout momentum: how far has price gone beyond the range?
        if side == 1:
            bp = (bar.close - self.hi) / self.pip
        else:
            bp = (self.lo - bar.close) / self.pip
        score += min(max(bp, 0), 5)

        return score

    # ------------------------------------------------------------------ #
    #  Order construction (read-only on broker/risk)                      #
    # ------------------------------------------------------------------ #

    def _build_long_order(self, bar, broker, risk) -> Optional[Order]:
        spread_px = bar.spread_pips * self.pip
        entry_est = bar.close + spread_px
        stop = self.lo if self.stop_mode == "range" \
            else entry_est - self.atr_mult * bar.atr
        if stop != stop:
            return None
        dist = abs(entry_est - stop)
        if dist <= 0:
            return None
        target = entry_est + self.rr * dist
        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return None
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        return Order(1, units, stop, target, "long_break")

    def _build_short_order(self, bar, broker, risk) -> Optional[Order]:
        spread_px = bar.spread_pips * self.pip
        entry_est = bar.close
        stop = self.hi + spread_px if self.stop_mode == "range" \
            else entry_est + self.atr_mult * bar.atr
        if stop != stop:
            return None
        dist = abs(entry_est - stop)
        if dist <= 0:
            return None
        target = entry_est - self.rr * dist
        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return None
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        return Order(-1, units, stop, target, "short_break")

    # ------------------------------------------------------------------ #
    #  Proposal (multi-strategy mode — deferred, no broker.submit)        #
    # ------------------------------------------------------------------ #

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        """Update state and return a scored TradeProposal once the sweep window
        has closed (defer_until).  Returns None during the sweep window so the
        Sweep strategy has priority.  Also returns None if the initial breakout
        signal has since reversed back inside the range (false breakout filter).
        """
        self._update_state(bar, local_day, local_min)

        if broker.position() is not None:
            if local_min >= self.session_exit:
                broker.close_position("session_exit")
            return None

        if self.hi == float("-inf"):
            return None
        if self.trades_today >= self.max_trades:
            return None

        # Only propose after the sweep window closes
        if local_min < self.defer_until or local_min >= self.entry_cutoff:
            return None

        # Range must be within configured bounds
        width = (self.hi - self.lo) / self.pip
        if not (self.min_range <= width <= self.max_range):
            return None

        # EMA trend filter (applies in deferred mode too)
        if self.ema_filter and hasattr(bar, "ema") and bar.ema == bar.ema:
            if self._deferred_side == 1 and bar.close < bar.ema:
                return None
            if self._deferred_side == -1 and bar.close > bar.ema:
                return None

        # A breakout must have been seen during the pre-defer window AND
        # price must still be on the right side at defer_until (false-breakout filter)
        if self._deferred_side == 1 and bar.close > self.hi + self.buffer:
            order = self._build_long_order(bar, broker, risk)
            if order:
                return TradeProposal(order, self._compute_score(bar, 1), "london_breakout")

        if self._deferred_side == -1 and bar.close < self.lo - self.buffer:
            order = self._build_short_order(bar, broker, risk)
            if order:
                return TradeProposal(order, self._compute_score(bar, -1), "london_breakout")

        return None

    def mark_fired(self):
        """Called by the multi-strategy engine after submitting this proposal."""
        self.trades_today += 1

    # ------------------------------------------------------------------ #
    #  Single-strategy / test interface (backward-compatible)             #
    # ------------------------------------------------------------------ #

    def on_bar(self, bar, local_day, local_min, broker, risk):
        """Fires immediately when breakout conditions are met (no deferral).
        Used by tests and single-strategy backtests."""
        self._update_state(bar, local_day, local_min)

        if broker.position() is not None:
            if local_min >= self.session_exit:
                broker.close_position("session_exit")
            return

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

        if self.ema_filter and hasattr(bar, "ema") and bar.ema == bar.ema:
            if bar.close > self.hi + self.buffer and bar.close < bar.ema:
                return
            if bar.close < self.lo - self.buffer and bar.close > bar.ema:
                return

        if bar.close > self.hi + self.buffer:
            order = self._build_long_order(bar, broker, risk)
            if order and broker.submit(order):
                self.trades_today += 1
        elif bar.close < self.lo - self.buffer:
            order = self._build_short_order(bar, broker, risk)
            if order and broker.submit(order):
                self.trades_today += 1
