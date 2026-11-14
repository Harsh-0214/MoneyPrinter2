"""What a candidate unit adds to the LIVE portfolio (real margin, risk brake, compounding).

    python run_portfolio_add.py                # every candidate below
    python run_portfolio_add.py --only jpy

Baseline = the live units' cached trades (results/portfolio_trades_{hist,mt5}.csv from
run_portfolio.py) replayed with the live risk: 3% per trade, gold + USDJPY 4%.
Each candidate's trades come from run_more_trades.run_variant (histdata 2021-25 for the
first two periods, the broker's own feed for 2026) and are added to, or replace, a live unit.
Pass = a higher average month in all three periods (2021-23, 2024-25, 2026) and a max
drawdown no more than 2 points deeper in any of them.
"""
import argparse

import numpy as np
import pandas as pd
import yaml

from run_more_trades import run_variant
from run_portfolio import replay, stats

CFG = yaml.safe_load(open("config.yaml"))
LIVE = dict(CFG["live"])
MAX_LEV = float(CFG["risk"]["max_leverage"])
RISK = 3.0
PERIODS = [("2021-23", "2021-01-01", "2024-01-01"), ("2024-25", "2024-01-01", "2026-01-01"),
           ("2026", "2026-01-01", "2027-01-01")]

#  label: [(variant name in run_more_trades, unit key, unit it replaces or None)]
CANDIDATES = {
    "gold 10/5 long (new sleeve)":        [("gold 10/5 long", "XAUUSD:fast10", None)],
    "gold 10/5 replaces 20/10":           [("gold 10/5 long", "XAUUSD:fast", "XAUUSD:fast")],
    "gold add55 @1.0R (new sleeve)":      [("gold add55 @1.0R", "XAUUSD:add55b", None)],
    "gold add20 @1.0R (new sleeve)":      [("gold add20 @1.0R", "XAUUSD:add20b", None)],
    "gold both @1.0R add-ons":            [("gold add55 @1.0R", "XAUUSD:add55b", None),
                                           ("gold add20 @1.0R", "XAUUSD:add20b", None)],
    "gold 55/20 intraday (replaces 55/20)": [("gold 55/20 intraday entry", "XAUUSD", "XAUUSD")],
    "jpy VBO re-entry (replaces VBO)":    [("jpy VBO re-entry 2/day", "USDJPY", "USDJPY")],
    "jpy VBO add-on @0.5R (new sleeve)":  [("jpy VBO add-on @0.5R", "USDJPY:add", None)],
    "jpy VBO add-on @1.0R (new sleeve)":  [("jpy VBO add-on @1.0R", "USDJPY:add", None)],
    "jpy VBO no trend (replaces VBO)":    [("jpy VBO no trend filter", "USDJPY", "USDJPY")],
    "jpy VBO no trend + re-entry (replaces VBO)": [("jpy VBO no trend + re-entry", "USDJPY", "USDJPY")],
    "jpy no trend + re-entry + gold 10/5 sleeve":
        [("jpy VBO no trend + re-entry", "USDJPY", "USDJPY"), ("gold 10/5 long", "XAUUSD:fast10", None)],
    "jpy VBO no trend + re-entry at 3% risk (replaces VBO)":
        [("jpy VBO no trend + re-entry", "USDJPY:3pct", "USDJPY")],
    "jpy VBO no trend at 3% risk (replaces VBO)": [("jpy VBO no trend filter", "USDJPY:3pct", "USDJPY")],
}


def _load(src):
    t = pd.read_csv(f"results/portfolio_trades_{src}.csv")
    for c in ("entry_time", "exit_time"):
        t[c] = pd.to_datetime(t[c], utc=True)
    return t


def _weights(trades):
    """Live risk: gold and USDJPY units trade 4%, the rest 3% (weights on RISK)."""
    return {u: (4.0 / 3.0 if u.startswith(("XAUUSD", "USDJPY")) and not u.endswith(":3pct") else 1.0)
            for u in trades.unit.unique()}


def _as_unit(t, key, market, inverse):
    """Trades from run_variant -> the columns replay() needs (1% risk, big account)."""
    t = t.copy()
    t["exit_time"] = pd.to_datetime(t["exit_time"], utc=True)
    se = 1_000_000.0
    ex = t.sort_values("exit_time")
    cum_pnl = ex.pnl.cumsum().to_numpy()
    n_closed = np.searchsorted(ex.exit_time.to_numpy(), t.entry_time.to_numpy(), side="right")
    eq_at = se + np.where(n_closed > 0, cum_pnl[np.maximum(n_closed - 1, 0)], 0.0)
    notional = t["units"] * (1.0 if inverse else t["entry_price"])
    t["lev_per_1pct"] = notional.to_numpy() / eq_at
    t["unit"], t["market"] = key, market
    return t[["unit", "market", "entry_time", "exit_time", "side", "r_multiple", "lev_per_1pct",
              "exit_reason", "tag"]]


def period_stats(trades, label, s, e):
    tr = trades[(trades.entry_time >= s) & (trades.entry_time < e)].sort_values("entry_time").reset_index(drop=True)
    eq, taken = replay(tr, RISK, LIVE, MAX_LEV, weights=_weights(tr))
    st = stats(eq)
    return dict(period=label, trades=int(taken.sum()), month=st.get("geo_month"), maxdd=st.get("maxdd"),
                final_x=st.get("final_x"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    hist, mt5 = _load("hist"), _load("mt5")
    base = pd.concat([hist[hist.entry_time < "2026-01-01"], mt5[mt5.entry_time >= "2026-01-01"]])
    base_rows = [period_stats(base, *p) for p in PERIODS]
    print("BASELINE (live units, live risk):")
    print(pd.DataFrame(base_rows).to_string(index=False))
    cache = {}
    out = []
    for label, parts in CANDIDATES.items():
        if a.only.lower() not in label.lower():
            continue
        t = base.copy()
        for variant, key, replaces in parts:
            if variant not in cache:
                _, th, tb = run_variant(variant)
                market = key.split(":")[0]
                inverse = market == "USDJPY"
                th = _as_unit(th, key, market, inverse) if len(th) else th
                tb = _as_unit(tb, key, market, inverse) if len(tb) else tb
                cache[variant] = pd.concat([x for x in (th[th.entry_time < "2026-01-01"] if len(th) else th,
                                                        tb[tb.entry_time >= "2026-01-01"] if len(tb) else tb)
                                            if len(x)])
            if replaces:
                t = t[t.unit != replaces]
            t = pd.concat([t, cache[variant]])
        rows = [period_stats(t, *p) for p in PERIODS]
        ok = all(r["month"] > b["month"] and r["maxdd"] >= b["maxdd"] - 2.0 for r, b in zip(rows, base_rows))
        line = {"candidate": label}
        for r, b in zip(rows, base_rows):
            line[f"{r['period']} month"] = f"{b['month']:.2f}->{r['month']:.2f}"
            line[f"{r['period']} DD"] = f"{b['maxdd']:.1f}->{r['maxdd']:.1f}"
            line[f"{r['period']} n"] = f"{b['trades']}->{r['trades']}"
        line["PASS"] = ok
        out.append(line)
        print(f"  {label:<58} " + "  ".join(f"{k}: {v}" for k, v in line.items() if k != "candidate"), flush=True)
    df = pd.DataFrame(out)
    df.to_csv("results/portfolio_add.csv", index=False)
    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 20)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
