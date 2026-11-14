"""Trade smaller during a strategy's own bad streak (instead of stopping it)?

    python run_streak_sizing.py

On top of the live account brake. Rules (per strategy, decided from its own closed trades only):
  S-N   after N losses in a row: next trades at x size until one wins
  D-X   while the strategy is X R or more below its own best: trades at x size
Full portfolio replay (real margin, account risk brake, gold/USDJPY at 4%), all three periods.
"""
import numpy as np
import pandas as pd

import run_portfolio_add as A
from run_loss_streak import load

_base_weights = A._weights


def _weights_with_size(tr):
    w = _base_weights(tr)
    for u in tr.unit.unique():
        if "|x" in u:
            base, mult = u.split("|x")
            w[u] = _base_weights(pd.DataFrame({"unit": [base]}))[base] * float(mult)
    return w


A._weights = _weights_with_size


def mark(t, flags, mult):
    t = t.copy()
    t.loc[flags, "unit"] = t.loc[flags, "unit"] + f"|x{mult}"
    return t


def streak_flags(t, n):
    """True where the strategy had >= n losses in a row before this trade (known at entry:
    only trades that CLOSED before this entry count)."""
    f = np.zeros(len(t), bool)
    for _, g in t.groupby(t.unit):
        closed = []                                    # (exit_time, R) of earlier trades
        for i in g.index:
            et = t.at[i, "entry_time"]
            done = sorted((x, r) for x, r in closed if x <= et)
            k = 0
            for _, r in reversed(done):
                if r <= 0:
                    k += 1
                else:
                    break
            f[i] = k >= n
            closed.append((t.at[i, "exit_time"], t.at[i, "r_multiple"]))
    return f


def dd_flags(t, x):
    f = np.zeros(len(t), bool)
    for _, g in t.groupby(t.unit):
        closed = []
        for i in g.index:
            et = t.at[i, "entry_time"]
            rs = [r for xt, r in sorted(closed) if xt <= et]
            if rs:
                c = np.cumsum(rs)
                f[i] = (max(c.max(), 0.0) - c[-1]) >= x
            closed.append((t.at[i, "exit_time"], t.at[i, "r_multiple"]))
    return f


def main():
    t = load()
    rows = []
    variants = {"live (account brake only)": (np.zeros(len(t), bool), 1.0)}
    for n in (2, 3, 4):
        for m in (0.5, 0.25):
            variants[f"S-{n}: {m:g} size after {n} losses until a win"] = (streak_flags(t, n), m)
    for x in (3, 5, 8):
        variants[f"D-{x}: half size while {x}R below its own best"] = (dd_flags(t, x), 0.5)
    for name, (flags, m) in variants.items():
        tt = mark(t, flags, m)
        st = [A.period_stats(tt, *p) for p in A.PERIODS]
        row = dict(rule=name, trades_resized=int(flags.sum()),
                   R_of_resized=round(t.r_multiple[flags].sum(), 1))
        for s in st:
            row[f"{s['period']} month"] = s["month"]
            row[f"{s['period']} DD"] = s["maxdd"]
        rows.append(row)
        print(row, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("results/streak_sizing.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
