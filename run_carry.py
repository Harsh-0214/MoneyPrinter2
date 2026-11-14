"""Carry trade research: hold high-interest currencies against low-interest ones.

    python fetch_cot.py / fetch_mt5_extra.py      # daily prices in data/cot/
    (3-month interbank rates from the OECD into data/rates/oecd.csv, see RESEARCH_LOG)
    python run_carry.py

Rules fixed before the first run (Nov 13 2026):
  Currencies: USD EUR GBP JPY AUD NZD CAD CHF (prices = the broker's daily history).
  Each month (first trading day): rank by last month's 3-month interest rate; buy the 3 highest,
    short the 3 lowest, equal money (1/3 each side). Earn price change + the rate difference.
  Broker cut: the broker keeps part of the interest. Judged at 1.5%/yr per position (also shown
    at 0% and 3%). Trading cost 0.02% of money moved at each monthly change.
  V2 crash filter: skip the month (flat) if the basket lost money over the previous 3 months.
  Pass: Sharpe >= 0.5 over 2007-2025, up in >= 12 of 19 years, 2026 not losing.
"""
import numpy as np
import pandas as pd

CCY = {"USA": "USD", "EA20": "EUR", "GBR": "GBP", "JPN": "JPY", "AUS": "AUD", "NZL": "NZD",
       "CAN": "CAD", "CHE": "CHF"}
INVERSE = {"JPY", "CAD", "CHF"}          # files hold USDJPY / USDCAD / USDCHF
TC = 0.0002


def rates():
    d = pd.read_csv("data/rates/oecd.csv")
    p = d.pivot_table(index="TIME_PERIOD", columns="REF_AREA", values="OBS_VALUE").rename(columns=CCY)
    p.index = pd.PeriodIndex(p.index, freq="M")
    return p.ffill()


def ccy_returns():
    out = {}
    for c in ["EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]:
        p = pd.read_csv(f"data/cot/{c}_D1.csv", index_col=0, parse_dates=True).close
        p = p[p.index.dayofweek < 5].copy()
        v = 1 / p if c in INVERSE else p                     # value of 1 unit in USD
        out[c] = v
    v = pd.DataFrame(out)
    v = v[v.index >= "2006-01-01"]
    # the broker's daily files have holes (EUR 2021, NZD 2020, CAD 2015, JPY/AUD/CHF most of 2025):
    # a currency with fewer than 15 days in a month is left out of that month's ranking
    have = v.notna().groupby(v.index.to_period("M")).sum() >= 15
    r = v.ffill(limit=5).pct_change(fill_method=None).fillna(0.0)
    r["USD"] = 0.0
    have["USD"] = True
    return r, have


def run(r, R, markup, crash_filter=False, have=None):
    days = r.index.to_series().diff().dt.days.fillna(1).values
    month = r.index.to_period("M")
    w = pd.Series(0.0, index=r.columns)
    out = np.zeros(len(r))
    hist = []                       # monthly returns of the unfiltered basket (for the filter)
    cur_m, raw_m, live = None, 0.0, True
    for k, (t, m) in enumerate(zip(r.index, month)):
        if m != cur_m:                                       # new month: rebalance
            if cur_m is not None:
                hist.append(raw_m)
            raw_m = 0.0
            ok = have.loc[m]
            rk = R.loc[m - 1].reindex([c for c in r.columns if ok.get(c, False)]).dropna().sort_values()
            new = pd.Series(0.0, index=r.columns)
            new[rk.index[-3:]] = 1 / 3
            new[rk.index[:3]] = -1 / 3
            live = not (crash_filter and len(hist) >= 3 and sum(hist[-3:]) < 0)
            tgt = new if live else new * 0
            out[k] -= TC * (tgt - w).drop("USD").abs().sum()
            w, base, cur_m = tgt, new, m
            rate_today = R.loc[m - 1]
        carry = (base * rate_today.reindex(base.index).fillna(0)).sum() / 100 / 365 * days[k]
        cost = markup / 100 / 365 * days[k] * base.drop("USD").abs().sum()
        raw = (base * r.iloc[k]).sum() + carry - cost
        raw_m += raw
        out[k] += raw if live else 0.0
    return pd.Series(out, index=r.index)


def stats(x, label):
    yrs = x.groupby(x.index.year).apply(lambda g: (1 + g).prod() - 1)
    ins = x[(x.index.year >= 2007) & (x.index.year <= 2025)]
    yi = yrs[(yrs.index >= 2007) & (yrs.index <= 2025)]
    sh = ins.mean() / ins.std() * np.sqrt(252)
    e = (1 + ins).cumprod()
    dd = (e / e.cummax() - 1).min()
    vol = ins.std() * np.sqrt(252)
    cagr = e.iloc[-1] ** (252 / len(ins)) - 1
    y26 = yrs.get(2026, 0.0)
    ok = sh >= 0.5 and (yi > 0).sum() >= 12 and y26 >= 0
    print(f"  {label:<38} {cagr*100:+5.1f}%/yr  vol {vol*100:4.1f}%  Sharpe {sh:4.2f}  worst drop {dd*100:5.1f}%  "
          f"years up {(yi > 0).sum()}/{len(yi)}  2026 {y26*100:+5.1f}%  {'PASS' if ok else ''}")
    return yrs


def main():
    R, (r, have) = rates(), ccy_returns()
    print("Which currencies it held (share of months, 2007-2026):")
    m = r.index.to_period("M").unique()
    longs, shorts = {}, {}
    for p in m:
        rk = R.loc[p - 1].reindex([c for c in r.columns if have.loc[p].get(c, False)]).dropna().sort_values()
        for c in rk.index[-3:]:
            longs[c] = longs.get(c, 0) + 1
        for c in rk.index[:3]:
            shorts[c] = shorts.get(c, 0) + 1
    print("  bought:", {k: f"{v / len(m):.0%}" for k, v in sorted(longs.items(), key=lambda x: -x[1])})
    print("  shorted:", {k: f"{v / len(m):.0%}" for k, v in sorted(shorts.items(), key=lambda x: -x[1])})
    print("\nNo leverage (1x each side):")
    res = {}
    for mk in (0.0, 1.5, 3.0):
        res[("V1", mk)] = run(r, R, mk, have=have)
        stats(res[("V1", mk)], f"V1 carry, broker cut {mk}%/yr")
    for mk in (0.0, 1.5, 3.0):
        res[("V2", mk)] = run(r, R, mk, crash_filter=True, have=have)
        stats(res[("V2", mk)], f"V2 + crash filter, cut {mk}%/yr")
    print("\nV1 (1.5% cut) by year, %:")
    y = res[("V1", 1.5)].groupby(res[("V1", 1.5)].index.year).apply(lambda g: (1 + g).prod() - 1) * 100
    print("  " + "  ".join(f"{k}:{v:+.0f}" for k, v in y.round(0).items()))
    # correlation with the bot's live strategies (monthly R, 2021-2026)
    try:
        t = pd.concat([pd.read_csv(f"results/portfolio_trades_{s}.csv", parse_dates=["entry_time"])
                       for s in ("hist", "mt5")])
        t = t[t.entry_time >= "2021-01-01"]
        bot = t.groupby(t.entry_time.dt.to_period("M")).r_multiple.sum()
        c = res[("V1", 1.5)]
        cm = c.groupby(c.index.to_period("M")).sum()
        j = pd.concat([bot, cm], axis=1, join="inner")
        print(f"\nCorrelation with the bot's monthly results 2021-2026: {j.corr().iloc[0, 1]:+.2f}")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
