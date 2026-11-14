"""After a trade opens: can its first hours tell us it will lose, and does cutting it early pay?

    python run_early_exit.py

Rule tested on every live strategy: at a fixed time after entry, if the trade is below a
threshold (in R, the trade's own risk), close it at the next bar instead of waiting for the stop.
  London / USDJPY (intraday):  check 30 min, 1 h, 2 h, 4 h after entry
  Gold trend + add-ons:        check 1, 3, 5 days after entry
  GBP daily pullback:          check 1, 2 days after entry
  thresholds: below -0.5R, below -0.25R, not in profit (below 0R), below +0.25R
Scored in R at 1% risk: 2021-23 and 2024-25 histdata, 2026 the broker's own feed.
Also reports, for the eventual winners and losers, where they stood at each check time.
"""
import copy
import itertools
from multiprocessing import Pool

import numpy as np
import pandas as pd
import yaml

import fxbot.backtest as BT
from fxbot.brokers.sim_broker import SimBroker

BASE = yaml.safe_load(open("config.yaml"))
CHECKS = {"intraday": [30, 60, 120, 240], "trend": [1440, 4320, 7200], "pullback": [1440, 2880]}
THRESHOLDS = [-0.5, -0.25, 0.0, 0.25]
UNIT_KIND = {"EURUSD": "intraday", "GBPUSD": "intraday", "USDJPY": "intraday",
             "XAUUSD": "trend", "XAUUSD:fast": "trend", "XAUUSD:add55": "trend", "XAUUSD:add20": "trend",
             "GBPUSD:pullback": "pullback"}
_BARS = {}


class EarlyExitBroker(SimBroker):
    check_min, thr = None, None
    snapshots = None                        # {entry_time: {check_min: R at that time}}

    def on_bar(self, bar):
        super().on_bar(bar)
        p = self._pos
        if p is None or self._pending_close is not None:
            return
        elapsed = (bar.Index + self._bar_len - p.entry_time) / pd.Timedelta(minutes=1)
        spread = bar.spread_pips * self.pip
        px = bar.close if p.side == 1 else bar.close + spread
        r_now = p.side * (px - p.entry_price) / p.risk_per_unit if p.risk_per_unit > 0 else 0.0
        snap = self.snapshots.setdefault(p.entry_time, {})
        for c in CHECKS_ALL:
            if elapsed >= c and c not in snap:
                snap[c] = r_now
        if self.check_min and elapsed >= self.check_min and not getattr(p, "_checked", False):
            p._checked = True
            if r_now < self.thr:
                self._pending_close = "early_exit"


CHECKS_ALL = sorted(set(sum(CHECKS.values(), [])))


def _init():
    from run_validate import load_pairs
    from run_london_optimize import _bars_2026
    from run_more_trades import mt5_bars
    hist = load_pairs(BASE)
    b26 = _bars_2026()
    _BARS["hist"] = hist
    _BARS["2026"] = {"EURUSD": b26["EURUSD"], "GBPUSD": b26["GBPUSD"],
                     "USDJPY": mt5_bars("USDJPY", "M15", 0.01, 1.6),
                     "GBPUSD:pullback": mt5_bars("GBPUSD", "H1", 0.0001, 2.0)}
    g = mt5_bars("XAUUSD", "H1", 0.1, 8.0)
    for k in ("XAUUSD", "XAUUSD:fast", "XAUUSD:add55", "XAUUSD:add20"):
        _BARS["2026"][k] = g


def _run(job):
    unit, check, thr = job
    units = {u["key"]: u for u in BT.expand_units(BASE)}
    c = BT.pair_config(BASE, units[unit])
    c["smt"] = {}
    c["risk"]["risk_per_trade_pct"] = 1.0
    c["risk"]["max_leverage"] = 1000
    out = {"unit": unit, "check_min": check, "thr": thr}
    snaps_all = []
    for src in ("hist", "2026"):
        b = _BARS[src][unit]
        EarlyExitBroker.check_min, EarlyExitBroker.thr = check, thr
        EarlyExitBroker.snapshots = {}
        EarlyExitBroker._bar_len = (b.index[1:] - b.index[:-1]).min()
        orig = BT.SimBroker
        BT.SimBroker = EarlyExitBroker
        try:
            t, _ = BT.run_backtest(b, c)
        finally:
            BT.SimBroker = orig
        if not len(t):
            continue
        t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
        yr = t.entry_time.dt.year
        if src == "hist":
            out["R21_23"] = round(t.r_multiple[yr <= 2023].sum(), 2)
            out["R24_25"] = round(t.r_multiple[(yr >= 2024) & (yr <= 2025)].sum(), 2)
            out["n"] = int((yr <= 2025).sum())
            out["early_exits"] = int(((t.exit_reason == "early_exit") & (yr <= 2025)).sum())
            if check is None:
                s = pd.DataFrame([{"entry_time": k, **v} for k, v in EarlyExitBroker.snapshots.items()])
                if len(s):
                    snaps_all.append(t[["entry_time", "r_multiple"]].merge(s, on="entry_time", how="left"))
        else:
            o = t[yr == 2026]
            out["R26"] = round(o.r_multiple.sum(), 2)
            out["n26"] = len(o)
    return out, (snaps_all[0] if snaps_all else None)


def main():
    jobs = []
    for unit, kind in UNIT_KIND.items():
        jobs.append((unit, None, None))
        jobs += [(unit, c, th) for c, th in itertools.product(CHECKS[kind], THRESHOLDS)]
    print(f"{len(jobs)} runs ...", flush=True)
    rows, snaps = [], {}
    with Pool(6, initializer=_init) as pool:
        for r, s in pool.imap_unordered(_run, jobs):
            rows.append(r)
            if s is not None:
                snaps[r["unit"]] = s
    df = pd.DataFrame(rows)
    df.to_csv("results/early_exit.csv", index=False)
    base = df[df.check_min.isna()].set_index("unit")
    rule = df[df.check_min.notna()].copy()
    for col in ("R21_23", "R24_25", "R26"):
        rule[f"d_{col}"] = rule[col] - rule.unit.map(base[col])
    rule["better_all"] = (rule.d_R21_23 > 0) & (rule.d_R24_25 > 0) & (rule.d_R26 > 0)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print("\nBASELINE (no early exit):")
    print(base[["n", "R21_23", "R24_25", "R26", "n26"]].to_string())
    print("\nEARLY EXIT RULES: change in R vs baseline (positive = the rule helped)")
    print(rule[["unit", "check_min", "thr", "early_exits", "d_R21_23", "d_R24_25", "d_R26", "better_all"]]
          .sort_values(["unit", "check_min", "thr"]).to_string(index=False))
    print("\nWhere eventual winners and losers stood at each check (median R, share below 0R):")
    for unit, s in snaps.items():
        s = s.copy()
        s["outcome"] = np.where(s.r_multiple > 0, "winner", "loser")
        for c in CHECKS[UNIT_KIND[unit]]:
            if c in s:
                g = s.groupby("outcome")[c].agg(median="median", below0=lambda x: (x < 0).mean())
                print(f"  {unit:<16} after {c / 60:>5.1f} h: "
                      + "  ".join(f"{o}: median {g.loc[o, 'median']:+.2f}R, {g.loc[o, 'below0'] * 100:.0f}% under water"
                                  for o in g.index))


if __name__ == "__main__":
    main()
