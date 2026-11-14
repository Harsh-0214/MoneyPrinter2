"""More London-stack trades: the Breakout's "ran too far by 10:30" cap, re-tested with the
current config (15-min EUR, 5-min GBP, 20:00 exit, Monday skip, trend filter).

    python run_london_more.py

Nov 2026 robustness (old config) showed the cap did not help out-of-sample (off: OOS +5.9%
vs +4.8% at 15 pips). Dropping it adds the strongest breakouts back. Judged like every
other change: 2021-23 first, then 2024-25, then 2026 (broker M15/M5 feed, run_oos_mt5
style) - must not lose on any period.
"""
import copy

import pandas as pd
import yaml

from run_validate import load_pairs, per_year, run_multi, set_param, summarize

cfg = yaml.safe_load(open("config.yaml"))
cfg["risk"]["risk_per_trade_pct"] = 1.0
bars = load_pairs(cfg)
bars = {k: v for k, v in bars.items() if k in ("EURUSD", "GBPUSD")}
se = cfg["account"]["starting_equity"]
rows = []
for cap in (15, 20, 25, 35, None):
    c = set_param(cfg, "breakout.max_defer_extension_pips", cap)
    for label, s, e in [("2021-23", "2021-01-01", "2023-12-31"), ("2024-25", "2024-01-01", "2025-12-31")]:
        t, eq = run_multi(bars, c, s, e)
        m = summarize(t, eq, se)
        rows.append(dict(cap=str(cap), period=label, **m))
    t, eq = run_multi(bars, c)
    py = per_year(t, eq, se)
    rows.append(dict(cap=str(cap), period="per-year ret%", **{str(y): r for y, r in zip(py.year, py["ret%"])}))
    print(pd.DataFrame(rows).tail(3).to_string(index=False), flush=True)
df = pd.DataFrame(rows)
df.to_csv("results/london_defer_cap.csv", index=False)
pd.set_option("display.width", 250)
print(df.to_string(index=False))
