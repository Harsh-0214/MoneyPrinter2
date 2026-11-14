"""Stop distance: does the "room to survive" cost more than it saves? Every live strategy.

    python run_stop_size.py

Each trade always risks the same % of the account (size = risk / stop distance), so a wider stop
means a smaller position, not a bigger loss. What changes is how often noise stops a trade out and
how many R a winner is worth. Scored in R at 1% risk: 2021-23, 2024-25 (histdata), 2026 (broker).
  London Breakout: stop at the far side of the range (live), at the range middle, or 1.5 / 3 x ATR
  USDJPY breakout: 0.3 / 0.4 / 0.5 (live) / 0.6 / 0.7 x yesterday's range
  Gold trend 55 and 20: 1.5 / 2 (live) / 2.5 / 3 x daily ATR (initial and trailing)
"""
import copy
from multiprocessing import Pool

import pandas as pd

import run_london_optimize as LO
import run_more_trades as MT

LONDON = [("range (live)", dict(stop_mode="range")), ("range middle", dict(stop_mode="mid")),
          ("1.5 x ATR", dict(stop_mode="atr", atr_stop_mult=1.5)), ("3 x ATR", dict(stop_mode="atr", atr_stop_mult=3.0))]
for v in (0.3, 0.4, 0.6, 0.7):
    MT.VARIANTS[f"jpy VBO stop {v}"] = ("USDJPY", "15min", [MT._v(MT.VBO, stop_range=v)], 2, "M15")
MT.VARIANTS["jpy VBO stop 0.5 (live)"] = ("USDJPY", "15min", [MT.VBO], 2, "M15")
for v in (1.5, 2.5, 3.0):
    MT.VARIANTS[f"gold 55/20 stop {v} ATR"] = ("XAUUSD", "1h", [MT._v(MT.T55, stop_atr=v)], 1, "H1")
    MT.VARIANTS[f"gold 20/10 stop {v} ATR"] = ("XAUUSD", "1h", [MT._v(MT.T20, stop_atr=v)], 1, "H1")
OTHER = [n for n in MT.VARIANTS if "stop" in n] + ["gold 55/20 (live)", "gold 20/10 (live)"]


def _london(job):
    name, pb = job
    r = LO._run((dict(LO.LIVE_B, **pb), dict(LO.LIVE_S)))
    return dict(strategy=f"London {name}", R21_23=round(r["R2021"] + r["R2022"] + r["R2023"], 1),
                R24_25=round(r["R2024"] + r["R2025"], 1), R26=round(r["R2026"], 1),
                trades=sum(r[f"n{y}"] for y in range(2021, 2026)))


def _other(name):
    row, _, _ = MT.run_variant(name)
    return dict(strategy=name, R21_23=row["R21_23"], R24_25=row["R24_25"], R26=row.get("R26"), trades=row["n"])


def main():
    with Pool(6, initializer=LO._init) as pool:
        rows = pool.map(_london, LONDON)
    with Pool(6) as pool:
        rows += pool.map(_other, OTHER)
    df = pd.DataFrame(rows)
    df["total"] = df[["R21_23", "R24_25", "R26"]].sum(axis=1).round(1)
    df.to_csv("results/stop_size.csv", index=False)
    pd.set_option("display.width", 200)
    print(df.sort_values("strategy").to_string(index=False))


if __name__ == "__main__":
    main()
