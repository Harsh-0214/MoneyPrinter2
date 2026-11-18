"""Does the S&P 500 IBS unit improve the whole account? (Nov 18 2026)

    python run_ibs_portfolio.py [--refresh] [--mc 500]

Whole-account replay (run_portfolio.replay: every live unit, live risk, risk brake, 12% open-risk
cap, 70% margin cap with SPX500 at its real 10% margin) with the SPX500 IBS unit at 0 (= today's
bots) to 4% risk per trade. 2021-23 and 2024-25 from the history caches, 2026 from the broker feed.
"""
import argparse

import pandas as pd
import yaml

import run_portfolio as rp

P = {"2021-23": ("hist", "2021-01-01", "2024-01-01"), "2024-25": ("hist", "2024-01-01", "2026-01-01"),
     "2026": ("mt5", "2026-01-01", "2027-01-01")}


def fixed_stats(eq, start, end, start_eq=50_000.0):
    """Monthly stats over the fixed calendar window [start, end) so every row has the same months."""
    idx = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") - pd.Timedelta(days=1), freq="ME")
    now = pd.Timestamp.now(tz="UTC")
    idx = idx[idx <= now] if len(idx[idx <= now]) else idx
    full = pd.concat([pd.Series([start_eq], index=[pd.Timestamp(start, tz="UTC")]), eq]).sort_index()
    full = full[~full.index.duplicated(keep="last")]
    m = full.reindex(full.index.union(idx)).ffill().reindex(idx)
    if pd.Timestamp(end, tz="UTC") > now and eq.index.max() > idx[-1]:
        m.loc[eq.index.max()] = eq.iloc[-1]      # the running year (2026): include the partial month
    # a finished period stops at its end date: trades opened in it but closed after it (e.g. an
    # SPX500 trade opened Dec 30) are not allowed to add an extra month
    prev = m.shift(1).fillna(start_eq)
    mret = (m / prev - 1) * 100
    dd = (full / full.cummax() - 1).min() * 100
    geo = ((m.iloc[-1] / start_eq) ** (1 / len(m)) - 1) * 100
    return dict(geo_month=round(geo, 2), maxdd=round(dd, 1), worst_month=round(mret.min(), 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--mc", type=int, default=0)
    a = ap.parse_args()
    cfg = yaml.safe_load(open("config.yaml"))
    live, ml, base = dict(cfg["live"]), float(cfg["risk"]["max_leverage"]), float(cfg["risk"]["risk_per_trade_pct"])
    data = {s: rp.load_trades(cfg, s, a.refresh) for s in ("hist", "mt5")}
    for s, t in data.items():
        u = t[t.unit == "SPX500"]
        print(f"{s}: {len(u)} SPX500 trades {u.entry_time.min()} .. {u.entry_time.max()}, avg R {u.r_multiple.mean():+.3f}")
    rows = []
    for r in (0.0, 1.0, 2.0, 3.0, 4.0):
        w = {"SPX500": r / base}
        row = {"SPX500 risk %": r}
        for p, (src, x, y) in P.items():
            t = data[src]
            t = t[(t.entry_time >= x) & (t.entry_time < y)].reset_index(drop=True)
            if r == 0:
                t = t[t.unit != "SPX500"].reset_index(drop=True)     # exactly today's bots
            eq, taken = rp.replay(t, base, live, ml, weights=w)
            s = fixed_stats(eq, x, y)
            u = t.unit == "SPX500"
            row[f"{p} month%"] = s["geo_month"]
            row[f"{p} DD%"] = s["maxdd"]
            row[f"{p} worst mo"] = s["worst_month"]
            row[f"{p} other trades taken"] = int((taken & ~u).sum())
        if a.mc:
            t = data["hist"]
            t = t[(t.entry_time >= "2021-01-01") & (t.entry_time < "2026-01-01")]
            if r == 0:
                t = t[t.unit != "SPX500"]
            t = t.copy()
            m = t.unit == "SPX500"                  # risk weight via R and leverage (replay is linear in both)
            t.loc[m, "r_multiple"] *= r / base
            t.loc[m, "lev_per_1pct"] *= r / base
            row.update(rp.monte_carlo(t.reset_index(drop=True), base, live, ml, a.mc))
        rows.append(row)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).set_index("SPX500 risk %").T.to_string())


if __name__ == "__main__":
    main()
