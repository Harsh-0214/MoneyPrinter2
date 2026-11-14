"""Is the risk brake worth it? Live brake vs none vs other shapes, $3,000, live risk mix.

    python run_brake_variants.py --start 3000

All runs: London/pullback 3%, gold + USDJPY 4%, 12% total-risk cap, 70% margin, emergency stop at
28% below the peak. Only the brake tiers change ([drawdown %, max risk %], deepest reached wins).
Actual 2021 - Nov 2026 order + 1,000 reshuffles; also the share of reshuffles that hit the 28% stop.
Caution: every variant is judged on the same trades, so small differences are noise.
"""
import argparse

import numpy as np
import pandas as pd

import run_portfolio_add as A
import run_risk_levels as RL
from run_portfolio import replay

VARIANTS = {
    "live: 8%->2, 15%->1, 20%->0.5": [[8, 2.0], [15, 1.0], [20, 0.5]],
    "no brake": [],
    "earlier: 5%->2, 10%->1, 15%->0.5": [[5, 2.0], [10, 1.0], [15, 0.5]],
    "later: 12%->2, 20%->1, 25%->0.5": [[12, 2.0], [20, 1.0], [25, 0.5]],
    "gentle: 10%->2.5, 20%->1.5": [[10, 2.5], [20, 1.5]],
    "one step: 15%->1.5": [[15, 1.5]],
}
# round 2: around the later / gentler shapes (first cut at 10-15%, cuts of 2 / 1 / 0.5 or 2.5 / 1.5 / 1)
GRID2 = {}
for first in (10, 12, 15):
    for cuts in ((2.0, 1.0, 0.5), (2.5, 1.5, 1.0)):
        GRID2[f"{first}%->{cuts[0]:g}, {first + 8}%->{cuts[1]:g}, {first + 12}%->{cuts[2]:g}"] =             [[first, cuts[0]], [first + 8, cuts[1]], [first + 12, cuts[2]]]


def hit_stop_share(t, live, start, n=1000, seed=7):
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(n):
        s = t.copy()
        for _, idx in s.groupby("unit").groups.items():
            idx = np.asarray(idx)
            s.loc[idx, "r_multiple"] = rng.permutation(s.loc[idx, "r_multiple"].to_numpy())
        eq, _ = replay(s, 3.0, live, A.MAX_LEV, weights=A._weights(s), start_eq=start)
        full = np.concatenate([[start], eq.to_numpy()])
        hits += (full / np.maximum.accumulate(full) - 1).min() <= -0.28
    return hits / n * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=float, default=3000)
    ap.add_argument("--mc", type=int, default=1000)
    ap.add_argument("--round2", action="store_true")
    a = ap.parse_args()
    h, m = A._load("hist"), A._load("mt5")
    t = pd.concat([h[h.entry_time < "2026-01-01"], m[m.entry_time >= "2026-01-01"]]).sort_values("entry_time")
    t = t.reset_index(drop=True)
    rows = []
    for name, tiers in (dict(list(VARIANTS.items())[:1], **GRID2) if a.round2 else VARIANTS).items():
        live = dict(A.LIVE, risk_brake=tiers)
        r = RL.run(t, 3.0, live, a.start)
        r.update(RL.mc(t, 3.0, live, a.start, a.mc))
        r.pop("yearly")
        r["hit_28pct_stop"] = hit_stop_share(t, live, a.start, a.mc)
        rows.append(dict(brake=name, **r))
        print(name, round(r["final"]), round(r["final_typical"]), round(r["final_bad"]), round(r["dd_1in100"], 1),
              round(r["hit_28pct_stop"], 1), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("results/brake_variants_round2.csv" if a.round2 else "results/brake_variants.csv", index=False)
    pd.set_option("display.width", 250)
    print(df[["brake", "final", "final_typical", "final_bad", "maxdd", "dd_typical", "dd_1in100", "hit_28pct_stop",
              "share_lose_money"]].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
