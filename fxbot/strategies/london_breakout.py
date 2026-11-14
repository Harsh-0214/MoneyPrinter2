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
from .proposal import TradeProposal, TrailState, extend_target, manages, trail_stop


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class LondonBreakout:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.range_start  = _minutes(cfg["range_start"])
        self.range_end    = _minutes(cfg["range_end"])
        self.entry_cutoff = _minutes(cfg["entry_cutoff"])
        # session_exit: null = no time exit (trade ends only at its stop or target)
        self.session_exit = _minutes(cfg["session_exit"]) if cfg.get("session_exit") else 10**9
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
        # Max extension beyond range buffer at defer_until: skip overextended entries.
        # None = disabled (accept any extension).
        _ext = cfg.get("max_defer_extension_pips", None)
        self.max_defer_ext = _ext * pip if _ext is not None else None
        # Move stop to entry once price is this many R ahead. 0 = disabled.
        self.trail_be_rr  = float(cfg.get("trail_to_breakeven_rr", 0.0))
        # "Let it run": near the target with momentum -> move target out, lock profit
        self.ext_trigger  = float(cfg.get("extend_trigger", 0.0))     # 0 = off; e.g. 0.8 of the way
        self.ext_step_r   = float(cfg.get("extend_step_r", 1.0))      # target moves this many R further
        self.ext_lock_r   = float(cfg.get("extend_lock_r", 1.0))      # stop goes this many R behind price
        self.ext_momentum = float(cfg.get("extend_momentum", 0.0))    # bar must close in top X of its range
        self.daily_trend_filter = cfg.get("daily_trend_filter", False)
        # Trailing stop: after trail_start_r R of profit, keep the stop trail_dist_r R
        # behind the best price reached (0 = off).
        self.trail_start_r = float(cfg.get("trail_start_r", 0.0))
        self.trail_dist_r  = float(cfg.get("trail_dist_r", 1.0))
        self._trail = TrailState()
        self.day          = None
        self._reset_day(None)

    def _reset_day(self, day):
        self.day  = day
        self.hi   = float("-inf")
        self.lo   = float("inf")
        self.trades_today        = 0
        self.skip_today          = None
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
                    self.skip_today = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][dow]

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

    def _manage_open(self, bar, broker):
        """Breakeven + trailing stop for an open position (uses the ORIGINAL risk)."""
        pos = broker.position()
        self._trail.update(pos, bar)
        r = self._trail.init_risk
        if self.trail_be_rr > 0 and r:
            if (bar.close - pos.entry_price) * pos.side / r >= self.trail_be_rr:
                be = pos.entry_price
                if (pos.side == 1 and be > pos.stop_loss) or (pos.side == -1 and be < pos.stop_loss):
                    broker.update_stop(be)
                    pos = broker.position()
        trail_stop(pos, broker, self._trail, self.trail_start_r, self.trail_dist_r)
        pos = broker.position()
        if pos is not None:
            extend_target(pos, broker, bar, self._trail, self.ext_trigger, self.ext_step_r,
                          self.ext_lock_r, self.ext_momentum)

    def _stop_price(self, side, entry_est, bar, spread_px):
        """Stop for a breakout: range wall, range midpoint, or ATR multiple."""
        if self.stop_mode == "range":
            return self.lo if side == 1 else self.hi + spread_px
        if self.stop_mode == "mid":
            mid = (self.hi + self.lo) / 2
            return mid if side == 1 else mid + spread_px
        return entry_est - side * self.atr_mult * bar.atr

    def _build_long_order(self, bar, broker, risk) -> Optional[Order]:
        spread_px = bar.spread_pips * self.pip
        entry_est = bar.close + spread_px
        stop = self._stop_price(1, entry_est, bar, spread_px)
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
        stop = self._stop_price(-1, entry_est, bar, spread_px)
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
        self._daily_ema = getattr(bar, "daily_ema", float("nan"))
        self._last_close = bar.close

        if broker.position() is not None:
            # Leave the Sweep's positions to the Sweep (unknown tags still managed)
            if not manages(broker.position(), "london_breakout"):
                return None
            self._manage_open(bar, broker)
            if local_min >= self.session_exit:
                broker.close_position("session_exit")
            return None
        self._trail.reset()

        if self.hi == float("-inf"):
            return None
        if self.trades_today >= self.max_trades:
            return None

        # Only propose after the sweep window closes
        if local_min < self.defer_until or local_min >= self.entry_cutoff:
            return None

        side = self._deferred_side
        where = "above" if side == 1 else "below"
        # Range must be within configured bounds
        width = (self.hi - self.lo) / self.pip
        if not (self.min_range <= width <= self.max_range):
            if side:
                self.skip_note = ("range", f"price broke {where} the overnight range, but the range is "
                                           f"{width:.0f} pips and the rule allows {self.min_range}-{self.max_range}")
            return None

        # EMA trend filter (applies in deferred mode too)
        if self.ema_filter and hasattr(bar, "ema") and bar.ema == bar.ema:
            if self._deferred_side == 1 and bar.close < bar.ema:
                return None
            if self._deferred_side == -1 and bar.close > bar.ema:
                return None

        # Higher-timeframe bias: only trade in the direction of the daily trend
        # (prior days' closes vs their EMA; no lookahead - daily_ema uses closed days)
        if self.daily_trend_filter:
            de = getattr(bar, "daily_ema", float("nan"))
            if de == de:
                if (self._deferred_side == 1 and bar.close < de) or (self._deferred_side == -1 and bar.close > de):
                    self.skip_note = ("trend", f"price broke {where} the overnight range, but the 50-day trend "
                                               f"is {'DOWN' if side == 1 else 'UP'}, so it only "
                                               f"{'sells' if side == 1 else 'buys'} today")
                    return None

        # A breakout must have been seen during the pre-defer window AND
        # price must still be on the right side at defer_until (false-breakout filter)
        if self._deferred_side == 1 and bar.close > self.hi + self.buffer:
            if self.max_defer_ext is not None:
                if bar.close - (self.hi + self.buffer) > self.max_defer_ext:
                    self._note_extended(bar.close - (self.hi + self.buffer))
                    return None
            order = self._build_long_order(bar, broker, risk)
            if order:
                return TradeProposal(order, self._compute_score(bar, 1), "london_breakout")

        if self._deferred_side == -1 and bar.close < self.lo - self.buffer:
            if self.max_defer_ext is not None:
                if (self.lo - self.buffer) - bar.close > self.max_defer_ext:
                    self._note_extended((self.lo - self.buffer) - bar.close)
                    return None
            order = self._build_short_order(bar, broker, risk)
            if order:
                return TradeProposal(order, self._compute_score(bar, -1), "london_breakout")

        if side:
            self.skip_note = ("inside", f"price broke {where} the overnight range earlier but is back inside it "
                                        "(false-breakout filter); it can still enter before 11:00 if it breaks out again")
        return None

    def _note_extended(self, beyond):
        self.skip_note = ("ext", f"price is already {beyond / self.pip:.0f} pips past the overnight range, more "
                                 f"than the {self.max_defer_ext / self.pip:.0f}-pip limit (the move already ran)")

    def mark_fired(self):
        """Called by the multi-strategy engine after submitting this proposal."""
        self.trades_today += 1

    def describe(self, local_min=None):
        """Chart overlay: breakout trigger lines + what it's waiting for."""
        out = {"lines": [], "boxes": [], "status": "", "vlines": [
            {"min": self.defer_until, "label": "Breakout decides (still outside the range?)", "color": "seagreen"},
            {"min": self.entry_cutoff, "label": "No new London trades after this", "color": "dimgray"}]}
        if self.session_exit < 10**9:
            out["vlines"].append({"min": self.session_exit, "label": "Breakout trades closed", "color": "orangered"})
        if self.hi == float("-inf"):
            out["status"] = "Breakout: waiting for Asian range data"
            return out
        width = (self.hi - self.lo) / self.pip
        out["lines"] += [
            {"price": self.hi + self.buffer, "label": "breakout: buy zone", "color": "seagreen", "style": "dash"},
            {"price": self.lo - self.buffer, "label": "breakout: sell zone", "color": "seagreen", "style": "dash"},
        ]
        if self.skip_today:
            msg = f"skip day ({self.skip_today}s are skipped by config) - watching only"
        elif self.trades_today >= self.max_trades:
            msg = "traded today - done"
        elif not (self.min_range <= width <= self.max_range):
            msg = f"range {width:.0f}p outside {self.min_range}-{self.max_range}p -> no breakout today"
        elif local_min is not None and local_min < self.range_end:
            msg = f"range so far {width:.0f}p"
        elif self._deferred_side == 0:
            msg = f"range {width:.0f}p ok, no close outside it yet"
        else:
            d = "UP" if self._deferred_side == 1 else "DOWN"
            msg = f"broke {d}; at 10:30 will {'buy' if self._deferred_side == 1 else 'sell'} " \
                  f"if price is still outside (Sweep has priority)"
            de = getattr(self, "_daily_ema", float("nan"))
            if self.daily_trend_filter and de == de:
                against = (self._deferred_side == 1 and self._last_close < de) or \
                          (self._deferred_side == -1 and self._last_close > de)
                if against:
                    msg = f"broke {d} but that's against the daily trend -> no trade"
            if local_min is not None and local_min >= self.entry_cutoff:
                msg = "entry window closed"
        de = getattr(self, "_daily_ema", float("nan"))
        if self.daily_trend_filter and de == de:
            up = self._last_close > de
            out["lines"].append({"price": de, "label": "50-day average (daily trend)",
                                 "color": "silver", "style": "dot"})
            msg = ("daily trend UP (buys only); " if up else "daily trend DOWN (sells only); ") + msg
        out["status"] = "Breakout: " + msg
        return out

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
