"""Decision system: pick which strategy to use from the conditions before each trade, judged walk-forward.

    python make_arsenal_trades.py     # once: every trade of every arsenal strategy (2021-25)
    python run_selector.py

The arsenal = 48 tested strategies x 5 markets (results/arsenal_trades.csv) + the 8 live units
(results/portfolio_trades_hist.csv, live settings). For every trade, the conditions BEFORE entry,
from completed daily bars of that market only:
    volatility: the 20-day average daily range, ranked against the previous 250 days -> calm / normal / wild
    trend:      (yesterday's close - 50-day average) / 20-day ATR, signed by the trade's direction ->
                against (< -0.5), flat (-0.5 .. 0.5), with (> 0.5)
    form:       that strategy's own result on that market over the previous 12 months (R)

Selectors (rules fixed before the run). Each test year Y in 2022-2025 is decided ONLY from years < Y:
    S1 conditions:  take a strategy-market's trades only in (volatility, trend) conditions where, in the
                    training years, it had >= 20 trades, average >= +0.05R and t-statistic >= 1.0
    S2 strategy:    the same test on the strategy-market as a whole (no conditions) - shows what the
                    conditions add
    S3 form:        take a trade only if its strategy-market made money over the previous 12 months
Benchmarks: the live units as they are; live units + the S1 trades of the other strategies (does the
decision system add profit on top of today's bot?). Scored in R per year at 1% risk per trade,
summed (no account limits); 2022-25 are all unseen by the selector that traded them.
"""
import numpy as np
import pandas as pd

LIVE_UNITS = {"EURUSD", "GBPUSD", "GBPUSD:pullback", "XAUUSD", "XAUUSD:fast", "XAUUSD:add55",
              "XAUUSD:add20", "USDJPY"}
DAILY_SRC = {"EURUSD": "data/EURUSD_M1_histdata.csv", "GBPUSD": "data/GBPUSD_M1_histdata.csv",
             "AUDUSD": "data/AUDUSD_M1_histdata.csv", "XAUUSD": "data/XAUUSD_M1_histdata.csv",
             "USDJPY": "data/USDJPY_M1_histdata.csv"}
YEARS = [2022, 2023, 2024, 2025]


def load_trades():
    a = pd.read_csv("results/arsenal_trades.csv")
    live = pd.read_csv("results/portfolio_trades_hist.csv")
    live = live.rename(columns={"unit": "strategy"})
    live["strategy"] = "LIVE " + live["strategy"]
    t = pd.concat([a[["strategy", "market", "entry_time", "exit_time", "side", "r_multiple"]],
                   live[["strategy", "market", "entry_time", "exit_time", "side", "r_multiple"]]],
                  ignore_index=True)
    for c in ("entry_time", "exit_time"):
        t[c] = pd.to_datetime(t[c], utc=True)
    t = t[(t.entry_time >= "2021-01-01") & (t.entry_time < "2026-01-01")].reset_index(drop=True)
    t["live"] = t.strategy.str.startswith("LIVE ")
    t["year"] = t.entry_time.dt.year
    return t


def conditions(t):
    from run_validate import _bars
    feats = []
    for mk, g in t.groupby("market"):
        d = _bars(DAILY_SRC[mk], "UTC", "1h").resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        rng = (d.high - d.low)
        atr20 = rng.rolling(20).mean()
        volp = atr20.rolling(250, min_periods=120).rank(pct=True)
        trend = (d.close - d.close.ewm(span=50, adjust=False).mean()) / atr20
        f = pd.DataFrame({"volp": volp, "trend": trend}).shift(1)      # known before the day starts
        idx = f.index.searchsorted(g.entry_time.dt.floor("D"), side="right") - 1
        idx = np.clip(idx, 0, len(f) - 1)
        part = f.iloc[idx].reset_index(drop=True)
        part.index = g.index
        feats.append(part)
    f = pd.concat(feats).sort_index()
    t = t.join(f)
    t["vol"] = pd.cut(t.volp, [-1, 1 / 3, 2 / 3, 2], labels=["calm", "normal", "wild"]).astype(str)
    tw = t.trend * t.side
    t["trend_c"] = np.where(tw < -0.5, "against", np.where(tw > 0.5, "with", "flat"))
    # form: same strategy-market, trades CLOSED in the 365 days before this entry
    t = t.sort_values("entry_time").reset_index(drop=True)
    form = np.full(len(t), np.nan)
    for _, g in t.groupby(["strategy", "market"]):
        ex = g.exit_time.to_numpy()
        r = g.r_multiple.to_numpy()
        for j, (i, et) in enumerate(zip(g.index, g.entry_time.to_numpy())):
            m = (ex < et) & (ex >= et - np.timedelta64(365, "D"))
            form[i] = r[m].sum() if m.any() else np.nan
    t["form"] = form
    return t


def _good(r, n_min, mean_min=0.05, t_min=1.0):
    if len(r) < n_min:
        return False
    m, s = r.mean(), r.std(ddof=1)
    return m >= mean_min and s > 0 and m / (s / np.sqrt(len(r))) >= t_min


def select(t):
    rows, picks = [], {}
    for y in YEARS:
        train, test = t[t.year < y], t[t.year == y]
        ok1 = {k for k, g in train.groupby(["strategy", "market", "vol", "trend_c"]) if _good(g.r_multiple, 20)}
        ok2 = {k for k, g in train.groupby(["strategy", "market"]) if _good(g.r_multiple, 30)}
        s1 = test[[k in ok1 for k in zip(test.strategy, test.market, test.vol, test.trend_c)]]
        s2 = test[[k in ok2 for k in zip(test.strategy, test.market)]]
        s3 = test[test.form > 0]
        live = test[test.live]
        live_plus = pd.concat([live, s1[~s1.live]])
        live_filtered = s1[s1.live]
        for name, d in [("live bot as it is", live), ("live bot, only in its good conditions (S1)", live_filtered),
                        ("S1 conditions, whole arsenal", s1), ("S2 strategy, whole arsenal", s2),
                        ("S3 form, whole arsenal", s3), ("live bot + S1 picks from the rest", live_plus),
                        ("everything (no selection)", test)]:
            rows.append(dict(year=y, selector=name, trades=len(d), R=round(d.r_multiple.sum(), 1),
                             avgR=round(d.r_multiple.mean(), 3) if len(d) else 0.0,
                             strategies=d.groupby(["strategy", "market"]).ngroups))
        picks[y] = s1[~s1.live].groupby(["strategy", "market"]).r_multiple.agg(["size", "sum"]).round(1)
    return pd.DataFrame(rows), picks


def main():
    t = conditions(load_trades())
    print(f"{len(t)} trades, {t.groupby(['strategy', 'market']).ngroups} strategy-market pairs\n")
    res, picks = select(t)
    res.to_csv("results/selector.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    piv = res.pivot(index="selector", columns="year", values="R")
    piv["total 2022-25"] = piv.sum(axis=1)
    piv["years up"] = (res.pivot(index="selector", columns="year", values="R") > 0).sum(axis=1)
    tr = res.pivot(index="selector", columns="year", values="trades").sum(axis=1)
    piv["trades/yr"] = (tr / len(YEARS)).round(0)
    print("R per unseen year (1% risk per trade, summed):")
    print(piv.sort_values("total 2022-25", ascending=False).to_string())
    for y, p in picks.items():
        print(f"\n{y}: non-live strategy-markets picked by S1 (trades, R in that year), top 8 by trades:")
        print(p.sort_values("size", ascending=False).head(8).to_string())
    print("\nLive units by condition, all years (trades, avg R):")
    lv = t[t.live]
    print(lv.groupby(["vol", "trend_c"]).r_multiple.agg(["size", "mean"]).round(2).unstack().to_string())


if __name__ == "__main__":
    main()
