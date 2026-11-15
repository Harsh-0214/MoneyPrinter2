"""One-account replay of the decision system (run_selector.py S1 picks) added to the live bot, real limits.
Arsenal trades get the median notional of the live trades on the same market (approximation)."""
import os, sys
os.chdir(r"C:\Users\harsh\MoneyPrinter2"); sys.path.insert(0, os.getcwd())
import numpy as np, pandas as pd
import run_selector as S, run_portfolio_add as A
from run_portfolio import replay, stats
t = S.conditions(S.load_trades())
live_raw = pd.read_csv("results/portfolio_trades_hist.csv")
lev_mk = live_raw.groupby("market").lev_per_1pct.median().to_dict()     # approx notional for arsenal trades
lev_mk.setdefault("AUDUSD", lev_mk.get("EURUSD", 3.0))
picked = []
for y in S.YEARS:
    train, test = t[t.year < y], t[t.year == y]
    ok1 = {k for k, g in train.groupby(["strategy", "market", "vol", "trend_c"]) if S._good(g.r_multiple, 20)}
    s1 = test[np.array([k in ok1 for k in zip(test.strategy, test.market, test.vol, test.trend_c)]) & ~test.live.to_numpy()]
    picked.append(s1)
picked = pd.concat(picked)
lv = live_raw.copy()
for c in ("entry_time", "exit_time"):
    lv[c] = pd.to_datetime(lv[c], utc=True)
lv = lv[(lv.entry_time >= "2022-01-01") & (lv.entry_time < "2026-01-01")]
ex = picked.assign(unit="SEL " + picked.strategy + "|" + picked.market,
                   lev_per_1pct=picked.market.map(lev_mk), exit_reason="", tag="")
ex = ex[["unit", "market", "entry_time", "exit_time", "side", "r_multiple", "lev_per_1pct", "exit_reason", "tag"]]
for name, tr in [("live bot as it is", lv), ("live bot + decision-system picks", pd.concat([lv, ex]))]:
    tr = tr.sort_values("entry_time").reset_index(drop=True)
    w = {u: 4 / 3 for u in tr.unit.unique()}
    out = []
    for lab, s, e in [("2022-23", "2022-01-01", "2024-01-01"), ("2024-25", "2024-01-01", "2026-01-01")]:
        part = tr[(tr.entry_time >= s) & (tr.entry_time < e)].reset_index(drop=True)
        eq, taken = replay(part, 3.0, A.LIVE, A.MAX_LEV, weights=w)
        st = stats(eq)
        live_taken = int(taken[~part.unit.str.startswith("SEL ").to_numpy()].sum())
        out.append(f"{lab}: avg month {st['geo_month']:.2f}%, max DD {st['maxdd']:.1f}%, trades taken {int(taken.sum())} "
                   f"(live strategy trades taken {live_taken} of {int((~part.unit.str.startswith('SEL ')).sum())})")
    eq, taken = replay(tr, 3.0, A.LIVE, A.MAX_LEV, weights=w, start_eq=3000)
    print(name, "|", " | ".join(out), f"| $3,000 from 2022 -> {eq.iloc[-1]:,.0f}")
