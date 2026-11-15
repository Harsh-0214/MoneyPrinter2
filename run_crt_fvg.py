"""CRT + 1-2-3 FVG together: a trade only when both agree. Research only.

    python run_crt_fvg.py

On 1-minute bars:
  * CRT context: candle 1 = yesterday (London day). Today price sweeps yesterday's high (low) and a
    1-minute bar closes back inside yesterday's range -> short (long) setup, sweep extreme = today's
    high (low) so far (extends while today keeps sweeping). Valid today and tomorrow.
  * 1-2-3 entry: after the sweep extreme, an opposite FVG is closed through ("inverted") on the 1-,
    2- and 3-minute bars, all within 30 minutes; enter when the last completes.
  * Stop: beyond the sweep extreme (+0.05 x daily ATR). Target: yesterday's other end ("range"),
    the same but only if >= 1.5R ("range_rr1.5"), or the nearest unmitigated 15-min FVG ("fvg15").
  * Exit: stop, target, or the end of the day after entry. Entries all day or in active hours.
Markets and costs as run_fvg123.py. Pass: PF >= 1.15 on 2021-25, >= 4 of 5 years up (NAS100 also 2026).
"""
import os
from multiprocessing import Pool
from typing import Optional

import pandas as pd

import run_fvg123 as F
from fxbot.strategies.daily_patterns import _Daily, _order
from fxbot.strategies.fvg123 import _TF, _minutes
from fxbot.strategies.proposal import TradeProposal, manages


class CRTxFVG:
    NAME = "fvg123"                       # reuses the fvg_ tag family for position ownership

    def __init__(self, cfg, pip):
        self.pip = pip
        self.target = cfg.get("target", "range")
        s, e = cfg.get("session", ["00:00", "23:59"])
        self.s_start, self.s_end = _minutes(s), _minutes(e)
        self.window = 30 * 60 * 10**9
        self.d = _Daily(keep=40)
        self.tf = {n: _TF(n) for n in (1, 2, 3, 15)}
        self.c1 = None
        self.today = None                 # [high, high_t, low, low_t]
        self.setups = []                  # side, ext, ext_t, target, day_no, done
        self.day_no = 0
        self.entry_day = None
        self.armed_today = {1: False, -1: False}
        self.pending = None

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        if self.d.update(bar, local_day):
            self.day_no += 1
            self.c1 = self.d.days[-1] if self.d.days else None
            self.today = [bar.high, bar.Index, bar.low, bar.Index]
            self.armed_today = {1: False, -1: False}
            self.setups = [s for s in self.setups if not s["done"] and s["day_no"] >= self.day_no - 1]
        else:
            if bar.high > self.today[0]:
                self.today[0], self.today[1] = bar.high, bar.Index
            if bar.low < self.today[2]:
                self.today[2], self.today[3] = bar.low, bar.Index
        for t in self.tf.values():
            t.update(bar)
        pos = broker.position()
        if pos is not None:
            if manages(pos, self.NAME) and self.entry_day is not None and self.day_no >= self.entry_day + 2:
                broker.close_position("time_exit")
            return None
        if self.c1 is None:
            return None
        _, h1, l1, _ = self.c1
        # CRT: sweep + 1-minute close back inside yesterday's range
        if self.today[0] > h1 and l1 < bar.close < h1 and not self.armed_today[-1]:
            self.armed_today[-1] = True
            self.setups.append(dict(side=-1, ext=self.today[0], ext_t=self.today[1], target=l1,
                                    day_no=self.day_no, done=False))
        if self.today[2] < l1 and l1 < bar.close < h1 and not self.armed_today[1]:
            self.armed_today[1] = True
            self.setups.append(dict(side=1, ext=self.today[2], ext_t=self.today[3], target=h1,
                                    day_no=self.day_no, done=False))
        atr = self.d.atr(14)
        if atr is None or not (self.s_start <= local_min < self.s_end):
            return None
        now = bar.Index.value
        for s in self.setups:
            if s["done"]:
                continue
            side = s["side"]
            if (side == -1 and bar.high > s["ext"]) or (side == 1 and bar.low < s["ext"]):
                if s["day_no"] == self.day_no:          # still the sweep day: the sweep extends
                    s["ext"], s["ext_t"] = (bar.high if side == -1 else bar.low), bar.Index
                    continue
                s["done"] = True
                continue
            ok = all(self.tf[n].last_inv[side] is not None and self.tf[n].last_inv[side].value >= s["ext_t"].value
                     and now - self.tf[n].last_inv[side].value <= self.window for n in (1, 2, 3))
            if not ok:
                continue
            stop = s["ext"] + (0.05 * atr if side == -1 else -0.05 * atr)
            risk_d = (stop - bar.close) * (-side)
            if self.target == "fvg15":
                tgt = None
                for g in self.tf[15].fvgs:
                    if g["mitigated"] or g["inverted_at"] is not None or g["dir"] != -side:
                        continue
                    edge = g["lo"] if side == 1 else g["hi"]
                    if (edge - bar.close) * side > 0 and (tgt is None or abs(edge - bar.close) < abs(tgt - bar.close)):
                        tgt = edge
                tgt = tgt if tgt is not None else s["target"]
            else:
                tgt = s["target"]
            reward = (tgt - bar.close) * side
            if risk_d <= 0 or reward <= 0 or (self.target == "range_rr1.5" and reward / risk_d < 1.5):
                s["done"] = True
                continue
            o = _order(side, bar.close, stop, tgt, bar, self.pip, broker, risk, "fvg_long" if side == 1 else "fvg_short")
            if o:
                self.pending = s
                return TradeProposal(o, 50, self.NAME)
        return None

    def mark_fired(self):
        if self.pending is not None:
            self.pending["done"] = True
            self.pending = None
        self.entry_day = self.day_no

    def on_bar(self, *a):
        p = self.propose(*a)
        if p and a[3].submit(p.order):
            self.mark_fired()


def run_one(job):
    from fxbot.backtest import run_backtest
    mk, target, sess = job
    s = F.SESSIONS[sess]
    if isinstance(s, dict):
        s = s.get(mk, s["default"])
    c = F.make_cfg(mk, dict(name="crt_fvg", target=target, session=s))
    t, _ = run_backtest(F._BARS[mk], c, strategy_cls=CRTxFVG)
    row = dict(market=mk, target=target, session=sess, trades=len(t))
    if not len(t):
        return row
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    yr = t.entry_time.dt.year
    h = t[yr <= 2025]
    row.update(trades_yr=round(len(h) / 5, 1), win=round((h.r_multiple > 0).mean() * 100),
               avgR=round(h.r_multiple.mean(), 3), pf=F._pf(h), R21_25=round(h.r_multiple.sum(), 1),
               yrs_up=int(sum(h[h.entry_time.dt.year == y].r_multiple.sum() > 0 for y in range(2021, 2026))),
               y26=round(t[yr == 2026].r_multiple.sum(), 1))
    row["PASS"] = bool(row["pf"] >= 1.15 and row["yrs_up"] >= 4 and (mk != "NAS100" or row["y26"] > 0))
    return row


def main():
    markets = [m for m in F.FILES if os.path.exists(F.FILES[m])]
    jobs = [(m, tg, se) for m in markets for tg in ("range", "range_rr1.5", "fvg15") for se in F.SESSIONS]
    print(f"{len(jobs)} runs ...", flush=True)
    with Pool(6, initializer=F._init, initargs=(markets,)) as pool:
        rows = list(pool.imap_unordered(run_one, jobs))
    df = pd.DataFrame(rows).sort_values(["market", "target", "session"])
    df.to_csv("results/crt_fvg.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
