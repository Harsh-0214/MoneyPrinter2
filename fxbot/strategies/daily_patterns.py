"""Daily-chart strategies that run on intraday bars (decide from COMPLETED days only).

All three share a London-day daily-bar builder (Sunday's short session is merged
into Monday) and use ATR / range multiples, so the same settings work on FX and gold.

DailyPullback   - swing "buy the dip in an uptrend" (RSI-2 on DAILY closes), hold days
VolBreakout     - Larry Williams style: today's open +/- k x yesterday's range, exit evening
NarrowRangeBreak- after an NR7 or inside day, trade the break of yesterday's high/low
"""
from datetime import time, timedelta
from typing import Optional

from ..brokers.base import Order
from .proposal import TradeProposal, manages, move_stop_to_breakeven


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class _Daily:
    """Incremental London-day OHLC history."""

    def __init__(self, keep=260):
        self.days = []            # completed (open, high, low, close)
        self.keep = keep
        self.key = None
        self.cur = None

    @staticmethod
    def day_key(local_day):
        d = local_day.astype("datetime64[D]").astype(object)
        return d + timedelta(days=1) if d.weekday() == 6 else d

    def update(self, bar, local_day):
        """Returns True on the first bar of a new day."""
        k = self.day_key(local_day)
        if k != self.key:
            if self.cur is not None:
                self.days.append(tuple(self.cur))
                if len(self.days) > self.keep:
                    self.days.pop(0)
            self.key = k
            self.cur = [bar.open, bar.high, bar.low, bar.close]
            return True
        c = self.cur
        c[1] = max(c[1], bar.high)
        c[2] = min(c[2], bar.low)
        c[3] = bar.close
        return False

    def atr(self, n):
        d = self.days
        if len(d) < n + 1:
            return None
        trs = [max(d[i][1] - d[i][2], abs(d[i][1] - d[i - 1][3]), abs(d[i][2] - d[i - 1][3]))
               for i in range(len(d) - n, len(d))]
        return sum(trs) / n

    def sma(self, n):
        if len(self.days) < n:
            return None
        return sum(x[3] for x in self.days[-n:]) / n

    def rsi(self, n):
        """Wilder RSI of daily closes over the whole stored history."""
        closes = [x[3] for x in self.days]
        if len(closes) < n + 2:
            return None
        ag = al = None
        for a, b in zip(closes[:-1], closes[1:]):
            ch = b - a
            g, l = max(ch, 0.0), max(-ch, 0.0)
            if ag is None:
                ag, al = g, l
            else:
                ag += (g - ag) / n
                al += (l - al) / n
        return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _order(side, entry_px, stop, target, bar, pip, broker, risk, tag):
    spread = bar.spread_pips * pip
    entry = entry_px + (spread if side == 1 else 0.0)
    if side == -1:
        stop = stop + spread
    if (entry - stop) * side <= 0:
        return None
    eq = broker.equity()
    if not risk.can_trade(eq, bar.Index):
        return None
    units = risk.position_size(eq, entry, stop, broker.current_spread_pips())
    if units <= 0:
        return None
    return Order(side, units, stop, target, tag)


class DailyPullback:
    NAME = "daily_pullback"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.trend_n = int(cfg.get("trend_sma", 100))
        self.rsi_n = int(cfg.get("rsi_period", 2))
        self.lo, self.hi = float(cfg.get("oversold", 10)), float(cfg.get("overbought", 90))
        self.exit_sma = int(cfg.get("exit_sma", 5))
        self.max_days = int(cfg.get("max_hold_days", 10))
        self.stop_atr = float(cfg.get("stop_atr", 3.0))
        self.atr_n = int(cfg.get("atr_days", 20))
        self.long_only = cfg.get("long_only", False)
        self.score = float(cfg.get("score", 55))
        self.d = _Daily()
        self.held = 0
        self.pending = 0

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        new_day = self.d.update(bar, local_day)
        pos = broker.position()
        if pos is not None and manages(pos, self.NAME):
            if new_day:
                self.held += 1
                sma = self.d.sma(self.exit_sma)
                last = self.d.days[-1][3]
                done = sma is not None and ((pos.side == 1 and last > sma) or (pos.side == -1 and last < sma))
                if done or self.held >= self.max_days:
                    broker.close_position("pullback_exit" if done else "time_exit")
            return None
        if pos is not None:
            return None
        if new_day:
            self.pending = 0
            trend, rsi, atr = self.d.sma(self.trend_n), self.d.rsi(self.rsi_n), self.d.atr(self.atr_n)
            if trend is None or rsi is None or atr is None:
                return None
            last = self.d.days[-1][3]
            if last > trend and rsi < self.lo:
                self.pending = 1
            elif last < trend and rsi > self.hi and not self.long_only:
                self.pending = -1
            self.pending_atr = atr
        if not self.pending:
            return None
        s = self.pending
        stop = bar.close - s * self.stop_atr * self.pending_atr
        o = _order(s, bar.close, stop, None, bar, self.pip, broker, risk,
                   "dpb_long" if s == 1 else "dpb_short")
        if o:
            self.held = 0
            return TradeProposal(o, self.score, self.NAME)
        return None

    def mark_fired(self):
        self.pending = 0

    def describe(self, local_min=None):
        out = {"lines": [], "boxes": [], "status": ""}
        trend, rsi = self.d.sma(self.trend_n), self.d.rsi(self.rsi_n)
        if trend is None or rsi is None:
            out["status"] = f"Pullback: warming up ({len(self.d.days)}/{self.trend_n} days of history)"
            return out
        last = self.d.days[-1][3]
        exit_sma = self.d.sma(self.exit_sma)
        out["lines"].append({"price": trend, "label": f"{self.trend_n}-day average (pullback trend)",
                             "color": "silver", "style": "dot"})
        if exit_sma is not None:
            out["lines"].append({"price": exit_sma, "label": f"{self.exit_sma}-day average (pullback exit)",
                                 "color": "dimgray", "style": "dot"})
        up = last > trend
        want = (f"buy if the 2-day RSI closes below {self.lo:g}" if up else
                ("no shorts (long only)" if self.long_only else
                 f"sell if the 2-day RSI closes above {self.hi:g}"))
        out["status"] = (f"Pullback: trend {'UP' if up else 'DOWN'}; 2-day RSI {rsi:.0f}; {want}"
                         + ("; ENTRY SIGNAL today" if self.pending else ""))
        return out

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()


class VolBreakout:
    NAME = "vol_breakout"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.k = float(cfg.get("k", 0.5))
        self.start = _minutes(cfg.get("entry_start", "07:00"))
        self.end = _minutes(cfg.get("entry_end", "16:00"))
        self.exit_min = _minutes(cfg.get("exit_time", "21:00"))
        self.stop_k = float(cfg.get("stop_range", 0.5))     # stop = entry -/+ stop_range x yesterday's range
        self.target_rr = cfg.get("target_rr", None)
        self.trend_n = cfg.get("trend_sma", 50)
        self.be = float(cfg.get("trail_to_breakeven_rr", 0.0))
        self.score = float(cfg.get("score", 50))
        self._skip = set(int(x) for x in cfg.get("skip_days", []))
        self.d = _Daily()
        self.levels = None
        self.traded = False

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        if self.d.update(bar, local_day):
            self.traded = False
            self.levels = None
            if self.d.days:
                o, h, l, c = self.d.days[-1]
                rng = h - l
                dow = self.d.key.weekday()
                if rng > 0 and dow not in self._skip:
                    trend = self.d.sma(self.trend_n) if self.trend_n else None
                    self.levels = (bar.open + self.k * rng, bar.open - self.k * rng, rng, trend, c)
        pos = broker.position()
        if pos is not None:
            if manages(pos, self.NAME):
                move_stop_to_breakeven(pos, broker, bar.close, self.be)
                if local_min >= self.exit_min:
                    broker.close_position("session_exit")
            return None
        if self.traded or not self.levels or not (self.start <= local_min < self.end):
            return None
        up, dn, rng, trend, yclose = self.levels
        side = 1 if bar.close > up else (-1 if bar.close < dn else 0)
        if side == 0:
            return None
        if trend is not None and ((side == 1 and yclose < trend) or (side == -1 and yclose > trend)):
            return None
        stop = bar.close - side * self.stop_k * rng
        target = bar.close + side * self.target_rr * self.stop_k * rng if self.target_rr else None
        o = _order(side, bar.close, stop, target, bar, self.pip, broker, risk,
                   "vbo_long" if side == 1 else "vbo_short")
        return TradeProposal(o, self.score, self.NAME) if o else None

    def mark_fired(self):
        self.traded = True

    def describe(self, local_min=None):
        """Chart overlay: today's buy/sell trigger levels, the day's open, the trend line,
        the entry window and the evening exit."""
        def hm(m):
            return f"{m // 60:02d}:{m % 60:02d}"
        out = {"lines": [], "boxes": [], "status": "", "vlines": [
            {"min": self.start, "label": "Breakout window opens", "color": "seagreen"},
            {"min": self.end, "label": "Breakout window closes", "color": "dimgray"},
            {"min": self.exit_min, "label": "Breakout trades closed", "color": "orangered"}]}
        if not self.levels:
            skip = self.d.key is not None and self.d.key.weekday() in self._skip
            out["status"] = ("Vol breakout: skip day (Mondays are skipped) - watching only" if skip
                             else f"Vol breakout: waiting for history ({len(self.d.days)} days)")
            return out
        up, dn, rng, trend, yclose = self.levels
        day_open = up - self.k * rng
        longs_ok = trend is None or yclose >= trend
        shorts_ok = trend is None or yclose <= trend
        stop = self.stop_k * rng
        out["lines"] += [
            {"price": up, "color": "seagreen" if longs_ok else "dimgray", "style": "dash",
             "label": ("BUY if a candle closes above" if longs_ok else "buy level (blocked: trend is down)")},
            {"price": dn, "color": "orangered" if shorts_ok else "dimgray", "style": "dash",
             "label": ("SELL if a candle closes below" if shorts_ok else "sell level (blocked: trend is up)")},
            {"price": day_open, "color": "white", "style": "dot",
             "label": f"day open (+/- {self.k:g} x yesterday's range {rng / self.pip:.0f}p)"},
        ]
        if trend is not None:
            out["lines"].append({"price": trend, "color": "silver", "style": "dot",
                                 "label": f"{self.trend_n}-day average (trend)"})
        side = "buys only" if longs_ok and not shorts_ok else ("sells only" if shorts_ok and not longs_ok else "both ways")
        if self.traded:
            msg = "traded today - done"
        elif local_min is not None and local_min < self.start:
            msg = f"window opens {hm(self.start)} London"
        elif local_min is not None and local_min >= self.end:
            msg = f"window closed ({hm(self.start)}-{hm(self.end)})"
        else:
            msg = f"watching until {hm(self.end)} London"
        out["status"] = (f"Vol breakout: trend {'UP' if longs_ok and not shorts_ok else 'DOWN' if shorts_ok and not longs_ok else 'FLAT'}"
                         f" -> {side}; {msg}; stop {stop / self.pip:.0f}p, stop to breakeven at +{self.be:g}R, "
                         f"closes {hm(self.exit_min)}")
        return out

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()


class NarrowRangeBreak:
    NAME = "nr_breakout"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.mode = cfg.get("pattern", "nr7")          # nr7 | inside | nr4
        self.start = _minutes(cfg.get("entry_start", "07:00"))
        self.end = _minutes(cfg.get("entry_end", "16:00"))
        self.exit_min = _minutes(cfg.get("exit_time", "21:00"))
        self.target_rr = cfg.get("target_rr", 2.0)
        self.trend_n = cfg.get("trend_sma", 50)
        self.be = float(cfg.get("trail_to_breakeven_rr", 1.0))
        self.score = float(cfg.get("score", 52))
        self.d = _Daily()
        self.setup = None
        self.traded = False

    def _is_setup(self):
        d = self.d.days
        if self.mode == "inside":
            return len(d) >= 2 and d[-1][1] < d[-2][1] and d[-1][2] > d[-2][2]
        n = 7 if self.mode == "nr7" else 4
        if len(d) < n:
            return False
        rngs = [x[1] - x[2] for x in d[-n:]]
        return rngs[-1] == min(rngs)

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        if self.d.update(bar, local_day):
            self.traded = False
            self.setup = None
            if self.d.days and self._is_setup():
                o, h, l, c = self.d.days[-1]
                trend = self.d.sma(self.trend_n) if self.trend_n else None
                self.setup = (h, l, trend, c)
        pos = broker.position()
        if pos is not None:
            if manages(pos, self.NAME):
                move_stop_to_breakeven(pos, broker, bar.close, self.be)
                if local_min >= self.exit_min:
                    broker.close_position("session_exit")
            return None
        if self.traded or not self.setup or not (self.start <= local_min < self.end):
            return None
        h, l, trend, yclose = self.setup
        side = 1 if bar.close > h else (-1 if bar.close < l else 0)
        if side == 0:
            return None
        if trend is not None and ((side == 1 and yclose < trend) or (side == -1 and yclose > trend)):
            return None
        stop = l if side == 1 else h
        dist = (bar.close - stop) * side
        target = bar.close + side * self.target_rr * dist if self.target_rr else None
        o = _order(side, bar.close, stop, target, bar, self.pip, broker, risk,
                   "nrb_long" if side == 1 else "nrb_short")
        return TradeProposal(o, self.score, self.NAME) if o else None

    def mark_fired(self):
        self.traded = True

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()
