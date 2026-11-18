"""IBS on more US indices: S&P 500 alone vs S&P 500 + NASDAQ (+ Dow), whole account (Nov 18 2026).

    python run_ibs_indices.py [--refresh] [--mc 500]

Same rules as the live SPX500 unit (fxbot/strategies/ibs.py, stop 3x the average day range) on
NAS100 and US30 (broker H1, complete from mid-2018; spreads charged 5.0 / 6.0 points vs medians
3.0 / 3.5; 6%/yr financing; 10% margin). Whole-account replay with the live units + SPX500 + the
extra indices at different risk splits; fixed calendar months; optional reshuffles (2021-25).
"""
import argparse
import copy
import os

import pandas as pd
import yaml

import run_portfolio as rp
from run_ibs_portfolio import P, fixed_stats

SPREAD = {"NAS100": 50.0, "US30": 60.0}


def extra_cfg(base):
    cfg = copy.deepcopy(base)
    spx = [p for p in cfg["pairs"] if p["symbol"] == "SPX500"][0]
    cfg["pairs"] = []
    for s, sp in SPREAD.items():
        p = copy.deepcopy(spx)
        p.update(symbol=s, broker_symbol=s, spread_pips=sp)
        p["data"] = dict(p["data"], path=f"data/mt5/{s}_H1.csv")
        cfg["pairs"].append(p)
    return cfg


def load(base, refresh):
    out = {}
    for src in ("hist", "mt5"):
        path = f"results/ibs_indices_{src}.csv"
        if os.path.exists(path) and not refresh:
            x = pd.read_csv(path)
            for c in ("entry_time", "exit_time"):
                x[c] = pd.to_datetime(x[c], utc=True)
        else:
            x = rp._units_trades(extra_cfg(base), src)
            x.to_csv(path, index=False)
        out[src] = pd.concat([rp.load_trades(base, src), x]).sort_values("entry_time").reset_index(drop=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--mc", type=int, default=0)
    a = ap.parse_args()
    base = yaml.safe_load(open("config.yaml"))
    live, ml, risk = dict(base["live"]), float(base["risk"]["max_leverage"]), float(base["risk"]["risk_per_trade_pct"])
    data = load(base, a.refresh)
    h = data["hist"]
    for u in ("SPX500", "NAS100", "US30"):
        g = h[h.unit == u]
        y = g.entry_time.dt.year
        print(f"{u}: {len(g)} trades, avg R {g.r_multiple.mean():+.3f}, R by year {g.groupby(y).r_multiple.sum().round(1).to_dict()}")
    j = h[h.unit.isin(["SPX500", "NAS100", "US30"])]
    mo = j.pivot_table(index=j.exit_time.dt.to_period("M"), columns="unit", values="r_multiple", aggfunc="sum").fillna(0)
    print("monthly R correlation:\n", mo.corr().round(2).to_string())
    variants = {
        "today: SPX500 2%":            {"SPX500": 2, "NAS100": 0, "US30": 0},
        "SPX500 1% + NAS100 1%":       {"SPX500": 1, "NAS100": 1, "US30": 0},
        "SPX500 2% + NAS100 2%":       {"SPX500": 2, "NAS100": 2, "US30": 0},
        "all three at 0.67%":          {"SPX500": 0.67, "NAS100": 0.67, "US30": 0.67},
        "all three at 1%":             {"SPX500": 1, "NAS100": 1, "US30": 1},
        "all three at 2%":             {"SPX500": 2, "NAS100": 2, "US30": 2},
    }
    rows = []
    for name, rk in variants.items():
        w = {u: r / risk for u, r in rk.items()}
        drop = [u for u, r in rk.items() if r == 0]
        row = {"variant": name}
        for p, (src, x, y) in P.items():
            t = data[src]
            t = t[(t.entry_time >= x) & (t.entry_time < y) & ~t.unit.isin(drop)].reset_index(drop=True)
            eq, _ = rp.replay(t, risk, live, ml, weights=w)
            s = fixed_stats(eq, x, y)
            row[f"{p} month%"], row[f"{p} DD%"] = s["geo_month"], s["maxdd"]
        if a.mc:
            t = h[(h.entry_time >= "2021-01-01") & (h.entry_time < "2026-01-01") & ~h.unit.isin(drop)].copy()
            for u, r in rk.items():
                m = t.unit == u
                t.loc[m, "r_multiple"] *= r / risk
                t.loc[m, "lev_per_1pct"] *= r / risk
            m = rp.monte_carlo(t.reset_index(drop=True), risk, live, ml, a.mc)
            row.update({"MC typical": m["geo_med"], "MC unlucky": m["geo_p10"], "MC 1-in-100 DD": m["dd_p99"]})
        rows.append(row)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).set_index("variant").to_string())


if __name__ == "__main__":
    main()
