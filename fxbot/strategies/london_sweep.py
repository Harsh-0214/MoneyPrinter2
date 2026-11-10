"""London open liquidity sweep reversal (ICT / TJR-style).

Setup overview
--------------
1. Build Asian range 00:00-08:00 London.
2. During the sweep window (08:00-10:30) price "sweeps" just past the
   Asian high or low, running stop-losses.
3. We wait for a confirmed Break-of-Structure (BOS) — a bar close back
   through a swing low/high that formed BEFORE the sweep extreme — then
   trade the reversal.

Lookahead rule
--------------
A swing low at bar i is only confirmed once bar i+swing_k has closed.
The strategy never peeks at future bars.

Scoring (propose() / multi-strategy mode)
------------------------------------------
Score = 100 base
  + 20  if SMT divergence confirmed (EUR swept but GBP did NOT)
  + 10  if Asian range is tight (< 15 pips)
  +  5  if Asian range is moderate (15-25 pips)
Minimum: 100  Maximum: ~130

Always higher than LondonBreakout (60-80), so the Sweep wins whenever
both strategies have a valid setup on the same bar.
"""
from datetime import time
from typing import Optional

from ..brokers.base import Order
from .proposal import TradeProposal, manages


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class LondonSweep:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.range_start  = _minutes(cfg.get("range_start",          "00:00"))
        self.range_end    = _minutes(cfg.get("range_end",            "08:00"))
        self.sweep_start  = _minutes(cfg.get("sweep_window_start",   "08:00"))
        self.sweep_end    = _minutes(cfg.get("sweep_window_end",     "10:30"))
        self.entry_cutoff = _minutes(cfg.get("entry_cutoff",         "11:00"))
        self.session_exit = _minutes(cfg.get("session_exit",         "16:00"))

        self.sweep_min    = cfg.get("sweep_min_pips",           1.0) * pip
        self.sweep_max    = cfg.get("sweep_max_pips",          15.0) * pip
        self.swing_k      = int(cfg.get("swing_k",               2))
        self.bos_buf      = cfg.get("bos_buffer_pips",          0.5) * pip
        self.max_bars_bos = int(cfg.get("max_bars_after_sweep", 12))
        self.req_inside   = cfg.get("require_close_inside_range", True)
        self.stop_buf     = cfg.get("stop_buffer_pips",          1.0) * pip
        self.max_stop_px  = cfg.get("max_stop_pips",            25.0) * pip
        self.target_mode  = cfg.get("target_mode",    "opposite_range")
        self.rr           = cfg.get("reward_risk",               2.0)
        self.min_rr       = cfg.get("min_rr",                    1.5)
        self.max_trades   = cfg.get("max_trades_per_day",          1)
        self.ema_filter   = cfg.get("ema_filter",               False)
        raw_skip = cfg.get("skip_days", [])
        self._skip_days   = set(int(d) for d in raw_skip)
        self.smt_filter   = cfg.get("smt_filter",              False)
        self.smt_min      = cfg.get("smt_min_pips",             1.0) * pip
        # Trailing stop: move stop to breakeven when price moves this many R in our favour.
        # 0 = disabled.
        self.trail_be_rr  = float(cfg.get("trail_to_breakeven_rr", 0.0))

        self.day = None
        self._reset_day(None)

    # ------------------------------------------------------------------ #
    #  Day state                                                           #
    # ------------------------------------------------------------------ #

    def _reset_day(self, day):
        self.day      = day
        self.asian_hi = float("-inf")
        self.asian_lo = float("inf")
        self._bars    = []
        self._sw_lows  = []
        self._sw_highs = []
        self.high_swept  = False
        self.high_failed = False
        self.ext_hi      = float("-inf")
        self.ext_hi_idx  = None
        self.low_swept   = False
        self.low_failed  = False
        self.ext_lo      = float("inf")
        self.ext_lo_idx  = None
        self.trades_today = 0
        self.smt_asian_hi = float("-inf")
        self.smt_asian_lo = float("inf")
        self.smt_hi_swept = False
        self.smt_lo_swept = False

    # ------------------------------------------------------------------ #
    #  Swing detection (no lookahead)                                     #
    # ------------------------------------------------------------------ #

    def _try_confirm_swing(self, candidate_idx):
        k    = self.swing_k
        bars = self._bars
        if candidate_idx < k:
            return
        if candidate_idx + k >= len(bars):
            return

        lo = bars[candidate_idx].low
        hi = bars[candidate_idx].high

        is_sw_low = all(
            bars[j].low > lo
            for j in range(candidate_idx - k, candidate_idx + k + 1)
            if j != candidate_idx
        )
        if is_sw_low:
            self._sw_lows.append((candidate_idx, lo))

        is_sw_high = all(
            bars[j].high < hi
            for j in range(candidate_idx - k, candidate_idx + k + 1)
            if j != candidate_idx
        )
        if is_sw_high:
            self._sw_highs.append((candidate_idx, hi))

    def _last_sw_low_before(self, before_bar_idx):
        result = None
        for idx, lo in self._sw_lows:
            if idx < before_bar_idx:
                result = (idx, lo)
        return result

    def _last_sw_high_before(self, before_bar_idx):
        result = None
        for idx, hi in self._sw_highs:
            if idx < before_bar_idx:
                result = (idx, hi)
        return result

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

        self._bars.append(bar)
        bar_idx = len(self._bars) - 1
        candidate = bar_idx - self.swing_k
        if candidate >= 0:
            self._try_confirm_swing(candidate)

        if self.range_start <= local_min < self.range_end:
            self.asian_hi = max(self.asian_hi, bar.high)
            self.asian_lo = min(self.asian_lo, bar.low)
            if self.smt_filter:
                sh = getattr(bar, "smt_high", float("nan"))
                sl = getattr(bar, "smt_low",  float("nan"))
                if sh == sh:
                    self.smt_asian_hi = max(self.smt_asian_hi, sh)
                if sl == sl:
                    self.smt_asian_lo = min(self.smt_asian_lo, sl)

        if self.smt_filter and self.sweep_start <= local_min < self.sweep_end:
            sh = getattr(bar, "smt_high", float("nan"))
            sl = getattr(bar, "smt_low",  float("nan"))
            if sh == sh and self.smt_asian_hi != float("-inf"):
                if sh > self.smt_asian_hi + self.smt_min:
                    self.smt_hi_swept = True
            if sl == sl and self.smt_asian_lo != float("inf"):
                if sl < self.smt_asian_lo - self.smt_min:
                    self.smt_lo_swept = True

        if self.sweep_start <= local_min < self.sweep_end:
            if not self.high_failed:
                if bar.high > self.asian_hi + self.sweep_max:
                    self.high_failed = True
                    self.high_swept  = False
                elif bar.high > self.asian_hi + self.sweep_min:
                    self.high_swept = True
                    if bar.high > self.ext_hi:
                        self.ext_hi     = bar.high
                        self.ext_hi_idx = bar_idx

            if not self.low_failed:
                if bar.low < self.asian_lo - self.sweep_max:
                    self.low_failed = True
                    self.low_swept  = False
                elif bar.low < self.asian_lo - self.sweep_min:
                    self.low_swept = True
                    if bar.low < self.ext_lo:
                        self.ext_lo     = bar.low
                        self.ext_lo_idx = bar_idx

    # ------------------------------------------------------------------ #
    #  Setup quality score                                                 #
    # ------------------------------------------------------------------ #

    def _compute_score(self, side: int) -> float:
        """Score this sweep setup.  Always >= 100; always beats Breakout (60-80)."""
        score = 100.0

        # SMT divergence: EUR swept its range but GBP did NOT → genuine stop hunt
        if self.smt_filter:
            smt_data_ok = self.smt_asian_hi != float("-inf")
            if smt_data_ok:
                if side == -1 and not self.smt_hi_swept:
                    score += 20
                elif side == 1 and not self.smt_lo_swept:
                    score += 20

        # Tight Asian range → more precise key levels
        range_pips = (self.asian_hi - self.asian_lo) / self.pip
        if range_pips < 15:
            score += 10
        elif range_pips < 25:
            score += 5

        return score

    # ------------------------------------------------------------------ #
    #  Order construction (read-only on broker/risk)                      #
    # ------------------------------------------------------------------ #

    def _build_short_order(self, bar, broker, risk) -> Optional[Order]:
        spread_px = bar.spread_pips * self.pip
        entry_est = bar.close
        stop      = self.ext_hi + self.stop_buf + spread_px
        stop_dist = stop - entry_est
        if stop_dist <= 0 or stop_dist > self.max_stop_px:
            return None

        target = self.asian_lo if self.target_mode == "opposite_range" \
            else entry_est - self.rr * stop_dist
        rr_actual = (entry_est - target) / stop_dist if stop_dist > 0 else 0
        if rr_actual < self.min_rr:
            return None

        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return None
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        return Order(-1, units, stop, target, "sweep_short")

    def _build_long_order(self, bar, broker, risk) -> Optional[Order]:
        spread_px = bar.spread_pips * self.pip
        entry_est = bar.close + spread_px
        stop      = self.ext_lo - self.stop_buf
        stop_dist = entry_est - stop
        if stop_dist <= 0 or stop_dist > self.max_stop_px:
            return None

        target = self.asian_hi if self.target_mode == "opposite_range" \
            else entry_est + self.rr * stop_dist
        rr_actual = (target - entry_est) / stop_dist if stop_dist > 0 else 0
        if rr_actual < self.min_rr:
            return None

        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return None
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        return Order(1, units, stop, target, "sweep_long")

    # ------------------------------------------------------------------ #
    #  Proposal (multi-strategy mode — no broker.submit)                  #
    # ------------------------------------------------------------------ #

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        """Update state and return a scored TradeProposal if a valid BOS entry
        exists on this bar.  Does NOT call broker.submit().

        In multi-strategy mode the backtest engine collects proposals from all
        morning strategies and executes the highest-scoring one.
        """
        self._update_state(bar, local_day, local_min)

        # Session exit is handled here even in propose() so positions close on time
        if broker.position() is not None:
            pos = broker.position()
            # Only manage positions this strategy opened (another strategy may
            # own the open position in multi-strategy mode). Unknown tags are
            # still managed so a position is never left without a session exit.
            if not manages(pos, "london_sweep"):
                return None
            # Trailing stop: move stop to breakeven once price is 1R ahead
            # (risk_per_unit is 0 on MT5 once the stop already sits at entry)
            if self.trail_be_rr > 0 and pos.risk_per_unit > 0:
                profit_in_r = (bar.close - pos.entry_price) * pos.side / pos.risk_per_unit
                if profit_in_r >= self.trail_be_rr:
                    new_stop = pos.entry_price
                    if (pos.side == 1 and new_stop > pos.stop_loss) or \
                       (pos.side == -1 and new_stop < pos.stop_loss):
                        broker.update_stop(new_stop)
            if local_min >= self.session_exit:
                broker.close_position("session_exit")
            return None

        if self.asian_hi == float("-inf"):
            return None
        if self.trades_today >= self.max_trades:
            return None
        if local_min >= self.entry_cutoff or local_min < self.range_end:
            return None

        daily_ema = getattr(bar, "daily_ema", float("nan"))
        ema_ok_short = (not self.ema_filter) or (daily_ema == daily_ema and bar.close < daily_ema)
        ema_ok_long  = (not self.ema_filter) or (daily_ema == daily_ema and bar.close > daily_ema)

        smt_data_ok  = (not self.smt_filter) or (self.smt_asian_hi != float("-inf"))
        smt_ok_short = (not self.smt_filter) or (not smt_data_ok) or (not self.smt_hi_swept)
        smt_ok_long  = (not self.smt_filter) or (not smt_data_ok) or (not self.smt_lo_swept)

        bar_idx = len(self._bars) - 1

        if ema_ok_short and smt_ok_short and self.high_swept and not self.high_failed \
                and self.ext_hi_idx is not None:
            if bar_idx - self.ext_hi_idx <= self.max_bars_bos:
                sw = self._last_sw_low_before(self.ext_hi_idx)
                if sw is not None:
                    _, sw_lo = sw
                    if bar.close < sw_lo - self.bos_buf:
                        close_ok = (not self.req_inside) or (bar.close < self.asian_hi)
                        if close_ok:
                            order = self._build_short_order(bar, broker, risk)
                            if order:
                                return TradeProposal(order, self._compute_score(-1), "london_sweep")

        if ema_ok_long and smt_ok_long and self.low_swept and not self.low_failed \
                and self.ext_lo_idx is not None:
            if bar_idx - self.ext_lo_idx <= self.max_bars_bos:
                sw = self._last_sw_high_before(self.ext_lo_idx)
                if sw is not None:
                    _, sw_hi = sw
                    if bar.close > sw_hi + self.bos_buf:
                        close_ok = (not self.req_inside) or (bar.close > self.asian_lo)
                        if close_ok:
                            order = self._build_long_order(bar, broker, risk)
                            if order:
                                return TradeProposal(order, self._compute_score(1), "london_sweep")

        return None

    def mark_fired(self):
        """Called by the multi-strategy engine after submitting this proposal."""
        self.trades_today += 1

    # ------------------------------------------------------------------ #
    #  Single-strategy / test interface (backward-compatible)             #
    # ------------------------------------------------------------------ #

    def on_bar(self, bar, local_day, local_min, broker, risk):
        p = self.propose(bar, local_day, local_min, broker, risk)
        if p and broker.submit(p.order):
            self.trades_today += 1
