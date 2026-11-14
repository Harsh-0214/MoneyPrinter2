"""What a given starting balance becomes at different risk levels, every live trade 2021 - Nov 2026.

    python run_risk_levels.py --start 3000

One account, trades in time order, compounding, live risk brake, real margin, leverage cap,
gold/USDJPY at 4/3 of the base risk (as live: 3% -> 4%). Plus 1,000 reshuffles of the trade
order (same trades, different luck) for the drawdown range. Min-lot rounding is ignored: at
$3,000 the smallest trades are about 20,000 FX units / 1 oz gold, far above the broker minimums.
"""
import argparse

import numpy as np
import pandas as pd

import run_portfolio_add as A
from run_portfolio import replay


def run(t, risk, live, start):
    eq, taken, money = replay(t, risk, live, A.MAX_LEV, weights=A._weights(t), start_eq=start, detail=True)
    full = pd.concat([pd.Series([start], index=[t.entry_time.min() - pd.Timedelta(seconds=1)]), eq])
    m = full.resample("ME").last().ffill()
    mret = (m / m.shift(1).fillna(start) - 1) * 100
    peak = full.cummax()
    dd = full / peak - 1
    i = dd.idxmin()
    yearly = full.resample("YE").last()
    return dict(final=full.iloc[-1], months=len(mret), avg_month=((full.iloc[-1] / start) ** (1 / len(mret)) - 1) * 100,
                losing_months=int((mret < 0).sum()), worst_month=mret.min(), maxdd=dd.min() * 100,
                dd_from=peak[i], dd_to=full[i], biggest_loss=money[taken].min() if taken.any() else 0.0,
                yearly=yearly, trades=int(taken.sum()))


def mc(t, risk, live, start, n=1000, seed=7):
    rng = np.random.default_rng(seed)
    dds, finals = [], []
    for _ in range(n):
        s = t.copy()
        for _, idx in s.groupby("unit").groups.items():
            idx = np.asarray(idx)
            s.loc[idx, "r_multiple"] = rng.permutation(s.loc[idx, "r_multiple"].to_numpy())
        eq, _ = replay(s, risk, live, A.MAX_LEV, weights=A._weights(s), start_eq=start)
        full = np.concatenate([[start], eq.to_numpy()])
        dds.append((full / np.maximum.accumulate(full) - 1).min() * 100)
        finals.append(full[-1])
    dds, finals = np.array(dds), np.array(finals)
    return dict(dd_typical=np.median(dds), dd_1in20=np.percentile(dds, 5), dd_1in100=np.percentile(dds, 1),
                final_bad=np.percentile(finals, 10), final_typical=np.median(finals),
                share_lose_money=(finals < start).mean() * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=float, default=3000)
    ap.add_argument("--mc", type=int, default=1000)
    ap.add_argument("--levels", default="", help="e.g. 6,8,10,12,15 (with brake); default = the standard set")
    a = ap.parse_args()
    h, m = A._load("hist"), A._load("mt5")
    t = pd.concat([h[h.entry_time < "2026-01-01"], m[m.entry_time >= "2026-01-01"]]).sort_values("entry_time")
    t = t.reset_index(drop=True)
    rows, yearly = [], {}
    levels = ([(f"{x}%", float(x), True) for x in a.levels.split(",")] if a.levels else
              [("1%", 1, True), ("2%", 2, True), ("3% (live)", 3, True), ("4%", 4, True),
               ("5%", 5, True), ("6%", 6, True), ("3%, no brake", 3, False), ("6%, no brake", 6, False)])
    for label, risk, brake in levels:
        live = dict(A.LIVE)
        if not brake:
            live["risk_brake"] = []
        r = run(t, risk, live, a.start)
        r.update(mc(t, risk, live, a.start, a.mc))
        yearly[label] = r.pop("yearly")
        rows.append(dict(risk=label, **r))
        print(label, {k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()}, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("results/risk_levels.csv", index=False)
    y = pd.DataFrame({k: v for k, v in yearly.items()})
    y.index = y.index.year
    y.to_csv("results/risk_levels_yearly.csv")
    pd.set_option("display.width", 250)
    print(df.round(1).to_string(index=False))
    print("\nAccount at each year end:")
    print(y.round(0).to_string())


if __name__ == "__main__":
    main()
