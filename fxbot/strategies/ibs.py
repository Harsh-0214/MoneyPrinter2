"""IBS mean reversion on US stock indices (Nov 18 2026; research: run_round3.py, run_ibs_realistic.py).

IBS = (close - day low) / (day high - day low). A close near the day's low in a US index tends
to bounce over the next few days (published effect; here profitable on SPX500 / NAS100 / US30
2001-20 on daily bars, 2021-25 and 2026; European / Asian indices fail).

Runs on 1-hour candles. The trading day is 18:00 New York (the evening before) to 16:00 New York
(US cash close); bars 16:00-18:00 belong to no day (CFD rollover / halt). When the 15:00-16:00
candle closes, using its close as "the 16:00 price":
  * open trade: sell if the 16:00 price is above the previous day's high, or after `max_days`
    16:00 decisions (default 5);
  * no trade: buy if IBS < `entry_ibs` (default 0.2) [and above the `trend_sma`-day average of
    16:00 prices, if set]. Stop `stop_range` x the average day range (last 20 days) below the
    entry - a catastrophic stop the research version did not have; it also sets the size (R).
Long only (the effect is a bounce after weak closes; shorts after strong closes lose in the tests).
"""
from collections import deque
from typing import Optional

import pandas as pd

from .daily_patterns import _order
from .proposal import TradeProposal, manages

NY = "America/New_York"


class IBSReversion:
    NAME = "ibs"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.entry_ibs = float(cfg.get("entry_ibs", 0.2))
        self.max_days = int(cfg.get("max_days", 5))
        self.stop_k = float(cfg.get("stop_range", 2.0))
        self.range_days = int(cfg.get("range_days", 20))
        self.trend_n = cfg.get("trend_sma")
        self.decide_hour = int(cfg.get("decide_hour_ny", 15))      # the 15:00-16:00 NY candle
        self.score = float(cfg.get("score", 50))
        self.key = None                     # current NY trading day
        self.hi = self.lo = None
        self.days = deque(maxlen=max(250, int(self.trend_n or 0) + 5))   # (hi, lo, c16) per complete day
        self.held = 0                       # 16:00 decisions since entry
        self.last = None                    # latest decision, for the status line
        self.skip_note = None

    @property
    def traded(self):
        return False

    def _avg_range(self):
        r = [h - l for h, l, _ in list(self.days)[-self.range_days:]]
        return sum(r) / len(r) if len(r) >= self.range_days else None

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        t = pd.Timestamp(bar.Index)
        ny = (t.tz_localize("UTC") if t.tzinfo is None else t).tz_convert(NY)
        key = (ny + pd.Timedelta(hours=6)).normalize()
        if key != self.key:
            self.key, self.hi, self.lo = key, None, None
        if 16 <= ny.hour < 18:                       # after the cash close: no day owns these bars
            return None
        self.hi = bar.high if self.hi is None else max(self.hi, bar.high)
        self.lo = bar.low if self.lo is None else min(self.lo, bar.low)
        if ny.hour != self.decide_hour:
            return None
        c16 = bar.close
        prev_high = self.days[-1][0] if self.days else None
        self.days.append((self.hi, self.lo, c16))
        rng = self.hi - self.lo
        ibs = (c16 - self.lo) / rng if rng > 0 else 0.5
        pos = broker.position()
        if pos is not None:
            if not manages(pos, self.NAME):
                return None
            self.held += 1
            if (prev_high is not None and c16 > prev_high) or self.held >= self.max_days:
                if ibs < self.entry_ibs:
                    # the exit and a new buy signal on the same close: selling and re-buying is
                    # holding minus a spread, so keep the trade and restart the count
                    self.held = 0
                    self.last = f"exit due, but IBS {ibs:.2f} is a new buy signal: holding, count restarted"
                    return None
                broker.close_position("ibs_exit")
                self.last = f"sold at {c16:g} ({'above the previous high' if prev_high and c16 > prev_high else f'{self.held} days held'})"
                return None
            above = f", sell above {prev_high:g}" if prev_high is not None else ""
            self.last = f"holding ({self.held} of {self.max_days} days){above}"
            return None
        avg = self._avg_range()
        if avg is None:
            self.last = f"waiting for history ({len(self.days)} of {self.range_days} days)"
            return None
        if self.trend_n:
            closes = [c for _, _, c in self.days][-int(self.trend_n):]
            if len(closes) < int(self.trend_n) or c16 <= sum(closes) / len(closes):
                if ibs < self.entry_ibs:
                    self.skip_note = ("trend", f"IBS {ibs:.2f} is below {self.entry_ibs:g}, but the index is under "
                                               f"its {self.trend_n}-day average")
                self.last = f"IBS {ibs:.2f}; below the {self.trend_n}-day average, no buys"
                return None
        if ibs >= self.entry_ibs:
            self.last = f"IBS {ibs:.2f} (buy below {self.entry_ibs:g})"
            return None
        stop = c16 - self.stop_k * avg
        o = _order(1, c16, stop, None, bar, self.pip, broker, risk, "ibs_long")
        self.last = f"IBS {ibs:.2f} < {self.entry_ibs:g}: buy at {c16:g}, stop {stop:g}"
        if o is None:
            return None
        return TradeProposal(o, self.score, self.NAME)

    def mark_fired(self):
        self.held = 0

    def describe(self, local_min=None):
        status = "IBS: " + (self.last or "waiting for the 16:00 New York close")
        lines = []
        if self.hi is not None:
            lines.append({"price": self.lo + self.entry_ibs * (self.hi - self.lo), "color": "seagreen",
                          "style": "dash", "label": f"BUY at 16:00 NY if below (IBS {self.entry_ibs:g})"})
        return {"lines": lines, "boxes": [], "status": status}

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()
