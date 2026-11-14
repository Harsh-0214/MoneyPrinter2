"""ICT "1-2-3" fair-value-gap strategy (from a YouTube video, Nov 2026). Research only.

Rules as coded (the video's rules made strict so they can be tested):
  * Daily fair value gap (FVG): three completed London days d1, d2, d3. Bullish gap when
    d3.low > d1.high (zone d1.high .. d3.low, acts as support); bearish gap when d3.high < d1.low
    (zone d3.high .. d1.low, resistance). A gap stays valid until a daily close goes through its
    far edge, or `max_zone_days` pass. Each gap is traded at most once.
  * Touch: a 1-minute bar trades into the zone.
  * Confirmation ("1-2-3"): on the 1-, 2- and 3-minute bars, an FVG in the OPPOSITE direction of
    the trade (e.g. a bearish FVG left by the drop into a bullish daily zone) is closed through
    = "inverted". All three timeframes must invert in the trade's direction, each within
    `window_min` minutes, after the zone was touched (minus `window_min`). The trade enters at the
    close of the 1-minute bar on which the last of the three completes.
  * Stop: beyond the far edge of the daily zone (+ `stop_buffer_atr` x daily ATR).
  * Target: `target` = "fvg15" -> near edge of the nearest unmitigated 15-minute FVG in the trade's
    direction (2R if none); "fvg15_min1r" -> same but skip the trade if that is < 1R away;
    "2r" / "3r" -> fixed; "none" -> time exit only.
  * Exit at `exit_time` London if still open. Entries only inside `session`.
"""
from datetime import time
from typing import Optional

from .daily_patterns import _Daily, _order
from .proposal import TradeProposal, manages


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class _TF:
    """Builds `n`-minute bars from 1-minute bars; finds FVGs and their inversions."""

    def __init__(self, n, keep=40):
        self.n, self.keep = n, keep
        self.key, self.cur, self.bars = None, None, []
        self.fvgs = []                  # dicts: dir (+1 bull / -1 bear), lo, hi, t, inverted_at, mitigated
        self.last_inv = {1: None, -1: None}   # time of the last inversion that favours longs / shorts

    def update(self, bar):
        """Feed one 1-minute bar. Returns True when an n-minute bar completed."""
        k = int(bar.Index.value // (60_000_000_000 * self.n))
        done = False
        if k != self.key:
            if self.cur is not None:
                self._close(self.cur)
                done = True
            self.key = k
            self.cur = [bar.open, bar.high, bar.low, bar.close, bar.Index]
        else:
            c = self.cur
            c[1], c[2], c[3] = max(c[1], bar.high), min(c[2], bar.low), bar.close
        return done

    def _close(self, b):
        o, h, l, c, t = b
        self.bars.append(b)
        if len(self.bars) > 3:
            self.bars.pop(0)
        for g in self.fvgs:                                  # inversions / mitigation on this close
            if g["inverted_at"] is None:
                if g["dir"] == -1 and c > g["hi"]:
                    g["inverted_at"] = t
                    self.last_inv[1] = t                     # bearish gap closed through: bullish signal
                elif g["dir"] == 1 and c < g["lo"]:
                    g["inverted_at"] = t
                    self.last_inv[-1] = t
            if not g["mitigated"] and h >= g["lo"] and l <= g["hi"] and g["t"] < t:
                g["mitigated"] = True
        if len(self.bars) == 3:
            b1, _, b3 = self.bars
            if b3[2] > b1[1]:
                self.fvgs.append(dict(dir=1, lo=b1[1], hi=b3[2], t=t, inverted_at=None, mitigated=False))
            elif b3[1] < b1[2]:
                self.fvgs.append(dict(dir=-1, lo=b3[1], hi=b1[2], t=t, inverted_at=None, mitigated=False))
            if len(self.fvgs) > self.keep:
                self.fvgs.pop(0)


class FVG123:
    NAME = "fvg123"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.window = int(cfg.get("window_min", 30))
        self.target = cfg.get("target", "fvg15")
        self.buffer_atr = float(cfg.get("stop_buffer_atr", 0.05))
        self.max_zone_days = int(cfg.get("max_zone_days", 30))
        s, e = cfg.get("session", ["00:00", "23:59"])
        self.s_start, self.s_end = _minutes(s), _minutes(e)
        self.exit_min = _minutes(cfg.get("exit_time", "21:00"))
        self.tfs_needed = tuple(cfg.get("timeframes", [1, 2, 3]))
        self.score = float(cfg.get("score", 50))
        self.d = _Daily(keep=60)
        self.tf = {n: _TF(n) for n in set(self.tfs_needed) | {15}}
        self.zones = []           # dicts: dir, lo, hi, age, touched_at, traded
        self.pending_zone = None

    # ---------------------------------------------------------------- daily zones
    def _new_day(self):
        d = self.d.days
        for z in self.zones:
            z["age"] += 1
        if d:
            c = d[-1][3]
            self.zones = [z for z in self.zones if z["age"] <= self.max_zone_days and not z["traded"]
                          and not (z["dir"] == 1 and c < z["lo"]) and not (z["dir"] == -1 and c > z["hi"])]
        if len(d) >= 3:
            (_, h1, l1, _), _, (_, h3, l3, _) = d[-3], d[-2], d[-1]
            if l3 > h1:
                self.zones.append(dict(dir=1, lo=h1, hi=l3, age=0, touched_at=None, traded=False))
            elif h3 < l1:
                self.zones.append(dict(dir=-1, lo=h3, hi=l1, age=0, touched_at=None, traded=False))
        for z in self.zones:
            z["touched_at"] = None                           # a touch counts for the day it happens

    def _target(self, side, entry, stop):
        risk = abs(entry - stop)
        if self.target in ("2r", "3r"):
            return entry + side * float(self.target[0]) * risk, True
        if self.target == "none":
            return None, True
        best = None
        for g in self.tf[15].fvgs:
            if g["mitigated"] or g["inverted_at"] is not None or g["dir"] != -side:
                continue
            edge = g["lo"] if side == 1 else g["hi"]
            if (edge - entry) * side > 0 and (best is None or (edge - entry) * side < (best - entry) * side):
                best = edge
        if best is None:
            return entry + side * 2 * risk, True
        if self.target == "fvg15_min1r" and abs(best - entry) < risk:
            return None, False
        return best, True

    # ---------------------------------------------------------------- main
    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        if self.d.update(bar, local_day):
            self._new_day()
        for t in self.tf.values():
            t.update(bar)
        pos = broker.position()
        if pos is not None:
            if manages(pos, self.NAME) and local_min >= self.exit_min:
                broker.close_position("session_exit")
            return None
        for z in self.zones:
            if z["touched_at"] is None and bar.low <= z["hi"] and bar.high >= z["lo"]:
                z["touched_at"] = bar.Index
        if not (self.s_start <= local_min < self.s_end) or local_min >= self.exit_min:
            return None
        atr = self.d.atr(14)
        if atr is None:
            return None
        win = self.window * 60_000_000_000
        now = bar.Index.value
        for z in self.zones:
            if z["traded"] or z["touched_at"] is None:
                continue
            side = z["dir"]
            since = z["touched_at"].value - win
            ok = True
            for n in self.tfs_needed:
                t_inv = self.tf[n].last_inv[side]
                if t_inv is None or t_inv.value < since or now - t_inv.value > win:
                    ok = False
                    break
            if not ok:
                continue
            stop = (z["lo"] - self.buffer_atr * atr) if side == 1 else (z["hi"] + self.buffer_atr * atr)
            if (bar.close - stop) * side <= 0:
                z["traded"] = True                           # already through the zone: dead
                continue
            target, take = self._target(side, bar.close, stop)
            if not take:
                z["traded"] = True
                continue
            o = _order(side, bar.close, stop, target, bar, self.pip, broker, risk,
                       "fvg_long" if side == 1 else "fvg_short")
            if o:
                self.pending_zone = z
                return TradeProposal(o, self.score, self.NAME)
        return None

    def mark_fired(self):
        if self.pending_zone is not None:
            self.pending_zone["traded"] = True
            self.pending_zone = None

    def describe(self, local_min=None):
        return {"lines": [], "boxes": [], "status": f"FVG 1-2-3: {len(self.zones)} daily gaps active"}

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()
