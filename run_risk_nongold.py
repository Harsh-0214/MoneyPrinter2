"""Raise risk on the non-gold strategies only; gold stays at its live 4%.

    python run_risk_nongold.py --start 3000

Non-gold = EURUSD London, GBPUSD London, GBP pullback, USDJPY breakout (live: 3% / 3% / 3% / 4%).
Each level sets all four to that risk; the four gold units stay at 4%. Brake on, margin limit 70%,
with the 12% total-risk cap on (live) and off. Actual 2021 - Nov 2026 order + 1,000 reshuffles.
"""
import argparse

import pandas as pd

import run_portfolio_add as A
import run_risk_levels as RL


def weights_for(level):
    """Replay runs at risk=level; gold units get 4/level so they stay at 4%."""
    def w(tr):
        return {u: (4.0 / level if u.startswith("XAUUSD") else 1.0) for u in tr.unit.unique()}
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=float, default=3000)
    ap.add_argument("--mc", type=int, default=1000)
    a = ap.parse_args()
    h, m = A._load("hist"), A._load("mt5")
    t = pd.concat([h[h.entry_time < "2026-01-01"], m[m.entry_time >= "2026-01-01"]]).sort_values("entry_time")
    t = t.reset_index(drop=True)
    live0 = dict(A.LIVE)
    rows = []
    for cap in (True, False):
        A.LIVE.clear()
        A.LIVE.update(live0)
        if not cap:
            A.LIVE["max_open_risk_pct"] = None
        for level in (3, 4, 5, 6, 8):
            A._weights = weights_for(level)
            r = RL.run(t, level, A.LIVE, a.start)
            r.update(RL.mc(t, level, A.LIVE, a.start, a.mc))
            r.pop("yearly")
            rows.append(dict(cap="12% cap on" if cap else "12% cap off", non_gold_risk=f"{level}%", **r))
            print(rows[-1]["cap"], level, round(r["final"]), round(r["final_typical"]), round(r["final_bad"]),
                  round(r["maxdd"], 1), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("results/risk_nongold.csv", index=False)
    pd.set_option("display.width", 250)
    print(df[["cap", "non_gold_risk", "final", "trades", "final_typical", "final_bad", "maxdd", "dd_1in100",
              "worst_month", "biggest_loss", "share_lose_money"]].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
