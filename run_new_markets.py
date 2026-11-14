"""New markets: the strategies that already work here, on markets never tested before.

    python fetch_mt5_h1.py                     # once: broker's own H1 history -> data/mt5/
    python run_new_markets.py                  # every strategy x every market, 2019-2026
    python run_new_markets.py --markets SPX500,NAS100 --only trend

Uses the FOREX.com MT5 feed itself (the prices the bot would trade), H1 bars from mid-2018,
with each bar's recorded spread (floored at today's typical spread) plus slippage.
Strategy settings are copied from the live config UNCHANGED - nothing is tuned on these
markets, so every number here is out-of-sample for the settings.

Scoring (decided before the run, same bar as the research log):
  pass = PF >= 1.15 on 2019-2025, profitable in >= 5 of those 7 years, and 2026 PF >= 1.0.
All money is in the market's quote currency (R-multiples don't depend on it).
"""
import argparse
import copy
import os
from multiprocessing import Pool

import pandas as pd
import yaml

#  name        file                     spread floor (MT5 points)  financing %/yr (long, short)
MARKETS = {
    "SPX500":  ("data/mt5/SPX500_H1.csv",  6,   (-6.5, -1.5)),
    "NAS100":  ("data/mt5/NAS100_H1.csv",  30,  (-6.5, -1.5)),
    "US30":    ("data/mt5/US30_H1.csv",    50,  (-6.5, -1.5)),
    "GER40":   ("data/mt5/GER40_H1.csv",   31,  (-6.5, -1.5)),
    "UK100":   ("data/mt5/UK100_H1.csv",   26,  (-6.5, -1.5)),
    "JPN225":  ("data/mt5/JPN225_H1.csv",  15,  (-6.5, -1.5)),
    "XAGUSD":  ("data/mt5/XAGUSD_H1.csv",  40,  (-6.5, -1.5)),
    "USOil":   ("data/mt5/USOil_H1.csv",   30,  (-6.5, -1.5)),
    "EURJPY":  ("data/mt5/EURJPY_H1.csv",  33,  (0.0, -2.0)),
    "GBPJPY":  ("data/mt5/GBPJPY_H1.csv",  42,  (0.0, -2.0)),
    "CADJPY":  ("data/mt5/CADJPY_H1.csv",  36,  (0.0, -2.0)),
    "AUDJPY":  ("data/mt5/AUDJPY_H1.csv",  30,  (0.0, -2.0)),
    # reference: markets already live, same feed, to compare with the histdata results
    "XAUUSD":  ("data/mt5/XAUUSD_H1.csv",  80,  (-6.5, -1.5)),
    "USDJPY":  ("data/mt5/USDJPY_H1.csv",  16,  (0.0, -2.0)),
    # --- round 2 (13 Nov 2026, fetch_mt5_more.py): spread floor = median of the last 90 days
    "Copper":       ("data/mt5/Copper_H1.csv",       25, (-6.5, -1.5)),
    "USNaturalGas": ("data/mt5/USNaturalGas_H1.csv", 11, (-6.5, -1.5)),
    "UKOil":        ("data/mt5/UKOil_H1.csv",         5, (-6.5, -1.5)),
    "SugarCash":    ("data/mt5/SugarCash_H1.csv",    20, (-6.5, -1.5)),
    "US2000":       ("data/mt5/US2000_H1.csv",        6, (-6.5, -1.5)),
    "AUS200":       ("data/mt5/AUS200_H1.csv",        4, (-6.5, -1.5)),
    "CHINAA50":     ("data/mt5/CHINAA50_H1.csv",     10, (-6.5, -1.5)),
    "FRA40":        ("data/mt5/FRA40_H1.csv",        23, (-6.5, -1.5)),
    "ESP35":        ("data/mt5/ESP35_H1.csv",         8, (-6.5, -1.5)),
    "SWISS20":      ("data/mt5/SWISS20_H1.csv",       4, (-6.5, -1.5)),
    "USDCAD":       ("data/mt5/USDCAD_H1.csv",       11, (0.0, -2.0)),
    "USDCHF":       ("data/mt5/USDCHF_H1.csv",       16, (0.0, -2.0)),
    "NZDUSD":       ("data/mt5/NZDUSD_H1.csv",       19, (0.0, -2.0)),
    "AUDUSD":       ("data/mt5/AUDUSD_H1.csv",       11, (0.0, -2.0)),
    "EURGBP":       ("data/mt5/EURGBP_H1.csv",       13, (0.0, -2.0)),
    "EURAUD":       ("data/mt5/EURAUD_H1.csv",       31, (0.0, -2.0)),
    "GBPAUD":       ("data/mt5/GBPAUD_H1.csv",       57, (0.0, -2.0)),
    "EURCAD":       ("data/mt5/EURCAD_H1.csv",       32, (0.0, -2.0)),
    "GBPCAD":       ("data/mt5/GBPCAD_H1.csv",       45, (0.0, -2.0)),
    "AUDNZD":       ("data/mt5/AUDNZD_H1.csv",       50, (0.0, -2.0)),
    "EURCHF":       ("data/mt5/EURCHF_H1.csv",       11, (0.0, -2.0)),
    "GBPCHF":       ("data/mt5/GBPCHF_H1.csv",       40, (0.0, -2.0)),
    "AUDCAD":       ("data/mt5/AUDCAD_H1.csv",       35, (0.0, -2.0)),
    "NZDJPY":       ("data/mt5/NZDJPY_H1.csv",       30, (0.0, -2.0)),
    "CHFJPY":       ("data/mt5/CHFJPY_H1.csv",       35, (0.0, -2.0)),
    "EURNZD":       ("data/mt5/EURNZD_H1.csv",       60, (0.0, -2.0)),
    "GBPNZD":       ("data/mt5/GBPNZD_H1.csv",       80, (0.0, -2.0)),
}
ROUND2 = [m for m in MARKETS if m in ("Copper", "USNaturalGas", "UKOil", "SugarCash", "US2000", "AUS200",
                                       "CHINAA50", "FRA40", "ESP35", "SWISS20") or
          (len(m) == 6 and m.isupper() and m not in ("XAUUSD", "USDJPY", "XAGUSD", "EURJPY", "GBPJPY",
                                                     "CADJPY", "AUDJPY", "SPX500", "NAS100", "GER40", "UK100", "JPN225"))]

BASE = yaml.safe_load(open("config.yaml"))
_P = {p["symbol"]: p for p in BASE["pairs"]}
VBO_LIVE = _P["USDJPY"]["strategies"]["morning"][0]
T55 = _P["XAUUSD"]["strategies"]["morning"][0]
T20, A55, A20 = [s["strategies"]["morning"][0] for s in _P["XAUUSD"]["sleeves"]]
DPB_LIVE = _P["GBPUSD"]["sleeves"][0]["strategies"]["morning"][0]


def _v(base, **kw):
    s = copy.deepcopy(base)
    s.update(kw)
    return s


STRATS = {
    "VBO (USDJPY live)":         VBO_LIVE,
    "VBO US session 14-19":      _v(VBO_LIVE, entry_start="14:00", entry_end="19:00", exit_time="20:00"),
    "Trend 55/20 long (gold)":   T55,
    "Trend 20/10 long (gold)":   T20,
    "Trend 55 add-on (gold)":    A55,
    "Trend 20 add-on (gold)":    A20,
    "Pullback (GBP live)":       DPB_LIVE,
    "Pullback long-only":        _v(DPB_LIVE, long_only=True),
}

_BARS = {}


def load(sym, floor):
    path = MARKETS[sym][0]
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "spread_pts"]].rename(columns={"spread_pts": "data_spread_pips"})
    df = df[df.index >= "2018-06-01"]                 # hourly bars start mid-2018 (daily before)
    df["data_spread_pips"] = df["data_spread_pips"].clip(lower=floor)
    return df


def _init(markets):
    for s in markets:
        _BARS[s] = load(s, MARKETS[s][1])


def make_cfg(sym, spec):
    path, floor, (fl, fs) = MARKETS[sym]
    point = float(pd.read_csv(path, nrows=1)["point"].iloc[0])
    c = copy.deepcopy(BASE)
    c["smt"] = {}
    c["account"]["starting_equity"] = 1_000_000       # big account: no lot-rounding noise in R
    c["costs"].update(spread_pips=floor, slippage_pips=0.25 * floor, rollover_spread_pips=0,
                      swap_long_per_lot=0.0, swap_short_per_lot=0.0,
                      swap_long_pct=fl, swap_short_pct=fs)
    c["risk"]["risk_per_trade_pct"] = 1.0
    c["risk"]["max_leverage"] = 50
    c["risk"]["news_filter"] = False                  # calendar only covers FX releases
    c["instrument"] = {"pip": point, "min_units": 1}
    c["strategies"] = {"morning": [copy.deepcopy(spec)], "afternoon": []}
    c["strategy"] = {"daily_ema_period": 50}
    c["symbol"] = sym
    return c


def _run(job):
    from fxbot.backtest import run_backtest
    from run_validate import summarize, per_year
    name, sym = job
    c = make_cfg(sym, STRATS[name])
    if len(sym) == 6 and sym.isupper() and sym not in ("XAUUSD", "XAGUSD", "SPX500", "NAS100", "GER40", "UK100", "USDJPY"):
        c["instrument"]["min_units"] = 1000          # FX crosses: micro lots
    se = c["account"]["starting_equity"]
    t, eq = run_backtest(_BARS[sym], c)
    if not len(t):
        return None
    t = t.copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"])
    ins = t[(t.entry_time >= "2019-01-01") & (t.entry_time < "2026-01-01")]
    oos = t[t.entry_time >= "2026-01-01"]
    e_in = eq[(eq.index >= "2019-01-01") & (eq.index < "2026-01-01")]
    m = summarize(ins, e_in / e_in.iloc[0] * se, se)
    py = per_year(ins, e_in / e_in.iloc[0] * se, se)
    yrs = dict(zip(py.year, py["ret%"]))
    pf26 = (oos.pnl[oos.pnl > 0].sum() / -oos.pnl[oos.pnl <= 0].sum()) if (oos.pnl <= 0).any() else float("inf")
    pos = sum(v > 0 for v in yrs.values())
    row = dict(market=sym, strategy=name, trades_yr=round(len(ins) / 7, 1), ret=m["ret%"], dd=m["dd%"],
               pf=m["pf"], avgR=m["avgR"], win=m["win%"], pos_years=f"{pos}/7",
               **{f"y{y % 100}": v for y, v in yrs.items()},
               n26=len(oos), R26=round(oos.r_multiple.sum(), 1), pf26=round(pf26, 2))
    row["PASS"] = bool(m["pf"] >= 1.15 and pos >= 5 and pf26 >= 1.0)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default=",".join(MARKETS))
    ap.add_argument("--round2", action="store_true", help="only the markets added on 13 Nov 2026")
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="results/new_markets.csv")
    a = ap.parse_args()
    markets = [m for m in (ROUND2 if a.round2 else a.markets.split(",")) if os.path.exists(MARKETS[m][0])]
    jobs = [(n, s) for n in STRATS if a.only.lower() in n.lower() for s in markets]
    print(f"{len(jobs)} runs ...", flush=True)
    rows = []
    with Pool(a.workers, initializer=_init, initargs=(markets,)) as pool:
        for r in pool.imap_unordered(_run, jobs):
            if r:
                rows.append(r)
                print(f"  {r['market']:<7} {r['strategy']:<26} {r['trades_yr']:5.1f}/yr pf {r['pf']:.2f} "
                      f"avgR {r['avgR']:+.3f} yrs {r['pos_years']}  2026 {r['R26']:+.1f}R pf {r['pf26']}"
                      f"{'  PASS' if r['PASS'] else ''}", flush=True)
    df = pd.DataFrame(rows).sort_values(["PASS", "pf"], ascending=False)
    os.makedirs("results", exist_ok=True)
    df.to_csv(a.out, index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
