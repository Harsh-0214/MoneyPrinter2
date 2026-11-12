"""Published short-term setups from well-known traders (daily signals, intraday entries).

TurtleSoup   - Linda Raschke / Larry Connors, "Street Smarts" (1996), Turtle Soup Plus One:
               a day CLOSES beyond the prior 20-day extreme (that extreme at least
               `min_age` days old); the next day, enter back inside once a bar closes
               back through the old extreme. Stop beyond the new extreme.
EightyTwenty - Raschke/Connors "80-20": a day opens in the top 20% of its range and
               closes in the bottom 20% (or the reverse). Next day, once price has
               traded beyond that day's extreme, enter when a bar closes back inside.
               Stop beyond today's extreme so far.
HolyGrail    - Raschke: daily ADX(14) > `adx_min` (strong trend), a pullback day whose
               low (high) touches the 20-day EMA in an up (down) trend; next day enter
               when a bar closes beyond that pullback day's high (low). Stop at the
               pullback day's other extreme.
IDNR4        - Toby Crabel: yesterday was an inside day AND the narrowest range of the
               last 4 days; today trade the break of its high or low (bar close
               beyond), stop at the other side.

All decide on COMPLETED London days only (no lookahead), enter on a bar CLOSE beyond
the trigger, and share the trade handling: target `target_rr` x risk (None = no
target), stop to breakeven at `trail_to_breakeven_rr`, and an exit either at
`exit_time` the same day (max_hold_days 0) or at the start of the day after
`max_hold_days` days. Optional `trend_sma` filter: longs only above / shorts only
below the N-day average of daily closes.
"""
from typing import Optional

from .daily_patterns import _Daily, _minutes, _order
from .proposal import TradeProposal, manages, move_stop_to_breakeven


class _DailySetup:
    NAME = "?"
    TAG = "?"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.start = _minutes(cfg.get("entry_start", "07:00"))
        self.end = _minutes(cfg.get("entry_end", "16:00"))
        self.exit_min = _minutes(cfg.get("exit_time", "21:00"))
        self.max_hold = int(cfg.get("max_hold_days", 0))       # 0 = out at exit_time the same day
        tr = cfg.get("target_rr", 2.0)
        self.target_rr = float(tr) if tr else None
        self.be = float(cfg.get("trail_to_breakeven_rr", 1.0))
        self.trend_n = cfg.get("trend_sma")
        self.long_only = bool(cfg.get("long_only", False))
        self.score = float(cfg.get("score", 50))
        self._skip = set(int(x) for x in cfg.get("skip_days", []))
        self.cfg = cfg
        self.d = _Daily(keep=300)
        self.setups = []          # today's candidates: (side, trigger, stop, state dict)
        self.traded = False
        self.held_days = 0
        self.today_hi = self.today_lo = None

    # subclasses: return list of (side, trigger, stop) from completed days (self.d.days)
    def _new_setups(self):
        return []

    def _intraday_ready(self, side, trigger, state, bar):
        """Extra intraday condition before a close-beyond-trigger entry (80-20 needs a probe)."""
        return True

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        new_day = self.d.update(bar, local_day)
        pos = broker.position()
        if new_day:
            self.traded = False
            self.today_hi, self.today_lo = bar.high, bar.low
            if pos is not None and manages(pos, self.NAME):
                self.held_days += 1
            dow = self.d.key.weekday()
            self.setups = []
            if dow not in self._skip and len(self.d.days) > 30:
                trend = self.d.sma(int(self.trend_n)) if self.trend_n else None
                last_close = self.d.days[-1][3]
                for side, trig, stop in self._new_setups():
                    if self.long_only and side == -1:
                        continue
                    if trend is not None and ((side == 1 and last_close < trend) or (side == -1 and last_close > trend)):
                        continue
                    self.setups.append((side, trig, stop, {}))
        else:
            self.today_hi, self.today_lo = max(self.today_hi, bar.high), min(self.today_lo, bar.low)

        if pos is not None:
            if manages(pos, self.NAME):
                move_stop_to_breakeven(pos, broker, bar.close, self.be)
                if self.max_hold == 0:
                    if local_min >= self.exit_min:
                        broker.close_position("session_exit")
                elif new_day and self.held_days >= self.max_hold:
                    broker.close_position("time_exit")
            return None
        self.held_days = 0
        if self.traded or not self.setups or not (self.start <= local_min < self.end):
            return None
        for side, trig, stop, state in self.setups:
            if not self._intraday_ready(side, trig, state, bar):
                continue
            if (bar.close - trig) * side > 0:
                stop_px = self._live_stop(side, stop)
                if (bar.close - stop_px) * side <= 0:
                    continue
                target = bar.close + side * self.target_rr * abs(bar.close - stop_px) if self.target_rr else None
                o = _order(side, bar.close, stop_px, target, bar, self.pip, broker, risk,
                           f"{self.TAG}long" if side == 1 else f"{self.TAG}short")
                if o:
                    return TradeProposal(o, self.score, self.NAME)
        return None

    def _live_stop(self, side, stop):
        return stop

    def mark_fired(self):
        self.traded = True
        self.held_days = 0

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()

    def describe(self, local_min=None):
        if not self.setups:
            return {"lines": [], "boxes": [], "status": f"{self.NAME}: no setup today"}
        parts = [f"{'BUY' if s == 1 else 'SELL'} on a close {'above' if s == 1 else 'below'} {t:.5g} (stop {st:.5g})"
                 for s, t, st, _ in self.setups]
        return {"lines": [], "boxes": [], "status": f"{self.NAME}: " + "; ".join(parts)}


class TurtleSoup(_DailySetup):
    NAME, TAG = "turtle_soup", "ts_"

    def _new_setups(self):
        n = int(self.cfg.get("lookback", 20)); age = int(self.cfg.get("min_age", 4))
        d = self.d.days
        if len(d) < n + 2:
            return []
        y = d[-1]
        window = d[-n - 1:-1]                        # the n days before yesterday
        lows = [x[2] for x in window]; highs = [x[1] for x in window]
        out = []
        lo = min(lows); lo_age = len(window) - 1 - lows.index(lo) + 1     # days before yesterday
        if y[3] < lo and lo_age >= age:
            out.append((1, lo, y[2]))                # back above the old low; stop under the new low
        hi = max(highs); hi_age = len(window) - 1 - highs.index(hi) + 1
        if y[3] > hi and hi_age >= age:
            out.append((-1, hi, y[1]))
        return out


class EightyTwenty(_DailySetup):
    NAME, TAG = "eighty_twenty", "e20_"

    def _new_setups(self):
        d = self.d.days
        if len(d) < 2:
            return []
        o, h, l, c = d[-1]
        rng = h - l
        if rng <= 0:
            return []
        out = []
        if (o - l) / rng >= 0.8 and (c - l) / rng <= 0.2:   # opened near the high, closed near the low
            out.append((1, l, None))
        if (o - l) / rng <= 0.2 and (c - l) / rng >= 0.8:   # opened near the low, closed near the high
            out.append((-1, h, None))
        return out

    def _intraday_ready(self, side, trigger, state, bar):
        if (side == 1 and self.today_lo < trigger) or (side == -1 and self.today_hi > trigger):
            state["probed"] = True                   # traded through yesterday's extreme
        return state.get("probed", False)

    def _live_stop(self, side, stop):
        return self.today_lo if side == 1 else self.today_hi


class HolyGrail(_DailySetup):
    NAME, TAG = "holy_grail", "hg_"

    def _adx(self, n=14):
        d = self.d.days
        if len(d) < 3 * n:
            return None, None, None
        trs, pdm, mdm = [], [], []
        for i in range(1, len(d)):
            h, l, pc = d[i][1], d[i][2], d[i - 1][3]
            up, dn = h - d[i - 1][1], d[i - 1][2] - l
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            pdm.append(up if up > dn and up > 0 else 0.0)
            mdm.append(dn if dn > up and dn > 0 else 0.0)
        atr = sum(trs[:n]); p = sum(pdm[:n]); m = sum(mdm[:n]); dxs = []
        for i in range(n, len(trs)):
            atr += trs[i] - atr / n; p += pdm[i] - p / n; m += mdm[i] - m / n
            pdi, mdi = 100 * p / atr if atr else 0, 100 * m / atr if atr else 0
            dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0)
        if len(dxs) < n:
            return None, None, None
        adx = sum(dxs[:n]) / n
        for x in dxs[n:]:
            adx += (x - adx) / n
        return adx, pdi, mdi

    def _ema(self, n=20):
        d = self.d.days
        if len(d) < n + 1:
            return None
        a = 2 / (n + 1); e = d[0][3]
        for x in d[1:]:
            e += a * (x[3] - e)
        return e

    def _new_setups(self):
        adx, pdi, mdi = self._adx(int(self.cfg.get("adx_period", 14)))
        ema = self._ema(int(self.cfg.get("ema_period", 20)))
        if adx is None or ema is None or adx < float(self.cfg.get("adx_min", 30)):
            return []
        o, h, l, c = self.d.days[-1]
        out = []
        if pdi > mdi and l <= ema <= h:
            out.append((1, h, l))
        if mdi > pdi and l <= ema <= h:
            out.append((-1, l, h))
        return out


class IDNR4(_DailySetup):
    NAME, TAG = "id_nr4", "idnr_"

    def _new_setups(self):
        d = self.d.days
        if len(d) < 5:
            return []
        y, p = d[-1], d[-2]
        inside = y[1] < p[1] and y[2] > p[2]
        nr4 = (y[1] - y[2]) < min(x[1] - x[2] for x in d[-4:-1])
        if not (inside and nr4):
            return []
        return [(1, y[1], y[2]), (-1, y[2], y[1])]
