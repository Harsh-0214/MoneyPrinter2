"""ICT / "smart money" setups with strict, testable definitions. Research only.

One class, `setup` picks the rule. All work on the bars they are run on (5 or 15 min):
swings are k-bar fractals (confirmed k bars later); structure breaks are closes through the
last unbroken swing; ATR is the 14-bar average range. Bullish versions described; shorts mirror.

  fvg         Fair value gap retest. A 3-bar gap up (bar3.low > bar1.high) whose middle bar is a
              displacement (range >= 1 x ATR). Buy the first return into the gap; stop under bar 1.
  ifvg        Inverse FVG retest. A gap DOWN that a later bar closes above (inverted) becomes
              support. Buy the first return into it; stop 0.25 ATR under it.
  ob          Order block. On a close above the last swing high, the last down-close bar before the
              move is the block. Buy the first return into its range; stop under it.
  breaker     Breaker block. A lower low (sweep of the previous swing low) followed by a close above
              the swing high between them: that swing-high bar's range becomes support. Buy the return.
  ote         Optimal trade entry. After a close above the last swing high, buy a pullback into the
              62-79% retracement of the leg (last swing low -> the high made since); stop under the
              leg's low; target the leg's high.
  silver      Silver Bullet. The first displacement FVG formed inside 03-04, 10-11 or 14-15 New York;
              enter on the return into it within 2 hours; stop beyond bar 1.
  sd          Supply and demand. 1-3 small bars (each <= 0.75 ATR) then a displacement bar (range >=
              2 ATR, body >= 60%) up: the base is a demand zone. Buy the first return; stop under it.
  sr          Support / resistance. Two swing lows within 0.15 ATR of each other (last 150 bars) make
              support. Buy a touch that closes back above it on an up bar; stop 0.3 ATR under the lows.
  sweep_choch Liquidity sweep + change of character. Price trades under the last swing low, then
              closes above the last swing high: buy; stop under the sweep's low.
  bos         Break of structure continuation. In an up-structure, a close above the last swing high:
              buy; stop under the last swing low.
  po3         Power of 3 on the day. With the daily trend up, price trades >= 0.25 x daily ATR under
              the New York midnight open (manipulation) and then closes back above it: buy; stop
              under the day's low. One per day.

Common: target = `rr` x risk unless the setup names its own; `trend_filter` = only with the 50-day
trend (bar.daily_ema); entries 07:00-20:00 London (silver: its own windows); every trade closed at
21:00 London; one position at a time; a zone is used once and expires after `zone_bars` bars.
"""
from typing import Optional

from .daily_patterns import _Daily, _order
from .proposal import TradeProposal, manages

SETUPS = ("fvg", "ifvg", "ob", "breaker", "ote", "silver", "sd", "sr", "sweep_choch", "bos", "po3")


class SMC:
    NAME = "smc"

    def __init__(self, cfg, pip):
        self.pip = pip
        self.setup = cfg.get("setup", "fvg")
        self.rr = float(cfg.get("rr", 2.0))
        self.trend_filter = bool(cfg.get("trend_filter", False))
        self.k = int(cfg.get("swing_k", 2))
        self.zone_bars = int(cfg.get("zone_bars", 96))
        self.max_per_day = int(cfg.get("max_per_day", 2))
        self.exit_min = 21 * 60
        self.b = []                     # bars: (t, o, h, l, c)
        self.atr = None
        self._rng = []
        self.sw_hi, self.sw_lo = [], []          # confirmed swings: [index, price, broken]
        self.struct = 0                 # +1 after an up-break, -1 after a down-break
        self.zones = []                 # dict(side, lo, hi, stop, born, target, until)
        self.day, self.n_today = None, 0
        self.d = _Daily(keep=40)
        self.pending = None
        self.sweep = {1: None, -1: None}         # sweep_choch: (extreme, index)
        self.ote = {1: None, -1: None}           # (leg origin, leg extreme, born)
        self.ny_open, self.ny_day, self.po3_done = None, None, False
        self.day_hi = self.day_lo = None
        self.sb_window, self.sb_done = None, False

    # ---------------------------------------------------------------- structure
    def _add_bar(self, bar):
        self.b.append((bar.Index, bar.open, bar.high, bar.low, bar.close))
        if len(self.b) > 600:
            drop = len(self.b) - 600
            self.b = self.b[drop:]
            for lst in (self.sw_hi, self.sw_lo):
                for s in lst:
                    s[0] -= drop
            self.sw_hi = [s for s in self.sw_hi if s[0] >= 0]
            self.sw_lo = [s for s in self.sw_lo if s[0] >= 0]
            for z in self.zones:
                z["born"] -= drop
                if "idx" in z:
                    z["idx"] -= drop
            for side in (1, -1):
                if self.sweep[side]:
                    self.sweep[side] = (self.sweep[side][0], self.sweep[side][1] - drop)
                if self.ote[side]:
                    self.ote[side][2] -= drop
        self._rng.append(bar.high - bar.low)
        if len(self._rng) > 14:
            self._rng.pop(0)
        self.atr = sum(self._rng) / len(self._rng) if len(self._rng) == 14 else None
        k, n = self.k, len(self.b)
        if n >= 2 * k + 1:
            i = n - k - 1
            h, l = self.b[i][2], self.b[i][3]
            win = self.b[i - k:i] + self.b[i + 1:i + k + 1]
            if all(h > x[2] for x in win):
                self.sw_hi.append([i, h, False])
            if all(l < x[3] for x in win):
                self.sw_lo.append([i, l, False])
            self.sw_hi, self.sw_lo = self.sw_hi[-30:], self.sw_lo[-30:]

    def _breaks(self, c):
        """Structure breaks on this close: list of (direction, swing) for unbroken swings closed through."""
        out = []
        if self.sw_hi and not self.sw_hi[-1][2] and c > self.sw_hi[-1][1]:
            self.sw_hi[-1][2] = True
            out.append((1, self.sw_hi[-1]))
        if self.sw_lo and not self.sw_lo[-1][2] and c < self.sw_lo[-1][1]:
            self.sw_lo[-1][2] = True
            out.append((-1, self.sw_lo[-1]))
        return out

    def _zone(self, side, lo, hi, stop, target=None, bars=None, **kw):
        if hi <= lo:
            return
        n = len(self.b) - 1
        self.zones.append(dict(side=side, lo=lo, hi=hi, stop=stop, born=n, target=target,
                               until=n + (bars or self.zone_bars), **kw))
        self.zones = self.zones[-40:]

    # ---------------------------------------------------------------- setup detectors (called on each close)
    def _detect(self, bar, lmin):
        b, a, n = self.b, self.atr, len(self.b) - 1
        if a is None or n < 20:
            return None                                            # immediate order: (side, stop, target)
        o, h, l, c = bar.open, bar.high, bar.low, bar.close
        buf = 0.1 * a
        s = self.setup
        b1, b2, b3 = b[-3], b[-2], b[-1]
        gap_up = b3[3] > b1[2] and (b2[2] - b2[3]) >= a
        gap_dn = b3[2] < b1[3] and (b2[2] - b2[3]) >= a

        if s in ("fvg", "silver"):
            ok = True
            if s == "silver":
                ny = bar.Index.tz_convert("America/New_York")
                win = ny.hour if ny.hour in (3, 10, 14) else None
                key = (ny.date(), win)
                if key != self.sb_window:
                    self.sb_window, self.sb_done = key, False
                ok = win is not None and not self.sb_done
            if ok and gap_up:
                self._zone(1, b1[2], b3[3], b1[3] - buf, bars=24 if s == "silver" else None)
                self.sb_done = True
            elif ok and gap_dn:
                self._zone(-1, b3[2], b1[3], b1[2] + buf, bars=24 if s == "silver" else None)
                self.sb_done = True

        elif s == "ifvg":
            if b3[3] > b1[2]:
                self._zone(1, b1[2], b3[3], None, watch=True)        # raw gaps, waiting to be inverted
            elif b3[2] < b1[3]:
                self._zone(-1, b3[2], b1[3], None, watch=True)
            for z in self.zones:
                if z.get("watch") and z["born"] < n:
                    if z["side"] == -1 and c > z["hi"]:               # bearish gap closed above -> support
                        z.update(side=1, watch=False, stop=z["lo"] - 0.25 * a, born=n, until=n + self.zone_bars)
                    elif z["side"] == 1 and c < z["lo"]:
                        z.update(side=-1, watch=False, stop=z["hi"] + 0.25 * a, born=n, until=n + self.zone_bars)

        elif s == "sd":
            body = abs(c - o)
            if (h - l) >= 2 * a and body >= 0.6 * (h - l):
                base = []
                for x in reversed(b[-4:-1]):
                    if (x[2] - x[3]) <= 0.75 * a:
                        base.append(x)
                    else:
                        break
                if base:
                    lo, hi = min(x[3] for x in base), max(x[2] for x in base)
                    if c > o:
                        self._zone(1, lo, hi, lo - buf, bars=192)
                    else:
                        self._zone(-1, lo, hi, hi + buf, bars=192)

        elif s == "sr":
            for side, sw in ((1, self.sw_lo), (-1, self.sw_hi)):
                pts = [x for x in sw if n - x[0] <= 150]
                if len(pts) < 2:
                    continue
                p1, p2 = pts[-2][1], pts[-1][1]
                if abs(p1 - p2) > 0.15 * a:
                    continue
                lvl = (p1 + p2) / 2
                if side == 1 and l <= lvl + 0.1 * a and c > lvl and c > o:
                    return (1, min(p1, p2) - 0.3 * a, None)
                if side == -1 and h >= lvl - 0.1 * a and c < lvl and c < o:
                    return (-1, max(p1, p2) + 0.3 * a, None)

        elif s == "sweep_choch":
            if self.sw_lo and l < self.sw_lo[-1][1] and self.sw_lo[-1][0] < n:
                ext = l if self.sweep[1] is None else min(l, self.sweep[1][0])
                self.sweep[1] = (ext, n)
            if self.sw_hi and h > self.sw_hi[-1][1] and self.sw_hi[-1][0] < n:
                ext = h if self.sweep[-1] is None else max(h, self.sweep[-1][0])
                self.sweep[-1] = (ext, n)
            for side in (1, -1):
                sw = self.sweep[side]
                if sw and n - sw[1] > 24:
                    self.sweep[side] = sw = None
                if not sw:
                    continue
                ref = self.sw_hi if side == 1 else self.sw_lo
                if ref and ((c > ref[-1][1]) if side == 1 else (c < ref[-1][1])) and n > sw[1]:
                    self.sweep[side] = None
                    return (side, sw[0] - side * buf, None)

        brk = self._breaks(c) if s in ("ob", "breaker", "ote", "bos") else []
        for direction, swing in brk:
            prev_struct, self.struct = self.struct, direction
            if s == "bos" and prev_struct == direction:
                opp = self.sw_lo if direction == 1 else self.sw_hi
                if opp:
                    return (direction, opp[-1][1] - direction * buf, None)
            elif s == "ob":
                for x in reversed(b[max(0, n - 20):n]):
                    if (direction == 1 and x[4] < x[1]) or (direction == -1 and x[4] > x[1]):
                        if direction == 1:
                            self._zone(1, x[3], x[2], x[3] - buf)
                        else:
                            self._zone(-1, x[3], x[2], x[2] + buf)
                        break
            elif s == "breaker":
                # up-break of swing high H after a lower low: lows ... L1, [H], L2 < L1, then close > H
                if direction == 1 and len(self.sw_lo) >= 2:
                    l2, l1 = self.sw_lo[-1], self.sw_lo[-2]
                    if l1[0] < swing[0] < l2[0] and l2[1] < l1[1]:
                        x = b[swing[0]]
                        self._zone(1, x[3], x[2], x[3] - buf)
                if direction == -1 and len(self.sw_hi) >= 2:
                    h2, h1 = self.sw_hi[-1], self.sw_hi[-2]
                    if h1[0] < swing[0] < h2[0] and h2[1] > h1[1]:
                        x = b[swing[0]]
                        self._zone(-1, x[3], x[2], x[2] + buf)
            elif s == "ote":
                opp = self.sw_lo if direction == 1 else self.sw_hi
                if opp:
                    self.ote[direction] = [opp[-1][1], h if direction == 1 else l, n]
                    self.ote[-direction] = None
        if s == "ote":
            for side in (1, -1):
                leg = self.ote[side]
                if not leg:
                    continue
                org, ext, born = leg
                if n - born > self.zone_bars or (side == 1 and l < org) or (side == -1 and h > org):
                    self.ote[side] = None
                    continue
                size = (ext - org) * side
                z62, z79 = ext - side * 0.62 * size, ext - side * 0.79 * size
                touched = (l <= z62) if side == 1 else (h >= z62)
                inside = (c >= z79) if side == 1 else (c <= z79)
                if n > born and touched and inside and size > 2 * a:
                    self.ote[side] = None
                    return (side, org - side * buf, ext)
                if (side == 1 and h > ext) or (side == -1 and l < ext):
                    leg[1] = h if side == 1 else l

        if s == "po3":
            ny = bar.Index.tz_convert("America/New_York")
            if ny.date() != self.ny_day:
                self.ny_day, self.ny_open, self.po3_done = ny.date(), o, False
                self.day_hi, self.day_lo = h, l
            self.day_hi, self.day_lo = max(self.day_hi, h), min(self.day_lo, l)
            datr = self.d.atr(14)
            de = getattr(bar, "daily_ema", float("nan"))
            if datr and de == de and not self.po3_done and self.ny_open is not None:
                if c > de and self.ny_open - self.day_lo >= 0.25 * datr and c > self.ny_open and b[-2][4] <= self.ny_open:
                    self.po3_done = True
                    return (1, self.day_lo - buf, None)
                if c < de and self.day_hi - self.ny_open >= 0.25 * datr and c < self.ny_open and b[-2][4] >= self.ny_open:
                    self.po3_done = True
                    return (-1, self.day_hi + buf, None)
        return None

    def _zone_entry(self, bar):
        """First return into an active zone: (side, stop, target, zone) or None."""
        n = len(self.b) - 1
        keep, hit = [], None
        for z in self.zones:
            if z.get("watch"):
                if n <= z["until"]:
                    keep.append(z)
                continue
            if n > z["until"]:
                continue
            side = z["side"]
            if (side == 1 and bar.close < z["stop"]) or (side == -1 and bar.close > z["stop"]):
                continue                                               # closed through the stop: dead
            if hit is None and n > z["born"]:
                touch = (bar.low <= z["hi"]) if side == 1 else (bar.high >= z["lo"])
                if touch:
                    hit = (side, z["stop"], z["target"], z)
                    continue
            keep.append(z)
        self.zones = keep
        return hit

    # ---------------------------------------------------------------- main
    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        if self.d.update(bar, local_day):
            pass
        if local_day != self.day:
            self.day, self.n_today = local_day, 0
        self._add_bar(bar)
        sig = self._detect(bar, local_min)
        zone_sig = self._zone_entry(bar) if self.atr is not None else None
        pos = broker.position()
        if pos is not None:
            if manages(pos, self.NAME) and local_min >= self.exit_min:
                broker.close_position("session_exit")
            return None
        if self.n_today >= self.max_per_day or local_min >= self.exit_min - 30:
            return None
        if self.setup != "silver" and not (7 * 60 <= local_min < 20 * 60):
            return None
        if sig is None and zone_sig is not None:
            sig = zone_sig[:3]
        if sig is None:
            return None
        side, stop, target = sig
        if self.trend_filter:
            de = getattr(bar, "daily_ema", float("nan"))
            if de == de and ((side == 1 and bar.close < de) or (side == -1 and bar.close > de)):
                return None
        dist = (bar.close - stop) * side
        if self.atr is None or dist < 0.25 * self.atr:                 # stop unrealistically tight
            return None
        if target is None or (target - bar.close) * side <= 0:
            target = bar.close + side * self.rr * dist
        o = _order(side, bar.close, stop, target, bar, self.pip, broker, risk,
                   "smc_long" if side == 1 else "smc_short")
        return TradeProposal(o, 50, self.NAME) if o else None

    def mark_fired(self):
        self.n_today += 1

    def describe(self, local_min=None):
        return {"lines": [], "boxes": [], "status": f"SMC {self.setup}: {len(self.zones)} zones"}

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()
