"""Does the high-impact news filter help? Portfolio backtest 2021-2025 with the
historical calendar at several blackout settings vs the current config.

    python run_news_test.py

Only risk.news_* settings change between rows; every strategy parameter is config.yaml.
"""
import copy
import time

import pandas as pd
import yaml

from run_validate import load_pairs, per_year, run_multi, summarize

CAL = "data/news/high_impact_2021_2025.csv"

VARIANTS = [
    ("baseline (no news filter)", {"news_filter": False}),
    ("+-15 min", {"news_filter": True, "news_blackout_minutes": 15}),
    ("+-30 min", {"news_filter": True, "news_blackout_minutes": 30}),
    ("+-60 min", {"news_filter": True, "news_blackout_minutes": 60}),
    ("+-120 min", {"news_filter": True, "news_blackout_minutes": 120}),
    ("+-30 min + skip NFP/FOMC days", {"news_filter": True, "news_blackout_minutes": 30,
                                       "news_day_block": ["payrolls", "fomc"]}),
    ("+-30 min + skip all event days", {"news_filter": True, "news_blackout_minutes": 30,
                                        "news_day_block": ["payrolls", "cpi", "fomc", "ecb", "boe"]}),
]


def main():
    cfg = yaml.safe_load(open("config.yaml"))
    t0 = time.time()
    bars = load_pairs(cfg)
    se = cfg["account"]["starting_equity"]
    rows, by_unit = [], []
    for name, over in VARIANTS:
        c = copy.deepcopy(cfg)
        c["risk"] = dict(c["risk"], news_calendar=CAL, news_day_block=[])
        c["risk"].update(over)
        t, eq = run_multi(bars, c)
        m = summarize(t, eq, se)
        py = per_year(t, eq, se).set_index("year")["ret%"]
        worst = t.r_multiple.nsmallest(10).mean() if len(t) else 0
        rows.append({"variant": name, **{str(y): py.get(y) for y in py.index},
                     "total%": m["ret%"], "maxDD%": m["dd%"], "pf": m["pf"], "trades": m["trades"],
                     "worst10_avgR": round(worst, 2)})
        if len(t):
            g = t.groupby("symbol").agg(n=("pnl", "size"), pnl=("pnl", "sum"))
            by_unit.append(g.rename(columns={"n": f"{name[:14]} n", "pnl": f"{name[:14]} pnl"}))
        print(f"  {name:<34} total {m['ret%']:+.2f}%  dd {m['dd%']:.2f}%  n {m['trades']}"
              f"  ({time.time()-t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\n=== NEWS FILTER, PORTFOLIO 2021-2025 (per-year return %) ===")
    print(df.to_string(index=False))
    if by_unit:
        print("\n=== BY UNIT (trades, PnL USD) ===")
        print(pd.concat(by_unit, axis=1).round(0).to_string())
    df.to_csv("results/news_filter_test.csv", index=False)


if __name__ == "__main__":
    main()
