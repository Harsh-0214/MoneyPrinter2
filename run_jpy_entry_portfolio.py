"""Whole-account test of earlier USDJPY breakout entries (k 0.5-0.8 vs live 0.9). Nov 20 2026.

    python run_jpy_entry_portfolio.py [--mc 500]

The live portfolio (all units, 4% risk, brake, 12% risk cap, 70% margin cap, SPX500 at 2%) with
only the USDJPY unit's k changed. Pass (the portfolio rule): higher avg month in all of 2021-23 /
2024-25 / 2026 and max DD no more than 2 points deeper in any.
"""
import argparse
import copy

import pandas as pd
import yaml

import run_portfolio as rp
from run_ibs_portfolio import P, fixed_stats


def jpy_trades(base, k, src):
    cfg = copy.deepcopy(base)
    p = [x for x in cfg["pairs"] if x["symbol"] == "USDJPY"][0]
    p["strategies"]["morning"][0]["k"] = k
    cfg["pairs"] = [p]
    return rp._units_trades(cfg, src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mc", type=int, default=0)
    a = ap.parse_args()
    base = yaml.safe_load(open("config.yaml"))
    live, ml, risk = dict(base["live"]), float(base["risk"]["max_leverage"]), float(base["risk"]["risk_per_trade_pct"])
    data = {s: rp.load_trades(base, s) for s in ("hist", "mt5")}
    w = {"SPX500": 2.0 / risk}
    rows = []
    for k in (0.9, 0.8, 0.7, 0.6, 0.5):
        row = {"k": k}
        alt = {s: (None if k == 0.9 else jpy_trades(base, k, s)) for s in ("hist", "mt5")}
        for p, (src, x, y) in P.items():
            t = data[src]
            if alt[src] is not None:
                t = pd.concat([t[t.unit != "USDJPY"], alt[src]])
            t = t[(t.entry_time >= x) & (t.entry_time < y)].sort_values("entry_time").reset_index(drop=True)
            eq, _ = rp.replay(t, risk, live, ml, weights=w)
            s = fixed_stats(eq, x, y)
            row[f"{p} month%"], row[f"{p} DD%"] = s["geo_month"], s["maxdd"]
            row[f"{p} jpy trades"] = int((t.unit == "USDJPY").sum())
        if a.mc:
            t = data["hist"]
            if alt["hist"] is not None:
                t = pd.concat([t[t.unit != "USDJPY"], alt["hist"]])
            t = t[(t.entry_time >= "2021-01-01") & (t.entry_time < "2026-01-01")].copy()
            m = t.unit == "SPX500"
            t.loc[m, "r_multiple"] *= w["SPX500"]
            t.loc[m, "lev_per_1pct"] *= w["SPX500"]
            mc = rp.monte_carlo(t.sort_values("entry_time").reset_index(drop=True), risk, live, ml, a.mc)
            row.update({"MC typical": mc["geo_med"], "MC unlucky": mc["geo_p10"], "MC 1-in-100 DD": mc["dd_p99"]})
        rows.append(row)
        print(row, flush=True)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).set_index("k").T.to_string())


if __name__ == "__main__":
    main()
