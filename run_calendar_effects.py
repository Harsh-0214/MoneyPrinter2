"""Calendar / flow effects screen (Nov 2026, research only - none passed).

    python fetch_mt5_h1.py           # once
    python run_calendar_effects.py

Vectorised, with costs (1.25 x spread) and long financing 6.5%/yr per night:
  turn-of-month on 6 indices (2001-2026), overnight vs intraday index drift (2018-26),
  pre-FOMC drift (2019-26), gold return by hour on two feeds, month-end USD rebalancing
  into the London 4pm fix (2010-26). Results: docs/RESEARCH_LOG.md (12 Nov 2026).
"""
import sys
import numpy as np
import pandas as pd

D = "data/mt5/"
FLOOR = {"SPX500": 6, "NAS100": 30, "US30": 50, "GER40": 31, "UK100": 26, "JPN225": 15,
         "XAUUSD": 80, "XAGUSD": 40}
FIN = 0.065 / 365          # long financing per night (pessimistic, like gold)


def load(sym):
    df = pd.read_csv(D + f"{sym}_H1.csv", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def daily_us_close(df):
    """One close per trading day at ~16:00 New York. Pre-2018-06 bars are daily already
    (labelled 22:00 UTC the day before, closing at server midnight ~ 17:00 NY)."""
    old = df[df.index < "2018-06-01"]
    new = df[df.index >= "2018-06-01"]
    o = pd.Series(old.close.values, index=(old.index + pd.Timedelta(hours=2)).normalize().tz_localize(None))
    ny = new.index.tz_convert("America/New_York")
    m = ny.hour == 15                                   # bar 15:00-16:00 NY closes at the cash close
    n = pd.Series(new.close.values[m], index=ny[m].normalize().tz_localize(None))
    s = pd.concat([o, n])
    s = s[~s.index.duplicated()].sort_index()
    return s[s.index.dayofweek < 5]


def cost_frac(sym, price):
    return (FLOOR[sym] * 1.25) * float(pd.read_csv(D + f"{sym}_H1.csv", nrows=1).point.iloc[0]) / price


def per_year(r):
    g = r.groupby(r.index.year)
    return pd.DataFrame({"n": g.size(), "sum%": g.sum() * 100}).round(2)


def report(name, r, years_from=2001):
    r = r[r.index.year >= years_from].dropna()
    py = per_year(r)
    sh = r.mean() / r.std() * np.sqrt(len(r) / max(1, r.index.year.nunique())) if r.std() > 0 else 0
    def blk(a, b):
        x = r[(r.index.year >= a) & (r.index.year <= b)]
        return f"{x.sum()*100:+6.1f}% ({(per_year(x)['sum%']>0).sum()}/{x.index.year.nunique()}y)"
    print(f"{name:<34} n={len(r):5d} avg {r.mean()*1e4:+6.1f}bp  sharpe/yr {sh:4.2f}  "
          f"01-17 {blk(2001,2017)}  18-25 {blk(2018,2025)}  26 {blk(2026,2026)}")
    return py


def tom(sym):
    c = daily_us_close(load(sym))
    ym = c.index.to_period("M")
    pos = pd.Series(np.arange(len(c)), index=c.index)
    rank_end = c.groupby(ym).cumcount(ascending=False)     # 0 = last trading day
    rank_start = c.groupby(ym).cumcount()                  # 0 = first trading day
    entries = c.index[rank_end == 1]                       # close of 2nd-to-last day
    out = {}
    for e in entries:
        i = pos[e]
        nxt = c.index[(c.index > e)]
        m_next = (e.to_period("M") + 1)
        tgt = [d for d in nxt[:8] if d.to_period("M") == m_next and rank_start[d] == 2]
        if not tgt:
            continue
        x = tgt[0]
        nights = (x - e).days
        out[x] = c[x] / c[e] - 1 - cost_frac(sym, c[e]) - FIN * nights
    return pd.Series(out)


def rest_of_month(sym):
    """Comparison: same 4-day holds on all OTHER days (buy-and-hold drift per 4 days)."""
    c = daily_us_close(load(sym))
    r4 = c.shift(-4) / c - 1 - cost_frac(sym, c.iloc[-1]) - FIN * 6
    return r4.iloc[::4].dropna()


def overnight(sym, exit_hour=9):
    df = load(sym)
    df = df[df.index >= "2018-06-01"]
    ny = df.index.tz_convert("America/New_York")
    cl = pd.Series(df.close.values[ny.hour == 15], index=ny[ny.hour == 15].normalize())
    op = pd.Series(df.open.values[ny.hour == exit_hour], index=ny[ny.hour == exit_hour].normalize())
    out = {}
    days = cl.index
    for k in range(len(days) - 1):
        d0 = days[k]
        nxt = op[op.index > d0]
        if not len(nxt):
            break
        d1 = nxt.index[0]
        if (d1 - d0).days > 4:
            continue
        nights = 3 if d0.dayofweek == 4 else 1
        out[d1.tz_localize(None)] = nxt.iloc[0] / cl[d0] - 1 - cost_frac(sym, cl[d0]) - FIN * nights
    on = pd.Series(out)
    # intraday open(09:00 bar)->close(15:00 bar close) for comparison
    both = pd.concat([op.rename("o"), cl.rename("c")], axis=1).dropna()
    intr = (both.c / both.o - 1 - cost_frac(sym, both.o.iloc[-1]))
    intr.index = intr.index.tz_localize(None)
    return on, intr


def gold_sessions(sym="XAUUSD"):
    df = load(sym)
    df = df[df.index >= "2018-06-01"]
    r = np.log(df.close).diff()
    h = df.index.hour
    sess = pd.Series(np.select([(h >= 22) | (h < 7), h < 12, h < 17], ["asia 22-07", "london 07-12", "ny 12-17"],
                               "late 17-22"), index=df.index)
    t = pd.DataFrame({"r": r, "s": sess}).dropna()
    tab = t.groupby([t.index.year, "s"]).r.sum().unstack() * 100
    return tab.round(1)


FOMC_EXTRA = ["2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19", "2019-07-31", "2019-09-18",
              "2019-10-30", "2019-12-11", "2020-01-29", "2020-04-29", "2020-06-10", "2020-07-29",
              "2020-09-16", "2020-11-05", "2020-12-16", "2026-01-28", "2026-03-18", "2026-04-29",
              "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28"]


def pre_fomc(sym):
    cal = pd.read_csv("data/news/high_impact_2021_2025.csv", comment="#", header=None,
                      names=["time", "cur", "event"])
    t = pd.to_datetime(cal[cal.event == "FOMC rate decision"].time, utc=True).tolist()
    for d in FOMC_EXTRA:
        t.append(pd.Timestamp(d + " 14:00", tz="America/New_York").tz_convert("UTC"))
    df = load(sym)
    out = {}
    for T in sorted(t):
        a = df[(df.index >= T - pd.Timedelta(hours=25)) & (df.index < T - pd.Timedelta(hours=23))]
        b = df[(df.index >= T - pd.Timedelta(hours=1)) & (df.index < T)]
        if not len(a) or not len(b):
            continue
        px0, px1 = a.close.iloc[0], b.close.iloc[-1]
        out[T.tz_localize(None)] = px1 / px0 - 1 - cost_frac(sym, px0) - FIN
    return pd.Series(out)


def screen_main():
    pd.set_option("display.width", 200)
    idx = ["SPX500", "NAS100", "US30", "GER40", "UK100", "JPN225"]
    print("== Turn of month (enter close of 2nd-last day, exit close of 3rd day), vs other 4-day holds ==")
    for s in idx:
        report(f"TOM {s}", tom(s))
        report(f"  other days {s}", rest_of_month(s))
    print("\n== Overnight (US close -> 09:00 NY) vs intraday (09:00 -> 16:00), 2018-06.. ==")
    for s in idx + ["XAUUSD"]:
        on, intr = overnight(s)
        report(f"overnight {s}", on, 2018)
        report(f"  intraday {s}", intr, 2018)
    print("\n== Pre-FOMC drift (24h before the decision -> just before), 2019-2026 ==")
    for s in ["SPX500", "NAS100", "US30", "XAUUSD"]:
        report(f"pre-FOMC {s}", pre_fomc(s), 2019)
    print("\n== Gold log-return by UTC session, % per year ==")
    print(gold_sessions())


def month_end_and_fomc():
    
    # ---- pre-FOMC detail
    for s in ["NAS100", "SPX500"]:
        r = pre_fomc(s) * 1e4
        print(s, "per year mean bp:", r.groupby(r.index.year).mean().round(0).to_dict(),
              "| median", round(r.median(), 1), "| trimmed (drop best 5)", round(r.sort_values()[:-5].mean(), 1),
              "| hit", round((r > 0).mean() * 100), "%")
    
    # ---- month-end USD rebalancing
    COST = {"EURUSD": 1.4e-4 * 1.25, "GBPUSD": 2.0e-4 * 1.25, "USDJPY": 1.6e-2 * 1.25, "AUDUSD": 1.5e-4 * 1.25}
    us = daily_us_close(load("SPX500"))
    fo = pd.concat([daily_us_close(load(s)).rename(s) for s in ["GER40", "UK100", "JPN225"]], axis=1).ffill()
    idx = pd.concat([us.rename("US"), fo], axis=1).ffill().dropna()
    ym = idx.index.to_period("M")
    first = idx.groupby(ym).transform("first")  # not exactly prev month-end, use prev month last close:
    prev_last = idx.groupby(ym).last().shift(1)
    rows = []
    for m, g in idx.groupby(ym):
        if len(g) < 5 or m not in prev_last.index or prev_last.loc[m].isna().any():
            continue
        d_sig = g.index[-3]                       # decide at the US close 3 trading days before month end
        base = prev_last.loc[m]
        mtd = g.loc[d_sig] / base - 1
        diff = mtd["US"] - mtd[["GER40", "UK100", "JPN225"]].mean()
        rows.append((m, d_sig, g.index[-1], diff))
    sig = pd.DataFrame(rows, columns=["m", "d_sig", "d_last", "diff"])
    print(f"\nmonth-end signals: {len(sig)} months {sig.m.min()}..{sig.m.max()}")
    for fx in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]:
        df = load(fx)
        res = []
        for r in sig.itertuples():
            t0 = pd.Timestamp(r.d_sig).tz_localize("America/New_York") + pd.Timedelta(hours=16)
            t1 = pd.Timestamp(r.d_last).tz_localize("Europe/London") + pd.Timedelta(hours=16)
            a = df[df.index >= t0.tz_convert("UTC")].head(1)
            b = df[df.index < t1.tz_convert("UTC")].tail(1)
            if not len(a) or not len(b) or b.index[0] <= a.index[0]:
                continue
            p0, p1 = a.open.iloc[0], b.close.iloc[-1]
            usd_sell = 1 if r.diff > 0 else -1               # US outperformed -> USD sold into the fix
            side = usd_sell * (-1 if fx == "USDJPY" else 1)   # buy EURUSD / sell USDJPY when selling USD
            ret = side * (p1 / p0 - 1) - COST[fx] / p0
            res.append((r.m.year, ret, abs(r.diff)))
        x = pd.DataFrame(res, columns=["y", "r", "absdiff"])
        big = x[x.absdiff > x.absdiff.median()]
        py = x.groupby("y").r.sum() * 100
        print(f"{fx}: n={len(x)} avg {x.r.mean()*1e4:+.1f}bp hit {(x.r>0).mean()*100:.0f}% | big-gap months avg "
              f"{big.r.mean()*1e4:+.1f}bp | 2010-17 {x[x.y<2018].r.sum()*100:+.1f}% 2018-25 "
              f"{x[(x.y>=2018)&(x.y<2026)].r.sum()*100:+.1f}% 2026 {x[x.y==2026].r.sum()*100:+.1f}% | yrs+ {(py>0).sum()}/{len(py)}")


def gold_by_hour():
    df=pd.read_csv('data/mt5/XAUUSD_H1.csv',index_col=0); df.index=pd.to_datetime(df.index,utc=True)
    df=df[df.index>='2018-06-01']
    r=(df.close/df.open-1)*1e4   # bp within each hourly bar (open->close of same bar)
    t=pd.DataFrame({'r':r,'h':df.index.hour,'y':df.index.year,'spr':df.spread_pts*0.01/df.close*1e4})
    print("MT5 gold: mean bp per hour-bar by UTC hour (rows) and year")
    tab=t.groupby(['h','y']).r.mean().unstack().round(1)
    tab['spread_bp']=t.groupby('h').spr.median().round(1)
    tab['yrs+']=(tab.drop(columns='spread_bp')>0).sum(axis=1)
    print(tab)
    # independent source: histdata M1 2021-2025
    from run_validate import _bars
    b=_bars('data/XAUUSD_M1_histdata.csv','UTC','1h')
    rr=(b.close/b.open-1)*1e4
    u=pd.DataFrame({'r':rr,'h':b.index.hour,'y':b.index.year})
    tab2=u.groupby(['h','y']).r.mean().unstack().round(1); tab2['yrs+']=(tab2>0).sum(axis=1)
    print("\nhistdata gold 2021-25 (independent feed)"); print(tab2)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    screen_main()
    month_end_and_fomc()
    gold_by_hour()
