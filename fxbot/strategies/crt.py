"""CRT, Candle Range Theory (higher-timeframe sweep and close back inside). Research only.

Rules as coded:
  * Range: candle 1 (C1) = the previous completed higher-timeframe candle ("D" = London day,
    "4H" = UTC 4-hour block). Its high / low are the range.
  * Manipulation, two readings of the rule:
      mode "close":    C2 (the next candle) trades beyond one side of C1 and CLOSES back inside C1.
                       The setup is traded during C3 only.
      mode "intrabar": during C2, price trades beyond one side of C1 and a lower-timeframe bar closes
                       back inside C1. The setup can be traded for the rest of C2 and during C3.
  * Entry trigger on the lower timeframe (the bars the strategy runs on), after the sweep extreme:
      "mss": a close through the most recent swing point (k-bar fractal) formed after the extreme
             (market structure shift);
      "fvg": a fair value gap in the trade's direction forms after the extreme (enter at its close).
  * Stop: beyond the sweep extreme (+ stop_buffer_atr x daily ATR). If price trades through it
    before entry, the setup is cancelled.
  * Target: the opposite end of C1. Skipped if reward/risk < min_rr.
  * Exit: stop, target, or at the end of the higher-timeframe candle after the entry candle.
"""
from typing import Optional

import pandas as pd

from .daily_patterns import _Daily, _order
from .proposal import TradeProposal, manages


class CRT:
    NAME = "crt"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.htf = cfg.get("htf", "D")
        self.mode = cfg.get("mode", "close")
        self.trigger = cfg.get("trigger", "mss")
        self.k = int(cfg.get("swing_k", 2))
        self.min_rr = float(cfg.get("min_rr", 0.0))
        self.buffer_atr = float(cfg.get("stop_buffer_atr", 0.05))
        self.score = float(cfg.get("score", 50))
        self.d = _Daily(keep=40)              # daily ATR for the stop buffer
        self.hkey = None
        self.c1 = None                        # previous HTF candle [o, h, l, c]
        self.cur = None                       # forming HTF candle
        self.n_htf = 0                        # HTF candles seen (for expiry / time exit)
        self.setups = []                      # dicts: side, ext, ext_t, target, expires, done
        self.bars = []                        # recent LTF bars (t, h, l, c)
        self.swings = []                      # (t, kind 'H'/'L', price)
        self.entry_htf = None
        self.pending = None

    # ---------------------------------------------------------------- candles
    def _key(self, bar, local_day):
        if self.htf == "D":
            return _Daily.day_key(local_day)
        return int(bar.Index.value // (4 * 3600 * 10**9))

    def _on_htf_close(self, c2):
        """c2 just closed; self.c1 is the candle before it."""
        c1 = self.c1
        if c1 is not None and self.mode == "close":
            _, h1, l1, _ = c1
            _, h2, l2, cl2 = c2
            if h2 > h1 and l1 < cl2 < h1:
                self.setups.append(dict(side=-1, ext=h2, ext_t=self._c2_ext_t["H"], target=l1,
                                        expires=self.n_htf + 1, done=False))
            if l2 < l1 and l1 < cl2 < h1:
                self.setups.append(dict(side=1, ext=l2, ext_t=self._c2_ext_t["L"], target=h1,
                                        expires=self.n_htf + 1, done=False))

    def _update_htf(self, bar, local_day):
        k = self._key(bar, local_day)
        if k != self.hkey:
            if self.cur is not None:
                self._on_htf_close(self.cur)
                self.c1 = self.cur
            self.hkey = k
            self.n_htf += 1
            self.cur = [bar.open, bar.high, bar.low, bar.close]
            self._c2_ext_t = {"H": bar.Index, "L": bar.Index}
            self._intrabar_armed = {1: False, -1: False}
            self.setups = [s for s in self.setups if not s["done"] and s["expires"] >= self.n_htf]
        else:
            c = self.cur
            if bar.high > c[1]:
                c[1] = bar.high
                self._c2_ext_t["H"] = bar.Index
            if bar.low < c[2]:
                c[2] = bar.low
                self._c2_ext_t["L"] = bar.Index
            c[3] = bar.close

    def _intrabar(self, bar):
        """mode intrabar: C2 swept C1 and this LTF bar closed back inside."""
        if self.c1 is None:
            return
        _, h1, l1, _ = self.c1
        _, h2, l2, _ = self.cur
        if h2 > h1 and l1 < bar.close < h1 and not self._intrabar_armed[-1]:
            self._intrabar_armed[-1] = True
            self.setups.append(dict(side=-1, ext=h2, ext_t=self._c2_ext_t["H"], target=l1,
                                    expires=self.n_htf + 1, done=False))
        if l2 < l1 and l1 < bar.close < h1 and not self._intrabar_armed[1]:
            self._intrabar_armed[1] = True
            self.setups.append(dict(side=1, ext=l2, ext_t=self._c2_ext_t["L"], target=h1,
                                    expires=self.n_htf + 1, done=False))

    def _update_swings(self, bar):
        self.bars.append((bar.Index, bar.high, bar.low, bar.close))
        if len(self.bars) > 400:
            self.bars.pop(0)
        k = self.k
        if len(self.bars) >= 2 * k + 1:
            t, h, l, _ = self.bars[-k - 1]
            win = self.bars[-2 * k - 1:]
            if all(h > x[1] for x in win if x[0] != t):
                self.swings.append((t, "H", h))
            if all(l < x[2] for x in win if x[0] != t):
                self.swings.append((t, "L", l))
            if len(self.swings) > 200:
                self.swings.pop(0)

    def _fvg_after(self, side, t0):
        if len(self.bars) < 3:
            return False
        b1, _, b3 = self.bars[-3:]
        if b1[0] <= t0:
            return False
        return (b3[1] < b1[2]) if side == -1 else (b3[2] > b1[1])

    # ---------------------------------------------------------------- main
    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        self.d.update(bar, local_day)
        self._update_htf(bar, local_day)
        self._update_swings(bar)
        if self.mode == "intrabar":
            self._intrabar(bar)
        pos = broker.position()
        if pos is not None:
            if manages(pos, self.NAME) and self.entry_htf is not None and self.n_htf >= self.entry_htf + 2:
                broker.close_position("time_exit")         # end of the HTF candle after the entry candle
            return None
        atr = self.d.atr(14)
        if atr is None:
            return None
        for s in self.setups:
            if s["done"]:
                continue
            side = s["side"]
            if (side == -1 and bar.high > s["ext"]) or (side == 1 and bar.low < s["ext"]):
                if self.mode == "intrabar" and s["expires"] == self.n_htf + 1:
                    s["ext"] = bar.high if side == -1 else bar.low      # still inside C2: sweep extends
                    s["ext_t"] = bar.Index
                    continue
                s["done"] = True                                       # stop level traded through
                continue
            if self.trigger == "mss":
                kind = "L" if side == -1 else "H"
                pts = [p for (t, kk, p) in self.swings if kk == kind and t > s["ext_t"]]
                fire = bool(pts) and ((bar.close < pts[-1]) if side == -1 else (bar.close > pts[-1]))
            else:
                fire = self._fvg_after(side, s["ext_t"])
            if not fire:
                continue
            stop = s["ext"] + (self.buffer_atr * atr if side == -1 else -self.buffer_atr * atr)
            risk_d = (stop - bar.close) * (-side)
            reward = (bar.close - s["target"]) * (-side)
            if risk_d <= 0 or reward <= 0 or reward / risk_d < self.min_rr:
                s["done"] = True
                continue
            o = _order(side, bar.close, stop, s["target"], bar, self.pip, broker, risk,
                       "crt_long" if side == 1 else "crt_short")
            if o:
                self.pending = s
                return TradeProposal(o, self.score, self.NAME)
        return None

    def mark_fired(self):
        if self.pending is not None:
            self.pending["done"] = True
            self.pending = None
        self.entry_htf = self.n_htf

    def describe(self, local_min=None):
        return {"lines": [], "boxes": [], "status": f"CRT: {sum(not s['done'] for s in self.setups)} setups armed"}

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()
