"""Re-test the shelved near-misses against TODAY's account (Nov 18 2026).

    python run_candidates.py [--refresh] [--mc 500]

Baseline = the live units + SPX500 IBS at 2% (all as configured now: 4% risk, USDJPY both ways,
risk brake, 12% risk cap, 70% margin cap). Candidates, each added on its own and all together:
  * gold 10/5 trend sleeve (buy a 10-day high, sell a 5-day low; 2x ATR stop) - Nov 13: +0.4-0.5
    points a month 2021-25 but 2026 slightly lower ("an option");
  * China A50 trend 55/20 long (the gold rules) - Nov 13: PF 1.50, 6/7 years, ~4 trades a year;
  * UK oil trend 55/20 long - Nov 13: PF 1.23, 0.07R a trade.
Gold 10/5 uses the same data as the live gold units (histdata 2021-25, broker 2026). A50 / UK oil
use the broker's H1 history (complete from mid-2018): spread floor = 90-day median, slippage 1/4
of it, financing -6.5% long / -1.5% short a year, margin 15% / 14%, 0.1-lot sizing.
Pass (the portfolio rule): higher avg month in all of 2021-23 / 2024-25 / 2026, max DD no more than
2 points deeper in any.
"""
import argparse
import copy
import os

import pandas as pd
import yaml

import run_portfolio as rp
from run_ibs_portfolio import P, fixed_stats

EXTRA_MARGIN = {"CHINAA50": 0.15, "UKOil": 0.14}


def candidate_cfg(base, which):
    cfg = copy.deepcopy(base)
    gold = [p for p in cfg["pairs"] if p["symbol"] == "XAUUSD"][0]
    if which == "gold10":
        p = copy.deepcopy(gold)
        p.pop("sleeves", None)
        spec = copy.deepcopy(gold["sleeves"][0]["strategies"]["morning"][0])     # the 20/10 sleeve
        spec.update(entry_days=10, exit_days=5)
        p["strategies"] = {"morning": [spec], "afternoon": []}
        cfg["pairs"] = [p]
        return cfg
    sym, path, floor = {"a50": ("CHINAA50", "data/mt5/CHINAA50_H1.csv", 10.0),
                        "ukoil": ("UKOil", "data/mt5/UKOil_H1.csv", 5.0)}[which]
    p = copy.deepcopy(gold)
    p.pop("sleeves", None)
    p.update(symbol=sym, broker_symbol=sym, spread_pips=floor)
    p["instrument"] = {"pip": 1.0, "min_units": 0.1}
    p["data"] = {"path": path, "source_tz": "UTC", "timeframe": "1h"}
    p["costs"] = {"swap_long_per_lot": 0.0, "swap_short_per_lot": 0.0, "swap_long_pct": -6.5,
                  "swap_short_pct": -1.5, "slippage_pips": 0.25 * floor, "rollover_spread_pips": 0.0}
    p["risk"] = dict(p.get("risk", {}), news_filter=False)
    cfg["pairs"] = [p]
    return cfg


def candidate_trades(base, which, refresh):
    path = f"results/candidate_{which}.csv"
    if os.path.exists(path) and not refresh:
        t = pd.read_csv(path)
        for c in ("entry_time", "exit_time"):
            t[c] = pd.to_datetime(t[c], utc=True)
        return t
    cfg = candidate_cfg(base, which)
    if which == "gold10":           # same sources as the live gold units
        h = rp._units_trades(cfg, "hist")
        m = rp._units_trades(cfg, "mt5")
        t = pd.concat([h[h.entry_time < "2026-01-01"].assign(src="hist"), m[m.entry_time >= "2026-01-01"].assign(src="mt5")])
        t["unit"] = "XAUUSD:fast10"
    else:                           # the broker H1 file covers every period
        t = rp._units_trades(cfg, "hist").assign(src="both")
    t = t.sort_values("entry_time").reset_index(drop=True)
    t.to_csv(path, index=False)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--mc", type=int, default=0)
    a = ap.parse_args()
    base = yaml.safe_load(open("config.yaml"))
    live, ml, risk = dict(base["live"]), float(base["risk"]["max_leverage"]), float(base["risk"]["risk_per_trade_pct"])
    rp.MARGIN_RATE.update(EXTRA_MARGIN)
    data = {s: rp.load_trades(base, s) for s in ("hist", "mt5")}
    cands = {w: candidate_trades(base, w, a.refresh) for w in ("gold10", "a50", "ukoil")}
    for w, t in cands.items():
        x = t[(t.entry_time >= "2021-01-01")]
        print(f"{w}: {len(x)} trades 2021-26, avg R {x.r_multiple.mean():+.3f}, "
              f"R by year {x.groupby(x.entry_time.dt.year).r_multiple.sum().round(1).to_dict()}")
    spx_w = 2.0 / risk
    variants = {"baseline (live + SPX500 2%)": [], "+ gold 10/5 sleeve": ["gold10"], "+ China A50 trend": ["a50"],
                "+ UK oil trend": ["ukoil"], "+ all three": ["gold10", "a50", "ukoil"]}
    rows = []
    for name, add in variants.items():
        row = {"variant": name}
        for p, (src, x, y) in P.items():
            t = data[src]
            parts = [t] + [cands[w][(cands[w].src == "both") | (cands[w].src == src)] for w in add]
            t = pd.concat(parts)
            t = t[(t.entry_time >= x) & (t.entry_time < y)].sort_values("entry_time").reset_index(drop=True)
            eq, _ = rp.replay(t, risk, live, ml, weights={"SPX500": spx_w})
            s = fixed_stats(eq, x, y)
            row[f"{p} month%"], row[f"{p} DD%"] = s["geo_month"], s["maxdd"]
        if a.mc:
            t = pd.concat([data["hist"]] + [cands[w][cands[w].src != "mt5"] for w in add])
            t = t[(t.entry_time >= "2021-01-01") & (t.entry_time < "2026-01-01")].copy()
            m = t.unit == "SPX500"
            t.loc[m, "r_multiple"] *= spx_w
            t.loc[m, "lev_per_1pct"] *= spx_w
            mc = rp.monte_carlo(t.sort_values("entry_time").reset_index(drop=True), risk, live, ml, a.mc)
            row.update({"MC typical": mc["geo_med"], "MC unlucky": mc["geo_p10"], "MC 1-in-100 DD": mc["dd_p99"]})
        rows.append(row)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).set_index("variant").to_string())


if __name__ == "__main__":
    main()
