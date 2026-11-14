"""Would a "stop after N losses in a row" rule have helped? Every live trade 2021-2026.

    python run_loss_streak.py

Rules tested on the live units' trades (results/portfolio_trades_{hist,mt5}.csv):
  A  per strategy: after N losses in a row, skip its trades until one it skipped would have won
     ("wait for the strategy to prove itself again")
  B  per strategy: after N losses in a row, skip its next K trades
  C  whole account: after N losing trades in a row (any market), no new trades for D days
Judged two ways: total R of what is skipped (positive = the rule threw away profit), and the full
portfolio replay (real margin, risk brake, gold/USDJPY at 4%) per period.
"""
import numpy as np
import pandas as pd

import run_portfolio_add as A


def load():
    h, m = A._load("hist"), A._load("mt5")
    t = pd.concat([h[h.entry_time < "2026-01-01"], m[m.entry_time >= "2026-01-01"]])
    return t.sort_values("entry_time").reset_index(drop=True)


def rule_unit_shadow(t, n):
    keep = np.ones(len(t), bool)
    for _, g in t.groupby("unit"):
        streak, paused = 0, False
        for i in g.index:                      # trades of one unit, in order
            r = t.at[i, "r_multiple"]
            if paused:
                keep[i] = False
                if r > 0:
                    paused, streak = False, 0  # a skipped trade would have won: back on
                continue
            streak = streak + 1 if r <= 0 else 0
            if streak >= n:
                paused = True
    return keep


def rule_unit_skip(t, n, k):
    keep = np.ones(len(t), bool)
    for _, g in t.groupby("unit"):
        streak, skip = 0, 0
        for i in g.index:
            if skip:
                keep[i] = False
                skip -= 1
                continue
            streak = streak + 1 if t.at[i, "r_multiple"] <= 0 else 0
            if streak >= n:
                skip, streak = k, 0
    return keep


def rule_account(t, n, days):
    """Losses counted in the order trades CLOSE (that's when the account learns of them)."""
    keep = np.ones(len(t), bool)
    closes = t.sort_values("exit_time")
    streak, pause_until = 0, pd.Timestamp("1900-01-01", tz="UTC")
    events = sorted([(r.entry_time, 1, i) for i, r in t.iterrows()] +
                    [(r.exit_time, 0, i) for i, r in t.iterrows()])
    taken = set()
    for ts, kind, i in events:
        if kind == 1:
            if ts < pause_until:
                keep[i] = False
            else:
                taken.add(i)
        elif i in taken:
            streak = streak + 1 if t.at[i, "r_multiple"] <= 0 else 0
            if streak >= n:
                pause_until, streak = ts + pd.Timedelta(days=days), 0
    return keep


def main():
    t = load()
    t["period"] = np.where(t.entry_time < "2024-01-01", "2021-23", "2024-26")
    base = [A.period_stats(t, *p) for p in A.PERIODS]
    rules = {"no rule (live)": np.ones(len(t), bool)}
    for n in (3, 4, 5):
        rules[f"A: {n} losses, wait for a would-be win"] = rule_unit_shadow(t, n)
        rules[f"B: {n} losses, skip next 2"] = rule_unit_skip(t, n, 2)
    for n in (3, 4):
        for d in (1, 3, 7):
            rules[f"C: account {n} losses, pause {d}d"] = rule_account(t, n, d)
    rows = []
    for name, keep in rules.items():
        sk = t[~keep]
        st = [A.period_stats(t[keep], *p) for p in A.PERIODS]
        row = dict(rule=name, skipped=int((~keep).sum()),
                   skipped_R_21_23=round(sk[sk.period == "2021-23"].r_multiple.sum(), 1),
                   skipped_R_24_26=round(sk[sk.period == "2024-26"].r_multiple.sum(), 1))
        for s, b in zip(st, base):
            row[f"{s['period']} month"] = s["month"]
            row[f"{s['period']} DD"] = s["maxdd"]
        rows.append(row)
        print(row, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("results/loss_streak.csv", index=False)
    # what happens right after a streak, per unit
    t["streak_before"] = t.groupby("unit").r_multiple.transform(
        lambda s: (s <= 0).astype(int).groupby((s > 0).cumsum()).cumsum().shift(1).fillna(0))
    t["after"] = pd.cut(t.streak_before, [-1, 0, 1, 2, 99], labels=["after a win", "after 1 loss",
                                                                     "after 2 losses", "after 3+ losses"])
    print("\nNext trade's result, by the losing streak before it:")
    print(t.groupby(["after", "period"], observed=True).r_multiple.agg(["size", "mean", "sum"])
          .unstack("period").round(2).to_string())
    pd.set_option("display.width", 250)
    print("\n" + df.to_string(index=False))


if __name__ == "__main__":
    main()
