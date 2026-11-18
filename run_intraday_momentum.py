"""Intraday momentum on the NASDAQ 100: the first half hour predicts the last half hour.

    python run_intraday_momentum.py

Published effect (Gao, Han, Li & Zhou 2018, SPY 1993-2013): the 09:30-10:00 New York return
predicts the 15:30-16:00 return. Never tested here. Rules: if the first half hour (optionally plus
the overnight move from yesterday's 16:00) is up, BUY at 15:30 (or 15:00), sell 16:00; down: SELL.
Optional threshold: only when the first-half-hour move is bigger than its 20-day median.
Data: Dukascopy NAS100 M1, 2021 - Nov 2026 (closed hours removed). Cost per trade: 3.0-point
spread + 0.5 slippage (the cost used for NAS100 in every earlier test).
Pass (fixed before the run): PF >= 1.15 over 2021-25, >= 4 of 5 years up, 2026 not negative.
"""
import numpy as np
import pandas as pd

import run_fvg123 as F

COST = 3.5


def main():
    b = F._load("NAS100")
    ny = b.copy()
    ny.index = ny.index.tz_convert("America/New_York")
    c = ny.close
    day = c.index.normalize()
    def at(hm):
        s = c[c.index.strftime("%H:%M") == hm]
        s.index = s.index.normalize()
        return s[~s.index.duplicated()]
    p = pd.DataFrame({"o": at("09:30"), "f": at("10:00"), "m": at("15:00"), "l": at("15:30"), "x": at("15:59")}).dropna()
    p["prev"] = p.x.shift(1)
    p["first"] = p.f - p.o
    p["first_on"] = p.f - p.prev
    p["med"] = p["first"].abs().rolling(20).median().shift(1)
    rows = []
    for sig_name, sig in (("first 30 min", "first"), ("overnight + first 30 min", "first_on")):
        for entry in ("l", "m"):
            for thr in (False, True):
                q = p.dropna(subset=[sig, "med"])
                if thr:
                    q = q[q["first"].abs() > q.med]
                side = np.sign(q[sig])
                pts = (q.x - q[entry]) * side - COST
                for name, m in (("2021-25", (q.index.year <= 2025)), ("2026", q.index.year == 2026)):
                    z = pts[m]
                    if not len(z):
                        continue
                    row = dict(signal=sig_name, entry="15:30" if entry == "l" else "15:00", big_moves_only=thr,
                               period=name, trades=len(z), avg_pts=round(z.mean(), 2),
                               gross_avg=round(z.mean() + COST, 2), win=round((z > 0).mean() * 100),
                               pf=round(z[z > 0].sum() / -z[z <= 0].sum(), 2), total_pts=round(z.sum()))
                    if name == "2021-25":
                        yr = z.groupby(z.index.year).sum()
                        row["yrs_up"] = int((yr > 0).sum()); row["by_year"] = " ".join(f"{v:+.0f}" for v in yr)
                    rows.append(row)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))
    df.to_csv("results/intraday_momentum.csv", index=False)


if __name__ == "__main__":
    main()
