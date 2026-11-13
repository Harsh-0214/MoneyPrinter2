"""Big US company stocks (CFDs on the same FOREX.com account), research only.

    python fetch_mt5_stocks.py        # once
    python run_stocks.py

Rules fixed before the first run (Nov 13 2026):
  Universes: the 12 biggest companies today, and the 14 biggest at the start of 2013. Today's
    leaders got big partly BY going up, so anything that buys looks good on them; the 2013 list is
    what "top companies" meant when the data starts. A strategy must pass on BOTH lists.
  Strategies (settings copied from the live bots, nothing tuned on stocks):
    Trend 55/20 and 20/10 (the gold rules), buy-only and buy+short;
    Volatility breakout (the USDJPY rules) inside the US session, buy+short;
    Momentum rotation: each month hold the 3 stocks with the best 12-month return (skipping the
    last month), vs simply holding all of them equally.
  Costs: recorded spread on every fill + 0.08% per side (1.8c/share commission with $10 minimum
    at our size + slippage) + CFD financing 7%/yr on buys, 1.5%/yr on shorts.
  Pass (trend/breakout): pooled PF >= 1.15 over 2013-2025, profitable in >= 9 of 13 years,
    2026 PF >= 1.0, on both lists. Rotation: must beat holding the same stocks (as CFDs).
"""
import copy
import os
from multiprocessing import Pool

import numpy as np
import pandas as pd

from fetch_mt5_stocks import TOP_2013, TOP_NOW, fname

COMM = 0.0008                      # per side: commission + slippage + spread the data under-records
FIN_LONG, FIN_SHORT = -7.0, -1.5   # %/yr of position value
SPLITS = [2, 3, 4, 5, 7, 8, 10, 15, 20]

_BARS = {}


def split_adjust(df, name="", verbose=False):
    """Find overnight jumps that match a split ratio and scale the earlier history."""
    df = df.copy()
    df["spread_pts"] = df["spread_pts"].astype(float)
    say = print if verbose else (lambda *a: None)
    gap = df.close.shift(1) / df.open
    short = df.index.to_series().diff() < pd.Timedelta(days=5)     # not across a hole in the data
    for t, r in gap[((gap > 1.6) | (gap < 0.6)) & short].items():
        f = r if r > 1 else 1 / r
        k = min(SPLITS, key=lambda s: abs(s - f) / s)
        i = df.index.get_loc(t)
        held = df.close.iloc[max(0, i - 7):i].median() / df.close.iloc[i:i + 7].median()
        if abs(held - r) / r > 0.15:                     # one bad print, not a new price level
            say(f"  {name}: one-off spike x{r:.2f} at {t} (ignored)")
            continue
        if abs(k - f) / k > 0.12:
            say(f"  {name}: unexplained jump x{r:.2f} at {t} (left as is)")
            continue
        k = k if r > 1 else 1 / k
        before = df.index < t
        df.loc[before, ["open", "high", "low", "close"]] /= k
        df.loc[before, "spread_pts"] /= k
        say(f"  {name}: split 1:{k:g} at {t.date()} - adjusted")
    return df


def load(name, verbose=False):
    df = pd.read_csv(fname(name), index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df = split_adjust(df, name, verbose)
    return df[["open", "high", "low", "close", "spread_pts"]].rename(columns={"spread_pts": "data_spread_pips"})


def make_cfg(name, spec):
    from run_new_markets import BASE
    point = float(pd.read_csv(fname(name), nrows=1)["point"].iloc[0])
    c = copy.deepcopy(BASE)
    c["smt"] = {}
    c["account"]["starting_equity"] = 1_000_000
    c["costs"].update(spread_pips=0, slippage_pips=0, rollover_spread_pips=0, use_data_spread=True,
                      swap_long_per_lot=0.0, swap_short_per_lot=0.0,
                      swap_long_pct=FIN_LONG, swap_short_pct=FIN_SHORT)
    c["risk"]["risk_per_trade_pct"] = 1.0
    c["risk"]["max_leverage"] = 50
    c["risk"]["news_filter"] = False
    c["instrument"] = {"pip": point, "min_units": 1}
    c["strategies"] = {"morning": [copy.deepcopy(spec)], "afternoon": []}
    c["strategy"] = {"daily_ema_period": 50}
    c["symbol"] = name
    return c


def strategies():
    from run_new_markets import T20, T55, VBO_LIVE, _v
    return {
        "Trend 55/20 buy-only":  T55,
        "Trend 55/20 buy+short": _v(T55, long_only=False),
        "Trend 20/10 buy-only":  T20,
        "Trend 20/10 buy+short": _v(T20, long_only=False),
        # US session in London time: 14:30-21:00; enter 15:00-19:00, out 20:00
        "Breakout US session":   _v(VBO_LIVE, entry_start="15:00", entry_end="19:00", exit_time="20:00"),
    }


def _init(names, verbose=False):
    for n in names:
        _BARS[n] = load(n, verbose)


def _run(job):
    from fxbot.backtest import run_backtest
    sname, name = job
    t, _ = run_backtest(_BARS[name], make_cfg(name, strategies()[sname]))
    if not len(t):
        return None
    t = t.copy()
    risk_amt = (t.pnl / t.r_multiple).abs().where(t.r_multiple != 0)
    risk_unit = risk_amt / t.units
    t["r_multiple"] = t.r_multiple - 2 * COMM * t.entry_price / risk_unit.fillna(np.inf)
    t["stock"], t["strategy"] = name, sname
    return t[["stock", "strategy", "side", "entry_time", "exit_time", "r_multiple"]]


def score(t):
    t = t.copy()
    t["y"] = pd.to_datetime(t.entry_time).dt.year
    ins, oos = t[t.y <= 2025], t[t.y >= 2026]
    pf = lambda x: x[x > 0].sum() / -x[x <= 0].sum() if (x <= 0).any() else np.inf
    yrs = ins.groupby("y").r_multiple.sum()
    r = dict(trades_yr=round(len(ins) / max(1, yrs.size), 1), pf=round(pf(ins.r_multiple), 2),
             avgR=round(ins.r_multiple.mean(), 3), totR=round(ins.r_multiple.sum(), 1),
             yrs_up=f"{(yrs > 0).sum()}/{yrs.size}", R26=round(oos.r_multiple.sum(), 1),
             pf26=round(pf(oos.r_multiple), 2))
    r["pass"] = bool(r["pf"] >= 1.15 and (yrs > 0).sum() >= 9 and r["pf26"] >= 1.0)
    return r


def daily_closes(names):
    out = {}
    for n in names:
        b = _BARS.get(n)
        if b is None:
            b = load(n)
        ny = b.index.tz_convert("America/New_York")
        out[n] = pd.Series(b.close.values, index=ny.normalize().tz_localize(None)).groupby(level=0).last()
    return pd.DataFrame(out).sort_index()


def rotation(names, top=3):
    """Monthly: hold the `top` stocks with the best 12-1 month return. CFD costs included."""
    c = daily_closes(names)
    m = c.resample("ME").last()
    ret = m.pct_change(fill_method=None)
    mom = m.shift(1) / m.shift(12) - 1                       # known at the start of the month
    fin = FIN_LONG / 100 / 12
    rows = []
    prev = set()
    for d in m.index[13:]:
        s = mom.loc[d].dropna()
        avail = ret.loc[d].dropna()
        s = s[s.index.isin(avail.index)]
        if len(s) < top + 2:
            continue
        pick = set(s.nlargest(top).index)
        turn = len(pick - prev) / top if prev else 1.0
        r_pick = avail[list(pick)].mean() + fin - 2 * COMM * turn
        r_all = avail.mean() + fin
        rows.append(dict(month=d, pick=r_pick, all=r_all))
        prev = pick
    return pd.DataFrame(rows).set_index("month")


def rot_report(label, r):
    def cagr(x):
        return (1 + x).prod() ** (12 / len(x)) - 1
    def dd(x):
        e = (1 + x).cumprod()
        return (e / e.cummax() - 1).min()
    ins, oos = r[r.index.year <= 2025], r[r.index.year >= 2026]
    yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
    beat = (yr["pick"] > yr["all"]).sum()
    print(f"  {label}: top-3 {cagr(ins.pick)*100:+.1f}%/yr (worst DD {dd(ins.pick)*100:.0f}%) vs hold-all "
          f"{cagr(ins['all'])*100:+.1f}%/yr (DD {dd(ins['all'])*100:.0f}%), beat it in {beat}/{len(yr)} years; "
          f"2026: {((1+oos.pick).prod()-1)*100:+.1f}% vs {((1+oos['all']).prod()-1)*100:+.1f}%")


def main():
    names = list(dict.fromkeys(TOP_NOW + TOP_2013))
    names = [n for n in names if os.path.exists(fname(n))]
    print("Split check:")
    _init(names, verbose=True)
    for n in names:
        b = _BARS[n]
        print(f"  {n:30s} {b.index[0].date()} -> {b.index[-1].date()}  {len(b)} bars")
    jobs = [(s, n) for s in strategies() for n in names]
    with Pool(6, initializer=_init, initargs=(names,)) as pool:
        res = [r for r in pool.imap_unordered(_run, jobs) if r is not None]
    T = pd.concat(res)
    T = T[pd.to_datetime(T.entry_time) >= "2013-06-01"]
    os.makedirs("results", exist_ok=True)
    T.to_csv("results/stocks_trades.csv", index=False)

    pd.set_option("display.width", 250)
    rows = []
    for lst_name, lst in (("today's top 12", TOP_NOW), ("2013's top 14", TOP_2013)):
        for s in strategies():
            g = T[(T.strategy == s) & T.stock.isin(lst)]
            if len(g):
                rows.append(dict(list=lst_name, strategy=s, **score(g)))
    print("\n=== Trend / breakout, pooled across the list, R per trade at 1% risk ===")
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n=== Per stock, today's top 12 (total R 2013-2025 | 2026) ===")
    piv = T[T.stock.isin(TOP_NOW)].assign(p=lambda x: np.where(pd.to_datetime(x.entry_time).dt.year >= 2026, "26", "13_25"))
    print(piv.pivot_table(index="stock", columns=["strategy", "p"], values="r_multiple", aggfunc="sum").round(1).to_string())

    print("\n=== Momentum rotation (monthly, top 3 by 12-1 month return) ===")
    for lst_name, lst in (("today's top 12", TOP_NOW), ("2013's top 14", TOP_2013)):
        rot_report(lst_name, rotation([n for n in lst if n in names]))


if __name__ == "__main__":
    main()
