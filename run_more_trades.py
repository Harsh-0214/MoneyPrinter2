"""More trades from the edges that already work, plus one new idea (weekend gap fade).

    python run_more_trades.py                 # everything (~20 min, 6 workers)
    python run_more_trades.py --only gold     # variants whose name contains "gold"

Rules fixed before the run. Each variant runs alone at 1% risk, real spreads + slippage:
  * design data: histdata M1 2021-2025 (resampled), judged on 2021-23 first, then 2024-25;
  * independent feed: the broker's own H1 2019-2026 (trend variants) or M15 mid-2024-2026
    (intraday variants); 2026 is data no setting was ever tuned on.
A candidate passes if: PF >= 1.15 and >= 4/5 years up on 2021-25, and 2026 PF >= 1.0.
run_portfolio_add.py then measures what a passing candidate adds to the live portfolio.
"""
import argparse
import copy
import os
from multiprocessing import Pool

import pandas as pd
import yaml

BASE = yaml.safe_load(open("config.yaml"))
_P = {p["symbol"]: p for p in BASE["pairs"]}
T55 = _P["XAUUSD"]["strategies"]["morning"][0]
T20, A55, A20 = [s["strategies"]["morning"][0] for s in _P["XAUUSD"]["sleeves"]]
VBO = _P["USDJPY"]["strategies"]["morning"][0]
DPB = _P["GBPUSD"]["sleeves"][0]["strategies"]["morning"][0]

HIST = {"EURUSD": "data/EURUSD_M1_histdata.csv", "GBPUSD": "data/GBPUSD_M1_histdata.csv",
        "USDJPY": "data/USDJPY_M1_histdata.csv", "XAUUSD": "data/XAUUSD_M1_histdata.csv",
        "AUDUSD": "data/AUDUSD_M1_histdata.csv"}
AUD = {"symbol": "AUDUSD", "spread_pips": 1.5, "data": {"path": HIST["AUDUSD"], "source_tz": "UTC"}}


def _v(base, **kw):
    s = copy.deepcopy(base)
    s.update(kw)
    return s


GAP = dict(name="weekend_gap", min_gap_atr=0.2, fill_frac=1.0, stop_rr=1.0, entry_delay_min=15,
           entry_cutoff_hours=6, exit_time="20:00")

#  name: (market, timeframe, [specs], slot_max_trades, independent-feed file kind)
VARIANTS = {
    "gold 55/20 (live)":              ("XAUUSD", "1h", [T55], 1, "H1"),
    "gold 20/10 (live)":              ("XAUUSD", "1h", [T20], 1, "H1"),
    "gold add55 @0.5R (live)":        ("XAUUSD", "1h", [A55], 1, "H1"),
    "gold add20 @0.5R (live)":        ("XAUUSD", "1h", [A20], 1, "H1"),
    "gold 10/5 long":                 ("XAUUSD", "1h", [_v(T20, entry_days=10, exit_days=5)], 1, "H1"),
    "gold 55/20 intraday entry":      ("XAUUSD", "1h", [_v(T55, intraday_entry=True)], 1, "H1"),
    "gold 20/10 intraday entry":      ("XAUUSD", "1h", [_v(T20, intraday_entry=True)], 1, "H1"),
    "gold 55/20 trail only":          ("XAUUSD", "1h", [_v(T55, exit_days=None)], 1, "H1"),
    "gold add55 @1.0R":               ("XAUUSD", "1h", [_v(A55, add_on_r=1.0)], 1, "H1"),
    "gold add55 @1.5R":               ("XAUUSD", "1h", [_v(A55, add_on_r=1.5)], 1, "H1"),
    "gold add20 @1.0R":               ("XAUUSD", "1h", [_v(A20, add_on_r=1.0)], 1, "H1"),
    "gold add20 @1.5R":               ("XAUUSD", "1h", [_v(A20, add_on_r=1.5)], 1, "H1"),
    "jpy VBO (live)":                 ("USDJPY", "15min", [VBO], 1, "M15"),
    "jpy VBO re-entry 2/day":         ("USDJPY", "15min", [_v(VBO, max_trades_per_day=2)], 2, "M15"),
    "jpy VBO add-on @0.5R":           ("USDJPY", "15min", [_v(VBO, add_on_r=0.5)], 1, "M15"),
    "jpy VBO add-on @1.0R":           ("USDJPY", "15min", [_v(VBO, add_on_r=1.0)], 1, "M15"),
    "jpy VBO Mondays too":            ("USDJPY", "15min", [_v(VBO, skip_days=[])], 1, "M15"),
    "jpy VBO no trend filter":        ("USDJPY", "15min", [_v(VBO, trend_sma=None)], 1, "M15"),
    "jpy VBO Mondays + no trend":     ("USDJPY", "15min", [_v(VBO, skip_days=[], trend_sma=None)], 1, "M15"),
    "jpy VBO no trend + re-entry":    ("USDJPY", "15min", [_v(VBO, trend_sma=None, max_trades_per_day=2)], 2, "M15"),
    "jpy VBO (live) [H1 feed]":       ("USDJPY", "1h", [VBO], 1, "H1"),
    "jpy VBO re-entry [H1 feed]":     ("USDJPY", "1h", [_v(VBO, max_trades_per_day=2)], 2, "H1"),
    "jpy VBO add-on @0.5R [H1 feed]": ("USDJPY", "1h", [_v(VBO, add_on_r=0.5)], 1, "H1"),
    "jpy pullback (GBP settings)":    ("USDJPY", "1h", [DPB], 1, "H1"),
    "aud pullback (GBP settings)":    ("AUDUSD", "1h", [DPB], 1, "H1"),
    "aud VBO (JPY settings)":         ("AUDUSD", "15min", [VBO], 1, "M15"),
}
for mk in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"):
    for mg in (0.15, 0.3):
        for ff in (1.0, 0.5):
            for dl in (15, 60):
                VARIANTS[f"gap {mk} min{mg} fill{ff} delay{dl}"] = (
                    mk, "5min", [_v(GAP, min_gap_atr=mg, fill_frac=ff, entry_delay_min=dl)], 1, "M15")


def pair_entry(mk):
    return _P.get(mk, AUD)


def hist_bars(mk, tf):
    from run_validate import _bars
    return _bars(HIST[mk], "UTC", tf)


def mt5_bars(mk, kind, pip, floor_pips):
    """Broker history (fetch_mt5_more.py / fetch_mt5_h1.py) with its recorded spread."""
    fn = f"data/mt5/{mk}_{kind}.csv"
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    point = float(df["point"].iloc[0])
    out = df[["open", "high", "low", "close"]].copy()
    out["data_spread_pips"] = (df["spread_pts"] * point / pip).clip(lower=floor_pips)
    return out


def make_cfg(mk, tf, specs, slot):
    from fxbot.backtest import pair_config
    c = pair_config(BASE, pair_entry(mk))
    c["smt"] = {}
    c["data"]["timeframe"] = tf
    c["account"]["starting_equity"] = 1_000_000
    c["risk"]["risk_per_trade_pct"] = 1.0
    c["risk"]["max_leverage"] = 1000
    c["strategies"] = {"morning": copy.deepcopy(specs), "afternoon": []}
    c["slot_max_trades"] = slot
    c["symbol"] = mk
    return c


def _pf(t):
    gl = -t.pnl[t.pnl <= 0].sum() if len(t) else 0.0
    return round(t.pnl[t.pnl > 0].sum() / gl, 2) if gl > 0 else float("inf")


def run_variant(name):
    """(summary row, hist trades, broker-feed trades) for one variant."""
    from fxbot.backtest import instrument_pip, run_backtest
    mk, tf, specs, slot, kind = VARIANTS[name]
    c = make_cfg(mk, tf, specs, slot)
    pip = instrument_pip(c)
    t, eq = run_backtest(hist_bars(mk, tf), c)
    row = dict(name=name, market=mk)
    if len(t):
        t = t.copy()
        t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
        t["year"] = t.entry_time.dt.year
    yrs = {y: (round(t[t.year == y].r_multiple.sum(), 1) if len(t) else 0.0) for y in range(2021, 2026)}
    row.update(n=len(t), trades_yr=round(len(t) / 5, 1),
               avgR=round(t.r_multiple.mean(), 3) if len(t) else 0.0, pf=_pf(t),
               yrs_up=sum(v > 0 for v in yrs.values()),
               R21_23=round(sum(yrs[y] for y in (2021, 2022, 2023)), 1),
               R24_25=round(yrs[2024] + yrs[2025], 1))
    row.update({f"y{y % 100}": v for y, v in yrs.items()})
    t2 = pd.DataFrame()
    mb = mt5_bars(mk, kind, pip, float(c["costs"]["spread_pips"]))
    if mb is not None:
        c2 = copy.deepcopy(c)
        c2["data"]["timeframe"] = "1h" if kind == "H1" else "15min"
        t2, _ = run_backtest(mb, c2)
        if len(t2):
            t2 = t2.copy()
            t2["entry_time"] = pd.to_datetime(t2["entry_time"], utc=True)
            o = t2[t2.entry_time >= "2026-01-01"]
            row.update(n26=len(o), R26=round(o.r_multiple.sum(), 1), pf26=_pf(o))
            if kind == "H1":
                pre = t2[(t2.entry_time >= "2019-01-01") & (t2.entry_time < "2021-01-01")]
                row["R19_20"] = round(pre.r_multiple.sum(), 1)
        else:
            row.update(n26=0, R26=0.0, pf26=float("nan"))
    row["PASS"] = bool(row["pf"] >= 1.15 and row["yrs_up"] >= 4 and row.get("pf26", 0) >= 1.0)
    return row, t, t2


def _run(name):
    row, _, _ = run_variant(name)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="results/more_trades.csv")
    a = ap.parse_args()
    names = [n for n in VARIANTS if a.only.lower() in n.lower()]
    print(f"{len(names)} variants ...", flush=True)
    rows = []
    with Pool(a.workers) as pool:
        for row in pool.imap_unordered(_run, names):
            rows.append(row)
            print(f"  {row['name']:<36} {row['trades_yr']:5.1f}/yr pf {row['pf']:.2f} avgR {row['avgR']:+.3f} "
                  f"yrs {row['yrs_up']}/5  R21-23 {row['R21_23']:+.1f}  R24-25 {row['R24_25']:+.1f}  "
                  f"2026 {row.get('R26', float('nan')):+.1f}R pf {row.get('pf26', float('nan'))}"
                  + ("  PASS" if row["PASS"] else ""), flush=True)
    df = pd.DataFrame(rows).set_index("name").loc[[n for n in names]].reset_index()
    os.makedirs("results", exist_ok=True)
    df.to_csv(a.out, index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
