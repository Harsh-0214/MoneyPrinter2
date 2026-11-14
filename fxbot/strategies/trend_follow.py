"""Daily trend following (multi-day holds).

Runs on intraday bars (1h recommended) but decides once per day, on the first
bar of each new London day, using only COMPLETED daily bars (no lookahead).
Sunday's short session is merged into Monday.

Entry (signal):
  donchian : yesterday's close > highest high of the `entry_days` days before
             it -> long; < lowest low -> short.
  ema      : fast EMA of daily closes crosses above / below slow EMA.
Stop:
  initial  : stop_atr x ATR(atr_days) from entry.
  trailing : each day the stop ratchets to (highest high since entry -
             stop_atr x ATR) for longs (mirror for shorts). Never loosens.
Exit:
  stop hit (intraday), or optional exit channel: close below the lowest low
  of `exit_days` days (long) / above highest high (short), or an opposite
  entry signal.
No profit target; no time exit. Swap is charged by the broker.

Add-on mode (add_on_r > 0, "adding to a winner"): runs as its own unit next to
the main trend bot. On the same entry signal it does NOT buy; it arms. Once
price has moved add_on_r x the main trade's initial risk in the trend's
direction, it buys a second position whose stop is the MAIN trade's entry
price (so if the trend fails there, it closes near breakeven). After that it
trails and exits exactly like the main trade. It disarms if the trend exits
(exit channel / opposite signal) or the main trade's initial stop would have
been hit before the add-on triggered.
"""
from collections import deque
from datetime import timedelta
from typing import Optional

import numpy as np

from ..brokers.base import Order
from .proposal import TradeProposal, manages

NAME = "trend_follow"


class TrendFollow:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.signal     = cfg.get("signal", "donchian")
        self.entry_days = int(cfg.get("entry_days", 55))
        self.exit_days  = cfg.get("exit_days", 20)            # None = trailing stop only
        self.fast       = int(cfg.get("ema_fast", 50))
        self.slow       = int(cfg.get("ema_slow", 200))
        self.atr_days   = int(cfg.get("atr_days", 20))
        self.stop_atr   = float(cfg.get("stop_atr", 3.0))
        self.trail      = cfg.get("trail", True)   # False = fixed initial stop (turtle style)
        self.long_only  = cfg.get("long_only", False)
        self.short_only = cfg.get("short_only", False)
        self.score      = float(cfg.get("score", 100))
        self.add_on_r   = float(cfg.get("add_on_r", 0.0))     # 0 = normal entries
        # intraday_entry: enter on the first BAR close beyond the channel instead of waiting
        # for the daily close (Turtle-style). Exits / trailing stay daily. One entry per day.
        self.intraday   = bool(cfg.get("intraday_entry", False))
        self.day_traded = False
        self.armed      = None   # add-on: (side, trigger price, stop price, main initial stop)
        keep = max(self.entry_days, self.exit_days or 0, self.atr_days, 2) + 5
        self.days = deque(maxlen=keep)      # completed (high, low, close)
        self.ema_f = self.ema_s = None
        self.prev_diff = None
        self.n_closes = 0
        self.cur_key = None
        self.cur = None                     # [high, low, close] of the forming day
        self.trail_ext = None               # best price since entry (for trailing)
        self.pending, self.pending_atr = 0, None   # today's entry signal (valid all day)
        self.last_sig, self.last_atr = 0, None

    # ---------------- daily bar building ----------------
    @staticmethod
    def _day_key(local_day):
        d = local_day.astype("datetime64[D]").astype(object)
        return d + timedelta(days=1) if d.weekday() == 6 else d     # Sunday -> Monday

    def _close_day(self):
        h, l, c = self.cur
        self.days.append((h, l, c))
        self.n_closes += 1
        a_f, a_s = 2 / (self.fast + 1), 2 / (self.slow + 1)
        self.ema_f = c if self.ema_f is None else self.ema_f + a_f * (c - self.ema_f)
        self.ema_s = c if self.ema_s is None else self.ema_s + a_s * (c - self.ema_s)

    def _atr(self):
        d = list(self.days)
        if len(d) < self.atr_days + 1:
            return None
        trs = [max(h - l, abs(h - d[i - 1][2]), abs(l - d[i - 1][2]))
               for i, (h, l, c) in enumerate(d) if i > 0]
        return float(np.mean(trs[-self.atr_days:]))

    def _signal(self):
        """+1 / -1 / 0 from completed days only."""
        d = list(self.days)
        if self.signal == "ema":
            if self.n_closes < self.slow:
                return 0
            diff = self.ema_f - self.ema_s
            prev, self.prev_diff = self.prev_diff, diff
            if prev is None:
                return 0
            if prev <= 0 < diff:
                return 1
            if prev >= 0 > diff:
                return -1
            return 0
        if len(d) < self.entry_days + 1:
            return 0
        window, last = d[-self.entry_days - 1:-1], d[-1]
        if last[2] > max(h for h, _, _ in window):
            return 1
        if last[2] < min(l for _, l, _ in window):
            return -1
        return 0

    def _intraday_signal(self, price):
        """+1 / -1 / 0: the current price versus the channel of COMPLETED days."""
        d = list(self.days)
        if self.signal != "donchian" or len(d) < self.entry_days:
            return 0
        window = d[-self.entry_days:]
        if price > max(h for h, _, _ in window):
            return 1
        if price < min(l for _, l, _ in window):
            return -1
        return 0

    def _exit_channel_hit(self, side):
        if not self.exit_days:
            return False
        d = list(self.days)
        if len(d) < self.exit_days + 1:
            return False
        window, last = d[-self.exit_days - 1:-1], d[-1]
        if side == 1:
            return last[2] < min(l for _, l, _ in window)
        return last[2] > max(h for h, _, _ in window)

    # ---------------- main ----------------
    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        key = self._day_key(local_day)
        new_day = key != self.cur_key
        if new_day:
            if self.cur is not None:
                self._close_day()
            self.cur_key = key
            self.cur = [bar.high, bar.low, bar.close]
        else:
            self.cur[0] = max(self.cur[0], bar.high)
            self.cur[1] = min(self.cur[1], bar.low)
            self.cur[2] = bar.close

        pos = broker.position()
        if pos is None:
            self.trail_ext = None
        if pos is not None and manages(pos, NAME) and bar.Index >= pos.entry_time:
            # only bars AFTER entry count (a startup replay also feeds older bars)
            if pos.side == 1:
                self.trail_ext = max(self.trail_ext or pos.entry_price, bar.high)
            else:
                self.trail_ext = min(self.trail_ext or pos.entry_price, bar.low)
        if not new_day:
            if pos is None and self.armed:
                return self._add_on_check(bar, broker, risk)
            # Entry signal stays valid for the whole day, so a bot (re)started
            # after the day's first bar still takes it. Backtests: unchanged,
            # the first bar of the day already fires.
            if pos is None and self.pending:
                return self._entry(self.pending, self.pending_atr, bar, broker, risk)
            if pos is None and self.intraday and not self.day_traded and self.last_atr:
                sig = self._intraday_signal(bar.close)
                if sig and not ((sig == 1 and self.short_only) or (sig == -1 and self.long_only)):
                    return self._entry(sig, self.last_atr, bar, broker, risk)
            return None

        sig = self._signal()          # always evaluated so EMA state stays current
        atr = self._atr()
        self.day_traded = False
        self.pending, self.pending_atr = 0, None
        self.last_sig, self.last_atr = sig, atr
        if pos is not None:
            if not manages(pos, NAME):
                return None
            # daily: ratchet trailing stop, check exit channel / reversal
            if atr and self.trail:
                if pos.side == 1:
                    ns = self.trail_ext - self.stop_atr * atr
                    if ns > pos.stop_loss:
                        broker.update_stop(ns)
                else:
                    ns = self.trail_ext + self.stop_atr * atr
                    if ns < pos.stop_loss:
                        broker.update_stop(ns)
            if self._exit_channel_hit(pos.side) or sig == -pos.side:
                broker.close_position("trend_exit")
            return None

        if self.add_on_r > 0 and self.armed:
            side, trig, stop0, init_stop = self.armed
            last_close = self.days[-1][2]
            if self._exit_channel_hit(side) or sig == -side or (last_close - init_stop) * side <= 0:
                self.armed = None                       # the trend ended before the add-on fired
        if sig == 0 or atr is None:
            return self._add_on_check(bar, broker, risk) if self.armed else None
        if (sig == 1 and self.short_only) or (sig == -1 and self.long_only):
            from .proposal import px
            d = list(self.days)
            win = d[-self.entry_days - 1:-1]
            lvl = min(l for _, l, _ in win) if sig == -1 else max(h for h, _, _ in win)
            self.skip_note = ("side", f"the daily close {px(d[-1][2], self.pip)} broke the {self.entry_days}-day "
                                      f"{'low' if sig == -1 else 'high'} {px(lvl, self.pip)}, but this strategy only "
                                      f"{'buys' if self.long_only else 'sells'}")
            return None
        if self.add_on_r > 0:
            if self.armed and self.armed[0] == sig:      # same trend: keep the original trigger
                return self._add_on_check(bar, broker, risk)
            base = bar.close
            r = self.stop_atr * atr
            self.armed = (sig, base + sig * self.add_on_r * r, base, base - sig * r)
            return self._add_on_check(bar, broker, risk)
        self.pending, self.pending_atr = sig, atr
        return self._entry(sig, atr, bar, broker, risk)

    def _add_on_check(self, bar, broker, risk) -> Optional[TradeProposal]:
        side, trig, stop0, _ = self.armed
        if (bar.close - trig) * side < 0:
            return None
        return self._entry(side, self.last_atr, bar, broker, risk, stop=stop0, tag="trend_add")

    def _entry(self, sig, atr, bar, broker, risk, stop=None, tag=None) -> Optional[TradeProposal]:
        spread = bar.spread_pips * self.pip
        entry = bar.close + (spread if sig == 1 else 0.0)
        if stop is None:
            stop = entry - sig * self.stop_atr * atr
        if (entry - stop) * sig <= 0:
            return None
        eq = broker.equity()
        if not risk.can_trade(eq, bar.Index):
            return None
        units = risk.position_size(eq, entry, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        self.trail_ext = None
        return TradeProposal(Order(sig, units, stop, None,
                                   tag or ("trend_long" if sig == 1 else "trend_short")),
                             self.score, NAME)

    def mark_fired(self):
        self.pending = 0
        self.armed = None
        self.day_traded = True

    def describe(self, local_min=None):
        """Chart overlay: entry channel, exit channel, trailing stop, status."""
        out = {"lines": [], "boxes": [], "status": ""}
        d = list(self.days)
        if len(d) < self.entry_days + 1:
            out["status"] = f"Trend: warming up ({len(d)}/{self.entry_days + 1} days of history)"
            return out
        win = d[-self.entry_days:]
        hi, lo = max(h for h, _, _ in win), min(l for _, l, _ in win)
        out["lines"] += [
            {"price": hi, "label": f"{self.entry_days}-day high: close above -> BUY", "color": "seagreen", "style": "dash"},
            {"price": lo, "label": f"{self.entry_days}-day low: close below -> SELL", "color": "orangered", "style": "dash"},
        ]
        if self.long_only:
            out["lines"].pop()
        if self.exit_days and len(d) >= self.exit_days:
            xw = d[-self.exit_days:]
            out["lines"].append({"price": min(l for _, l, _ in xw), "color": "dimgray", "style": "dot",
                                 "label": f"{self.exit_days}-day low (long exit)"})
        if self.trail_ext is not None and self.last_atr:
            out["status"] = (f"Trend: IN TRADE - best price {self.trail_ext:.2f}, stop trails "
                             f"{self.stop_atr:g}x daily range ({self.stop_atr * self.last_atr:.2f}) behind it")
        elif self.pending:
            out["status"] = f"Trend: {'BUY' if self.pending == 1 else 'SELL'} signal today - entering"
        else:
            last = d[-1][2]
            out["status"] = (f"Trend: waiting - last daily close {last:.2f}; buy above {hi:.2f}"
                             + ("" if self.long_only else f", sell below {lo:.2f}"))
        return out

    def on_bar(self, bar, local_day, local_min, broker, risk):
        p = self.propose(bar, local_day, local_min, broker, risk)
        if p:
            broker.submit(p.order)
