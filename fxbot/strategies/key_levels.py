"""Key levels: trade support/resistance lines the way a chart trader draws them.

Lines are rebuilt at the start of every London day from COMPLETED history only:
  pd     : previous day high / low (London day)
  pw     : previous week high / low
  swing  : clusters of 1-hour swing highs/lows from the last `lookback_days`
           that were touched at least `min_touches` times (within cluster_pips)

Signals during the entry window (each level trades at most once per day):
  bounce : price comes from one side, pierces the line by <= max_pierce_pips
           and the 5-min bar CLOSES back on the original side
           -> long at support / short at resistance
  break  : bar closes through the line by >= break_buffer_pips
           -> trade the breakout
Stop:   beyond the bar extreme (bounce) or back across the line (break)
        + stop_buffer_pips, clamped to [min_stop_pips, max_stop_pips]
Target: target_rr x risk, or "next" = the next line in the trade direction
        (skipped if that gives < min_rr).
Exit:   session_exit if still open.
"""
from collections import deque
from datetime import time, timedelta
from typing import List, Optional, Tuple

from ..brokers.base import Order
from .proposal import TradeProposal, manages, move_stop_to_breakeven

NAME = "key_levels"


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class KeyLevels:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.mode          = cfg.get("mode", "bounce")
        kinds              = cfg.get("levels", ["pd", "pw", "swing"])
        self.kinds         = set(kinds if isinstance(kinds, (list, tuple, set)) else str(kinds).split("+"))
        self.lookback_days = int(cfg.get("lookback_days", 10))
        self.swing_k       = int(cfg.get("swing_k", 3))
        self.cluster       = cfg.get("cluster_pips", 5.0) * pip
        self.min_touches   = int(cfg.get("min_touches", 2))
        self.entry_start   = _minutes(cfg.get("entry_start", "08:00"))
        self.entry_end     = _minutes(cfg.get("entry_end", "15:00"))
        self.session_exit  = _minutes(cfg.get("session_exit", "16:00"))
        self.max_pierce    = cfg.get("max_pierce_pips", 8.0) * pip
        self.confirm_buf   = cfg.get("confirm_pips", 0.5) * pip
        self.break_buf     = cfg.get("break_buffer_pips", 3.0) * pip
        self.stop_buf      = cfg.get("stop_buffer_pips", 2.0) * pip
        self.min_stop      = cfg.get("min_stop_pips", 8.0) * pip
        self.max_stop      = cfg.get("max_stop_pips", 30.0) * pip
        self.target        = cfg.get("target", "rr")
        self.target_rr     = float(cfg.get("target_rr", 2.0))
        self.min_rr        = float(cfg.get("min_rr", 1.5))
        self.trail_be_rr   = float(cfg.get("trail_to_breakeven_rr", 0.0))
        self.max_trades    = int(cfg.get("max_trades_per_day", 1))
        self.score         = float(cfg.get("score", 80))
        self._skip_days    = set(int(d) for d in cfg.get("skip_days", []))

        self.hours = deque(maxlen=self.lookback_days * 24 + 10)   # completed 1h bars
        self._hour = None            # [key, o, h, l, c] forming
        self.day_key = None
        self.day_hl = None           # [h, l] forming London day
        self.prev_day = None         # (h, l)
        self.week_key = None
        self.week_hl = None
        self.prev_week = None
        self.levels: List[Tuple[float, str, int]] = []   # (price, kind, touches)
        self.used = set()
        self.trades_today = 0
        self.prev_close = None
        self.status = "starting"
        self.last_signal = None

    # ---------------- history ----------------
    def _roll_hour(self, bar):
        key = bar.Index.floor("1h")
        if self._hour is None or self._hour[0] != key:
            if self._hour is not None:
                self.hours.append(tuple(self._hour[1:]))
            self._hour = [key, bar.open, bar.high, bar.low, bar.close]
        else:
            h = self._hour
            h[2] = max(h[2], bar.high)
            h[3] = min(h[3], bar.low)
            h[4] = bar.close

    def _swing_levels(self):
        hs = list(self.hours)
        k = self.swing_k
        pts = []
        for i in range(k, len(hs) - k):
            hi, lo = hs[i][1], hs[i][2]
            if all(hs[j][1] < hi for j in range(i - k, i + k + 1) if j != i):
                pts.append(hi)
            if all(hs[j][2] > lo for j in range(i - k, i + k + 1) if j != i):
                pts.append(lo)
        pts.sort()
        out, grp = [], []
        for p in pts:
            if grp and p - grp[0] > self.cluster:
                out.append(grp)
                grp = []
            grp.append(p)
        if grp:
            out.append(grp)
        return [(sum(g) / len(g), "swing", len(g)) for g in out if len(g) >= self.min_touches]

    @staticmethod
    def _eff_day(local_day):
        d = local_day.astype("datetime64[D]").astype(object)
        return d + timedelta(days=1) if d.weekday() == 6 else d   # Sunday -> Monday

    def _new_day(self, d):
        if self.day_hl is not None:
            self.prev_day = tuple(self.day_hl)
        wk = (d - timedelta(days=d.weekday()))
        if self.week_key is not None and wk != self.week_key and self.week_hl is not None:
            self.prev_week = tuple(self.week_hl)
            self.week_hl = None
        self.week_key = wk
        self.day_key = d
        self.day_hl = None
        self.used = set()
        self.trades_today = 0
        if d.weekday() in self._skip_days:
            self.trades_today = self.max_trades
        lv = []
        if "pd" in self.kinds and self.prev_day:
            lv += [(self.prev_day[0], "PDH", 1), (self.prev_day[1], "PDL", 1)]
        if "pw" in self.kinds and self.prev_week:
            lv += [(self.prev_week[0], "PWH", 1), (self.prev_week[1], "PWL", 1)]
        if "swing" in self.kinds:
            lv += self._swing_levels()
        self.levels = sorted(lv)

    # ---------------- orders ----------------
    def _next_level(self, side, entry):
        if side == 1:
            above = [p for p, _, _ in self.levels if p > entry + self.min_stop]
            return min(above) if above else None
        below = [p for p, _, _ in self.levels if p < entry - self.min_stop]
        return max(below) if below else None

    def _order(self, side, raw_stop, bar, broker, risk, tag) -> Optional[Order]:
        spread = bar.spread_pips * self.pip
        if side == 1:
            entry = bar.close + spread
            stop = min(raw_stop - self.stop_buf, entry - self.min_stop)
            dist = entry - stop
        else:
            entry = bar.close
            stop = max(raw_stop + self.stop_buf + spread, entry + self.min_stop)
            dist = stop - entry
        if dist <= 0 or dist > self.max_stop:
            return None
        if self.target == "next":
            nl = self._next_level(side, entry)
            if nl is None or abs(nl - entry) / dist < self.min_rr:
                return None
            target = nl - side * spread * 0.5
        else:
            target = entry + side * self.target_rr * dist
        eq = broker.equity()
        if not risk.can_trade(eq, bar.Index):
            return None
        units = risk.position_size(eq, entry, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        return Order(side, units, stop, target, tag)

    # ---------------- main ----------------
    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        d = self._eff_day(local_day)
        if d != self.day_key:
            self._new_day(d)
        self._roll_hour(bar)
        self.day_hl = [bar.high, bar.low] if self.day_hl is None else \
            [max(self.day_hl[0], bar.high), min(self.day_hl[1], bar.low)]
        self.week_hl = [bar.high, bar.low] if self.week_hl is None else \
            [max(self.week_hl[0], bar.high), min(self.week_hl[1], bar.low)]
        prev_close, self.prev_close = self.prev_close, bar.close

        pos = broker.position()
        if pos is not None:
            if manages(pos, NAME):
                move_stop_to_breakeven(pos, broker, bar.close, self.trail_be_rr)
                if local_min >= self.session_exit:
                    broker.close_position("session_exit")
                self.status = f"in trade ({pos.tag})"
            return None
        if self.trades_today >= self.max_trades:
            self.status = "done for today"
            return None
        if not (self.entry_start <= local_min < self.entry_end):
            self.status = "outside entry window"
            return None
        if prev_close is None or not self.levels:
            self.status = "no levels yet"
            return None
        self.status = f"watching {len(self.levels)} levels"

        best = None
        for price, kind, touches in self.levels:
            if price in self.used:
                continue
            if self.mode == "bounce":
                if prev_close > price and bar.low <= price and price - bar.low <= self.max_pierce \
                        and bar.close > price + self.confirm_buf:
                    cand = (1, bar.low, price, kind)
                elif prev_close < price and bar.high >= price and bar.high - price <= self.max_pierce \
                        and bar.close < price - self.confirm_buf:
                    cand = (-1, bar.high, price, kind)
                else:
                    continue
            else:   # break
                if prev_close <= price and bar.close > price + self.break_buf:
                    cand = (1, price, price, kind)
                elif prev_close >= price and bar.close < price - self.break_buf:
                    cand = (-1, price, price, kind)
                else:
                    continue
            if best is None or abs(price - bar.close) < abs(best[2] - bar.close):
                best = cand
        if best is None:
            return None
        side, raw_stop, price, kind = best
        self.used.add(price)
        tag = ("kl_long" if side == 1 else "kl_short")
        o = self._order(side, raw_stop, bar, broker, risk, tag)
        if o is None:
            return None
        self.last_signal = (bar.Index, side, price, kind)
        return TradeProposal(o, self.score, NAME)

    def mark_fired(self):
        self.trades_today += 1

    def on_bar(self, bar, local_day, local_min, broker, risk):
        p = self.propose(bar, local_day, local_min, broker, risk)
        if p and broker.submit(p.order):
            self.mark_fired()

    # ---------------- chart overlay ----------------
    def describe(self):
        out = {"lines": [], "status": f"KeyLevels: {self.status}"}
        for price, kind, touches in self.levels:
            label = kind if kind != "swing" else f"S/R x{touches}"
            out["lines"].append({"price": price, "label": label,
                                 "color": "gold" if kind == "swing" else "silver",
                                 "used": price in self.used})
        return out
