"""Positioning research: CFTC Commitments of Traders vs the markets the bot trades.

    (download deacot*.zip from cftc.gov into data/cot/, then)  python fetch_cot.py
    python run_cot.py

Rules were fixed before the first run (Nov 13 2026):
  COT index = where a group's net position (long - short) sits in its own 3-year range, 0-100.
  T1 crowd fade   : speculators' index >= 90 -> bet against them, <= 10 -> bet with a reversal.
                    Hold 4 weeks (20 trading days), one trade per market at a time.
  T2 commercials  : hedgers' index >= 90 -> go their way (long), <= 10 -> short. Hold 4 weeks.
  T3 follow flow  : each week, take the direction speculators added to over the last 4 weeks
                    (change in net / open interest). Re-decided weekly.
  T4 filter       : the bot's own trades (2021-2026), split by whether speculators were already
                    crowded (>= 80 / <= 20) on the trade's side, and by 4-week flow direction.
Entries: the Monday open after the Friday 15:30 NY release (Tuesday data) - no lookahead.
Results in R: a trade's move divided by 2 x the 20-day ATR at entry (a typical stop).
Costs: today's spread on every entry and exit + 2%/yr financing on every position (pessimistic:
carry can also be earned). Judged on 2007-2020, then confirmed once on 2021-2026.
"""
import numpy as np
import pandas as pd

# futures long the foreign currency = which way on the MT5 symbol
SIGN = {"EUR": 1, "GBP": 1, "AUD": 1, "XAU": 1, "JPY": -1, "CAD": -1, "CHF": -1}
SPREAD = {"EUR": 0.00014, "GBP": 0.0002, "AUD": 0.00015, "CAD": 0.00025, "CHF": 0.0002,
          "JPY": 0.016, "XAU": 0.8}
FIN = 0.02 / 365
LOOK = 156                      # weeks in the COT index range (3 years)
UNIT_MARKET = {"EURUSD": "EUR", "GBPUSD": "GBP", "USDJPY": "JPY", "XAUUSD": "XAU"}


def cot_table():
    d = pd.read_csv("data/cot/cot.csv", parse_dates=["report_date"])
    d["release"] = pd.to_datetime(d["release"], utc=True)
    out = []
    for m, g in d.groupby("market"):
        g = g.sort_values("report_date").copy()
        for grp, l, s in (("spec", "spec_long", "spec_short"), ("comm", "comm_long", "comm_short")):
            net = g[l] - g[s]
            lo, hi = net.rolling(LOOK, min_periods=LOOK).min(), net.rolling(LOOK, min_periods=LOOK).max()
            g[f"{grp}_idx"] = (net - lo) / (hi - lo).replace(0, np.nan) * 100
        g["flow"] = (g["spec_long"] - g["spec_short"]).diff(4) / g["open_interest"]
        out.append(g)
    return pd.concat(out)


def prices(m):
    p = pd.read_csv(f"data/cot/{m}_D1.csv", index_col=0, parse_dates=True)
    p = p[p.index.dayofweek < 5]
    tr = pd.concat([p.high - p.low, (p.high - p.close.shift()).abs(), (p.low - p.close.shift()).abs()], axis=1).max(axis=1)
    p["atr"] = tr.rolling(20).mean().shift(1)          # known before today's open
    return p


def trade(p, i_in, i_out, side_foreign, m):
    """side_foreign: +1 = long the foreign currency / gold. Returns R."""
    side = side_foreign * SIGN[m]
    e, x = p.open.iloc[i_in], p.open.iloc[i_out]
    days = (p.index[i_out] - p.index[i_in]).days
    gross = side * (x - e)
    cost = SPREAD[m] + FIN * days * e
    risk = 2 * p.atr.iloc[i_in]
    return (gross - cost) / risk if risk > 0 else np.nan


def entry_index(p, release_utc):
    """First daily bar strictly after the release day (= the Monday open)."""
    day = release_utc.tz_convert("America/New_York").normalize().tz_localize(None)
    return p.index.searchsorted(day + pd.Timedelta(days=1))


def run_events(cot, rule, hold=20):
    rows = []
    for m, g in cot.groupby("market"):
        p = prices(m)
        busy_until = -1
        for r in g.itertuples():
            sig = rule(r)
            if not sig:
                continue
            i = entry_index(p, r.release)
            if i <= busy_until or i + hold >= len(p) or not np.isfinite(p.atr.iloc[i]):
                continue
            rows.append(dict(market=m, date=p.index[i], R=trade(p, i, i + hold, sig, m)))
            busy_until = i + hold
    return pd.DataFrame(rows)


def run_flow(cot):
    rows = []
    for m, g in cot.groupby("market"):
        p = prices(m)
        g = g.dropna(subset=["flow"])
        rel = list(g.itertuples())
        prev = 0
        for a, b in zip(rel[:-1], rel[1:]):
            sig = int(np.sign(a.flow))
            i, j = entry_index(p, a.release), entry_index(p, b.release)
            if not sig or j >= len(p) or i >= j or not np.isfinite(p.atr.iloc[i]):
                continue
            side = sig * SIGN[m]
            gross = side * (p.open.iloc[j] - p.open.iloc[i])
            cost = (SPREAD[m] if sig != prev else 0.0) + FIN * (p.index[j] - p.index[i]).days * p.open.iloc[i]
            rows.append(dict(market=m, date=p.index[i], R=(gross - cost) / (2 * p.atr.iloc[i])))
            prev = sig
    return pd.DataFrame(rows)


def summarize(name, t):
    if not len(t):
        print(f"{name}: no trades")
        return
    t = t.dropna()
    t["y"] = t.date.dt.year
    ins, oos = t[(t.y >= 2007) & (t.y <= 2020)], t[t.y >= 2021]
    yrs = ins.groupby("y").R.sum()
    print(f"\n=== {name} ===")
    print(f"  2007-20: {len(ins)} trades, avg {ins.R.mean():+.3f}R, total {ins.R.sum():+.1f}R, "
          f"years up {(yrs > 0).sum()}/{len(yrs)} | 2021-26: {len(oos)} trades, avg {oos.R.mean():+.3f}R, "
          f"total {oos.R.sum():+.1f}R")
    by = t.groupby("market").apply(lambda x: pd.Series({
        "n07_20": int((x.y <= 2020).sum()), "avgR07_20": x[x.y <= 2020].R.mean(),
        "n21_26": int((x.y >= 2021).sum()), "avgR21_26": x[x.y >= 2021].R.mean()}), include_groups=False)
    print(by.round(3).to_string())


def filter_test(cot):
    """T4: the bot's own trades (portfolio sim caches) by positioning at entry."""
    import yaml
    import run_portfolio as rp
    cfg = yaml.safe_load(open("config.yaml"))
    T = pd.concat([rp.load_trades(cfg, "hist"), rp.load_trades(cfg, "mt5")])
    T = T[T.entry_time >= "2021-01-01"].copy()
    T["m"] = T.market.map(UNIT_MARKET)
    out = []
    for m, g in T.groupby("m"):
        c = cot[cot.market == m].sort_values("release")
        k = c.release.searchsorted(g.entry_time, side="right") - 1        # latest report already out
        ok = k >= 0
        g = g[ok].copy()
        row = c.iloc[k[ok]]
        g["idx"], g["flow"] = row.spec_idx.to_numpy(), row.flow.to_numpy()
        g["dir"] = g.side * SIGN[m]                                     # +1 = long the foreign ccy / gold
        g["crowded_with"] = ((g.dir == 1) & (g.idx >= 80)) | ((g.dir == -1) & (g.idx <= 20))
        g["crowded_against"] = ((g.dir == 1) & (g.idx <= 20)) | ((g.dir == -1) & (g.idx >= 80))
        g["flow_with"] = np.sign(g.flow) == g.dir
        out.append(g)
    g = pd.concat(out)
    g["period"] = np.where(g.entry_time < "2024-01-01", "2021-23", "2024-26")
    print("\n=== T4 filter: the bot's own trades, avg R by positioning at entry ===")
    for col in ("crowded_with", "crowded_against", "flow_with"):
        tab = g.groupby(["period", col]).r_multiple.agg(["count", "mean", "sum"]).round(3)
        print(f"\n{col}:\n{tab.to_string()}")
    print("\nby unit, crowded_with:")
    print(g.groupby(["unit", "crowded_with"]).r_multiple.agg(["count", "mean"]).round(3).to_string())


def main():
    pd.set_option("display.width", 200)
    cot = cot_table()
    summarize("T1 crowd fade (spec index >=90 sell / <=10 buy, 4 weeks)",
              run_events(cot, lambda r: -1 if r.spec_idx >= 90 else (1 if r.spec_idx <= 10 else 0)))
    summarize("T2 commercials (comm index >=90 buy / <=10 sell, 4 weeks)",
              run_events(cot, lambda r: 1 if r.comm_idx >= 90 else (-1 if r.comm_idx <= 10 else 0)))
    summarize("T3 follow 4-week spec flow (weekly)", run_flow(cot))
    filter_test(cot)


if __name__ == "__main__":
    main()
