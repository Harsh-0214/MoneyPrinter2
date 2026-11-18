"""What would cheaper (or dearer) trading do to the whole account? (Nov 18 2026)

    python run_cost_test.py

Re-runs every unit's backtest (histdata 2021-25 + broker 2026) with each market's spread floor
(`spread_pips`) set per scenario, then replays the whole account at live settings (risk, brake,
12% risk cap, 70% margin cap). Raw-spread accounts charge ~0.1-0.3 pips + a commission (~$7 per
100k round trip = 0.7 pips): modelled as one effective spread. Everything else stays as configured
(0.2-pip slippage on fills, wider rollover spread, financing). SPX500 (dry run) is left out.
Spreads in pips: FX pip 0.0001 / 0.01 (JPY), gold pip $0.10, SPX500 pip 0.1 point.
"""
import copy
import os

import pandas as pd
import yaml

import run_portfolio as rp
from run_ibs_portfolio import P, fixed_stats

SCEN = {  # market -> effective spread in pips
    "A today (FOREX.com demo)":        {"EURUSD": 1.4, "GBPUSD": 2.0, "USDJPY": 1.6, "XAUUSD": 8.0, "SPX500": 10.0},
    "B raw-spread account (typical)":  {"EURUSD": 0.9, "GBPUSD": 0.9, "USDJPY": 0.9, "XAUUSD": 2.5, "SPX500": 5.0},
    "C half of today":                 {"EURUSD": 0.7, "GBPUSD": 1.0, "USDJPY": 0.8, "XAUUSD": 4.0, "SPX500": 5.0},
    "D today + 0.5 pip slippage":      {"EURUSD": 1.9, "GBPUSD": 2.5, "USDJPY": 2.1, "XAUUSD": 13.0, "SPX500": 15.0},
}


def main():
    base = yaml.safe_load(open("config.yaml"))
    live, ml, risk = dict(base["live"]), float(base["risk"]["max_leverage"]), float(base["risk"]["risk_per_trade_pct"])
    rows = []
    for name, spreads in SCEN.items():
        cfg = copy.deepcopy(base)
        for pair in cfg["pairs"]:
            if pair["symbol"] in spreads:
                pair["spread_pips"] = spreads[pair["symbol"]]
        tag = name.split()[0]
        row = {"scenario": name}
        trades = {}
        for src in ("hist", "mt5"):
            path = f"results/cost_{tag}_{src}.csv"
            if os.path.exists(path):
                t = pd.read_csv(path)
                for c in ("entry_time", "exit_time"):
                    t[c] = pd.to_datetime(t[c], utc=True)
            else:
                print(f"{name}: running every unit ({src}) ...", flush=True)
                t = rp._units_trades(cfg, src)
                t.to_csv(path, index=False)
            trades[src] = t[t.unit != "SPX500"]
        h = trades["hist"]
        h = h[(h.entry_time >= "2021-01-01") & (h.entry_time < "2026-01-01")]
        row["avg R per trade 21-25"] = round(h.r_multiple.mean(), 3)
        for p, (src, a, b) in P.items():
            t = trades[src]
            t = t[(t.entry_time >= a) & (t.entry_time < b)].reset_index(drop=True)
            eq, _ = rp.replay(t, risk, live, ml)
            s = fixed_stats(eq, a, b)
            row[f"{p} month%"] = s["geo_month"]
            row[f"{p} DD%"] = s["maxdd"]
        for u, g in h.groupby("unit"):
            row[f"R/trade {u}"] = round(g.r_multiple.mean(), 3)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("scenario").T
    pd.set_option("display.width", 250)
    print(df.to_string())
    df.to_csv("results/cost_test.csv")


if __name__ == "__main__":
    main()
