"""Stock-specific strategies on big US companies (CFDs on the same account), research only.

    python fetch_mt5_stocks.py        # once
    python run_stock_edges.py

Rules fixed before the first run (Nov 13 2026), nothing tuned afterwards:
  Timing: decisions use the price at 15:00 New York (the bot can see that), orders fill at the
    16:00 close. Day high/low for a decision = high/low up to 15:00.
  S1 Dip (RSI-2): price above its 200-day average and 2-day RSI < 10 -> buy. Sell when price is
    above its 5-day average, or after 10 days.
  S2 Weak close (IBS): above the 200-day average and the day closes in the bottom 20% of its
    range -> buy. Sell when price is above yesterday's high, or after 10 days.
  S3 Gap follow-through: the day opens >4% away from yesterday's close (earnings / big news) and
    holds that side (upper/lower half of the day's range) -> go that way, hold 20 days.
    Buy side and short side reported separately.
  S4 Pairs: log(A) - log(B) more than 2 standard deviations (60 days) from its 60-day mean ->
    short the expensive one, buy the cheap one (equal money). Out when the gap closes (back
    through the mean) or after 20 days.
  Costs: 0.08% per side per stock (commission, slippage, spread) + CFD financing 7%/yr on buys,
    1.5%/yr on shorts.
  Lists: today's 12 biggest companies and 2013's 14 biggest (the honest list). Pairs: 7 pairs.
  Pass: profit factor >= 1.15 over 2013-2025, profitable in >= 70% of years, 2026 not losing,
    on BOTH lists (pairs: on the pair set).
Money: each trade uses 25% of the account (pairs: 25% per side), at most 4 at once = no leverage.
"""
import numpy as np
import pandas as pd

from fetch_mt5_stocks import PAIR_EXTRA, TOP_2013, TOP_NOW, fname
from run_stocks import load

COMM = 0.0008
FIN_L, FIN_S = 0.07 / 365, 0.015 / 365
SIZE, MAXPOS = 0.25, 4
PAIRS = [("Visa", "Mastercard"), ("Coca Cola Co", "PepsiCo"), ("Exxon Mobil", "Chevron Corp"),
         ("J.P. Morgan", "Bank Of America"), ("Goldman Sachs", "Morgan Stanley"),
         ("Walmart", "Costco"), ("Pfizer", "Merck and Co")]


def daily(name):
    """One row per New York trading day: open, decision price (15:00), high/low to 15:00,
    close (16:00), full-day high/low."""
    b = load(name)
    ny = b.index.tz_convert("America/New_York")
    b = b.assign(day=ny.normalize().tz_localize(None), hr=ny.hour)
    rows = {}
    for d, g in b.groupby("day"):
        early = g[g.hr < 15]                       # bars that have finished by 15:00
        last = g[g.hr == 15]                       # the 15:00-16:00 bar
        if not len(early) or not len(last):
            continue
        rows[d] = dict(open=g.open.iloc[0], dec=early.close.iloc[-1], hi15=early.high.max(),
                       lo15=early.low.min(), close=last.close.iloc[-1], high=g.high.max(), low=g.low.min())
    df = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    df["gapday"] = df.index.to_series().diff().dt.days <= 4      # previous day is a normal day
    return df


def rsi2_today(c, dec):
    """2-day Wilder RSI where today's value uses the 15:00 price."""
    ch = c.diff()
    up, dn = ch.clip(lower=0), (-ch).clip(lower=0)
    au, ad = up.ewm(alpha=0.5, adjust=False).mean(), dn.ewm(alpha=0.5, adjust=False).mean()
    t = dec - c.shift(1)
    au_t = 0.5 * au.shift(1) + 0.5 * t.clip(lower=0)
    ad_t = 0.5 * ad.shift(1) + 0.5 * (-t).clip(lower=0)
    return 100 - 100 / (1 + au_t / ad_t.replace(0, np.nan))


def ret(entry, exit_, side, days):
    gross = side * (exit_ / entry - 1)
    return gross - 2 * COMM - (FIN_L if side > 0 else FIN_S) * days


def single_stock(name, d):
    c, p = d.close, d.dec
    sma200 = c.rolling(200).mean().shift(1)
    sma5 = (c.rolling(4).sum().shift(1) + p) / 5
    rsi = rsi2_today(c, p)
    ibs = (p - d.lo15) / (d.hi15 - d.lo15).replace(0, np.nan)
    idx = list(d.index)
    out = []

    def run(tag, entry_sig, exit_fn, hold, side_fn=lambda i: 1):
        i = 200
        while i < len(idx) - 1:
            side = entry_sig(i)
            if not side:
                i += 1
                continue
            j = i + 1
            while j < len(idx) - 1 and j - i < hold and not exit_fn(i, j, side):
                j += 1
            out.append(dict(stock=name, strategy=tag, side=side, entry=idx[i], exit=idx[j],
                            ret=ret(c.iloc[i], c.iloc[j], side, (idx[j] - idx[i]).days)))
            i = j + 1

    run("S1 dip RSI-2",
        lambda i: 1 if p.iloc[i] > sma200.iloc[i] and rsi.iloc[i] < 10 else 0,
        lambda i, j, s: p.iloc[j] > sma5.iloc[j], 10)
    run("S2 weak close IBS",
        lambda i: 1 if p.iloc[i] > sma200.iloc[i] and ibs.iloc[i] < 0.2 else 0,
        lambda i, j, s: p.iloc[j] > d.high.iloc[j - 1], 10)
    gap = d.open / c.shift(1) - 1
    mid = (d.hi15 + d.lo15) / 2
    for side, tag in ((1, "S3 gap buy"), (-1, "S3 gap short")):
        run(tag,
            lambda i, s=side: s if d.gapday.iloc[i] and s * gap.iloc[i] > 0.04 and s * (p.iloc[i] - mid.iloc[i]) > 0 else 0,
            lambda i, j, s: False, 20)
    return out


def pair_trades(a, b, da, db):
    j = da[["close", "dec"]].join(db[["close", "dec"]], lsuffix="_a", rsuffix="_b", how="inner")
    spread = np.log(j.close_a) - np.log(j.close_b)
    now = np.log(j.dec_a) - np.log(j.dec_b)
    mu, sd = spread.rolling(60).mean().shift(1), spread.rolling(60).std().shift(1)
    z = (now - mu) / sd
    idx = list(j.index)
    out, i = [], 60
    while i < len(idx) - 1:
        if not abs(z.iloc[i]) > 2:
            i += 1
            continue
        s = -np.sign(z.iloc[i])            # +1: buy A / short B (A cheap)
        k = i + 1
        while k < len(idx) - 1 and k - i < 20 and np.sign(z.iloc[k]) != np.sign(z.iloc[i]) * -1 and z.iloc[k] * np.sign(z.iloc[i]) > 0:
            k += 1
        days = (idx[k] - idx[i]).days
        ra = ret(j.close_a.iloc[i], j.close_a.iloc[k], s, days)
        rb = ret(j.close_b.iloc[i], j.close_b.iloc[k], -s, days)
        out.append(dict(stock=f"{a}/{b}", strategy="S4 pairs", side=int(s), entry=idx[i], exit=idx[k],
                        ret=(ra + rb) / 2))    # per unit of money in each side, averaged
        i = k + 1
    return out


def portfolio_years(t, per_side=1):
    """Take trades in time order, at most MAXPOS at once, each SIZE of the account (simple, no
    compounding). Returns % made per year."""
    t = t.sort_values(["entry", "stock"])
    open_, took = [], []
    for r in t.itertuples():
        open_ = [x for x in open_ if x > r.entry]
        if len(open_) >= MAXPOS:
            continue
        open_.append(r.exit)
        took.append(r)
    k = pd.DataFrame(took)
    gain = k.ret * SIZE * per_side
    return gain.groupby(pd.to_datetime(k.exit).dt.year).sum() * 100, len(k)


def score(label, strat, t, per_side=1):
    t = t[pd.to_datetime(t.entry) >= "2013-06-01"]
    ins, oos = t[pd.to_datetime(t.entry).dt.year <= 2025], t[pd.to_datetime(t.entry).dt.year >= 2026]
    pf = lambda x: x[x > 0].sum() / -x[x <= 0].sum() if (x <= 0).any() else np.inf
    yrs = ins.groupby(pd.to_datetime(ins.entry).dt.year).ret.sum()
    port, n = portfolio_years(t, per_side)
    p_in = port[port.index <= 2025]
    r = dict(list=label, strategy=strat, trades_yr=round(len(ins) / max(1, yrs.size), 1),
             avg_pct=round(ins.ret.mean() * 100, 3), win=round((ins.ret > 0).mean() * 100),
             pf=round(pf(ins.ret), 2), yrs_up=f"{(yrs > 0).sum()}/{yrs.size}",
             acct_pct_yr=round(p_in.mean(), 1), worst_yr=round(p_in.min(), 1),
             y2026_acct_pct=round(port.get(2026, 0.0), 1), n26=len(oos))
    r["pass"] = bool(r["pf"] >= 1.15 and (yrs > 0).sum() >= 0.7 * yrs.size and r["y2026_acct_pct"] >= 0)
    return r


def main():
    pd.set_option("display.width", 250)
    names = list(dict.fromkeys(TOP_NOW + TOP_2013 + PAIR_EXTRA))
    D = {n: daily(n) for n in names}
    rows = []
    T = pd.DataFrame([x for n in dict.fromkeys(TOP_NOW + TOP_2013) for x in single_stock(n, D[n])])
    for label, lst in (("today's top 12", TOP_NOW), ("2013's top 14", TOP_2013)):
        for s in T.strategy.unique():
            rows.append(score(label, s, T[(T.strategy == s) & T.stock.isin(lst)]))
        # what simply holding the list (equal money, as CFDs and as shares) made per year
        c = pd.DataFrame({n: D[n].close for n in lst})
        yr = c.resample("YE").last().pct_change(fill_method=None).mean(axis=1)
        yr = yr[(yr.index.year >= 2014) & (yr.index.year <= 2025)]
        print(f"hold {label}: shares {yr.mean()*100:+.1f}%/yr, as CFDs ~{(yr.mean()-0.07)*100:+.1f}%/yr")
    P = pd.DataFrame([x for a, b in PAIRS for x in pair_trades(a, b, D[a], D[b])])
    rows.append(score("7 pairs", "S4 pairs", P, per_side=2))
    print("\nacct_pct_yr = average % the account makes per year at 25% per trade, max 4 at once (no leverage)")
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nPairs, per pair (avg % per trade 2013-25, trades, 2026 trades):")
    P["y"] = pd.to_datetime(P.entry).dt.year
    print(P.groupby("stock").apply(lambda g: pd.Series({
        "avg%": round(g[g.y <= 2025].ret.mean() * 100, 3), "n": int((g.y <= 2025).sum()),
        "avg%26": round(g[g.y >= 2026].ret.mean() * 100, 3), "n26": int((g.y >= 2026).sum())}),
        include_groups=False).to_string())
    pd.concat([T, P.drop(columns="y")]).to_csv("results/stock_edges_trades.csv", index=False)


if __name__ == "__main__":
    main()
