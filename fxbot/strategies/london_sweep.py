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
"""
from datetime import time

from ..brokers.base import Order


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

        self.day = None
        self._reset_day(None)

    # ------------------------------------------------------------------ #
    #  Day state                                                           #
    # ------------------------------------------------------------------ #

    def _reset_day(self, day):
        self.day      = day
        self.asian_hi = float("-inf")
        self.asian_lo = float("inf")

        # All bars seen today (bar namedtuples from itertuples)
        self._bars = []

        # Confirmed swing points today:  list of (bar_index, price)
        self._sw_lows  = []   # (idx_of_low_bar, low_price)
        self._sw_highs = []   # (idx_of_high_bar, high_price)

        # High-sweep state
        self.high_swept  = False
        self.high_failed = False
        self.ext_hi      = float("-inf")
        self.ext_hi_idx  = None   # bar index (into self._bars) of sweep extreme

        # Low-sweep state
        self.low_swept   = False
        self.low_failed  = False
        self.ext_lo      = float("inf")
        self.ext_lo_idx  = None

        self.trades_today = 0

    # ------------------------------------------------------------------ #
    #  Swing detection (no lookahead)                                     #
    # ------------------------------------------------------------------ #

    def _try_confirm_swing(self, candidate_idx):
        """
        Called when we have just seen bar candidate_idx + swing_k.
        At that point we have exactly swing_k bars on each side of candidate.
        """
        k    = self.swing_k
        bars = self._bars
        # We need bars[candidate_idx - k .. candidate_idx + k] to all exist
        if candidate_idx < k:
            return
        if candidate_idx + k >= len(bars):
            return   # shouldn't happen if called correctly, but guard anyway

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

    # ------------------------------------------------------------------ #
    #  Helpers: "most recent confirmed swing before the extreme bar"      #
    # ------------------------------------------------------------------ #

    def _last_sw_low_before(self, before_bar_idx):
        """Most recent confirmed swing low whose bar index < before_bar_idx."""
        result = None
        for idx, lo in self._sw_lows:
            if idx < before_bar_idx:
                result = (idx, lo)
        return result   # None if no such swing low exists

    def _last_sw_high_before(self, before_bar_idx):
        result = None
        for idx, hi in self._sw_highs:
            if idx < before_bar_idx:
                result = (idx, hi)
        return result

    # ------------------------------------------------------------------ #
    #  Main loop entry point                                              #
    # ------------------------------------------------------------------ #

    def on_bar(self, bar, local_day, local_min, broker, risk):
        if local_day != self.day:
            self._reset_day(local_day)

        # --- append bar and confirm any new swing point ---
        self._bars.append(bar)
        bar_idx = len(self._bars) - 1
        candidate = bar_idx - self.swing_k
        if candidate >= 0:
            self._try_confirm_swing(candidate)

        # --- build Asian range ---
        if self.range_start <= local_min < self.range_end:
            self.asian_hi = max(self.asian_hi, bar.high)
            self.asian_lo = min(self.asian_lo, bar.low)

        # --- session exit (always check even after entry_cutoff) ---
        if broker.position() is not None:
            if local_min >= self.session_exit:
                broker.close_position("session_exit")
            return

        # No valid Asian range yet
        if self.asian_hi == float("-inf"):
            return

        # --- track sweeps during sweep window ---
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

        # --- look for BOS entry ---
        if self.trades_today >= self.max_trades:
            return
        if local_min >= self.entry_cutoff:
            return
        if local_min < self.range_end:
            return

        # Short setup (high was swept)
        if self.high_swept and not self.high_failed and self.ext_hi_idx is not None:
            if bar_idx - self.ext_hi_idx <= self.max_bars_bos:
                sw = self._last_sw_low_before(self.ext_hi_idx)
                if sw is not None:
                    _, sw_lo = sw
                    if bar.close < sw_lo - self.bos_buf:
                        # BOS confirmed — check close-inside-range filter
                        close_ok = (not self.req_inside) or (bar.close < self.asian_hi)
                        if close_ok:
                            self._enter_short(bar, broker, risk)
                            return

        # Long setup (low was swept)
        if self.low_swept and not self.low_failed and self.ext_lo_idx is not None:
            if bar_idx - self.ext_lo_idx <= self.max_bars_bos:
                sw = self._last_sw_high_before(self.ext_lo_idx)
                if sw is not None:
                    _, sw_hi = sw
                    if bar.close > sw_hi + self.bos_buf:
                        close_ok = (not self.req_inside) or (bar.close > self.asian_lo)
                        if close_ok:
                            self._enter_long(bar, broker, risk)
                            return

    # ------------------------------------------------------------------ #
    #  Order construction                                                 #
    # ------------------------------------------------------------------ #

    def _enter_short(self, bar, broker, risk):
        spread_px = bar.spread_pips * self.pip
        entry_est = bar.close                              # sell at bid (next bar)
        stop      = self.ext_hi + self.stop_buf + spread_px
        stop_dist = stop - entry_est
        if stop_dist <= 0 or stop_dist > self.max_stop_px:
            return

        if self.target_mode == "opposite_range":
            target = self.asian_lo
        else:
            target = entry_est - self.rr * stop_dist

        rr_actual = (entry_est - target) / stop_dist if stop_dist > 0 else 0
        if rr_actual < self.min_rr:
            return

        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return
        if broker.submit(Order(-1, units, stop, target, "sweep_short")):
            self.trades_today += 1

    def _enter_long(self, bar, broker, risk):
        spread_px = bar.spread_pips * self.pip
        entry_est = bar.close + spread_px                  # buy at ask (next bar)
        stop      = self.ext_lo - self.stop_buf
        stop_dist = entry_est - stop
        if stop_dist <= 0 or stop_dist > self.max_stop_px:
            return

        if self.target_mode == "opposite_range":
            target = self.asian_hi
        else:
            target = entry_est + self.rr * stop_dist

        rr_actual = (target - entry_est) / stop_dist if stop_dist > 0 else 0
        if rr_actual < self.min_rr:
            return

        equity = broker.equity()
        if not risk.can_trade(equity, bar.Index):
            return
        units = risk.position_size(equity, entry_est, stop, broker.current_spread_pips())
        if units <= 0:
            return
        if broker.submit(Order(1, units, stop, target, "sweep_long")):
            self.trades_today += 1
