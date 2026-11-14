"""Trading the reaction to big news releases (research only).

    python fetch_mt5_extra.py            # 2026 five-minute bars
    python run_news_reaction.py

Rules fixed before the first run (Nov 13 2026):
  Events: data/news/high_impact_2021_2025.csv (NFP, US CPI, FOMC, ECB, BoE, UK CPI, EZ flash CPI)
    and for 2026 the US releases (NFP, CPI from the BLS archive; FOMC statements). Only the first
    event of the day per market (a press conference after its decision is skipped).
  Markets: USD news -> EURUSD, GBPUSD, USDJPY, gold. EUR news -> EURUSD. GBP news -> GBPUSD.
  Reaction = price 15 minutes after the release minus the price just before it.
  If the reaction is at least 0.2 x the market's average daily range (20 days):
    FOLLOW: trade in the reaction's direction at the next bar; stop = the pre-release price.
    FADE:   trade against it; stop = the most extreme price of those 15 minutes.
  Stop to breakeven at +1R; everything closes 4 hours after the release.
  Costs: double the normal spread (spreads stay wide after news) + half a spread of slippage
    on each fill. 5-minute bars: 2021-2025 from histdata M1, 2026 from the broker.
  Pass: profit factor >= 1.15 over 2021-2025, up in >= 4 of 5 years, 2026 not losing.
  (0.1 and 0.3 x daily range shown as a check, not used to pick.)
"""
import numpy as np
import pandas as pd

MARKETS = {  # normal spread (price units), 2021-25 file, 2026 file
    "EURUSD": (0.00014, "data/EURUSD_M1_histdata.csv", "data/mt5/EURUSD_M5_2026.csv"),
    "GBPUSD": (0.00020, "data/GBPUSD_M1_histdata.csv", "data/mt5/GBPUSD_M5_2026.csv"),
    "USDJPY": (0.016, "data/USDJPY_M1_histdata.csv", "data/mt5/USDJPY_M5_2026.csv"),
    "XAUUSD": (0.80, "data/XAUUSD_M1_histdata.csv", "data/mt5/XAUUSD_M5_2026.csv"),
}
WHO = {"USD": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"], "EUR": ["EURUSD"], "GBP": ["GBPUSD"]}

NFP_2026 = ["2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05", "2026-07-02",
            "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06"]
CPI_2026 = ["2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10",
            "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10"]
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16",
             "2026-10-28"]


def events():
    e = pd.read_csv("data/news/high_impact_2021_2025.csv", comment="#")
    e["time"] = pd.to_datetime(e.time, utc=True)
    ny = lambda d, hm: pd.Timestamp(f"{d} {hm}", tz="America/New_York").tz_convert("UTC")
    add = ([(ny(d, "08:30"), "USD", "US Non-Farm Payrolls") for d in NFP_2026]
           + [(ny(d, "08:30"), "USD", "US CPI") for d in CPI_2026]
           + [(ny(d, "14:00"), "USD", "FOMC rate decision") for d in FOMC_2026])
    e = pd.concat([e, pd.DataFrame(add, columns=["time", "currency", "event"])], ignore_index=True)
    return e.sort_values("time")


def bars(sym):
    _, f1, f2 = MARKETS[sym]
    a = pd.read_csv(f1, index_col=0)
    a.index = pd.to_datetime(a.index, utc=True)
    a = a.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    b = pd.read_csv(f2, index_col=0)
    b.index = pd.to_datetime(b.index, utc=True)
    b = b[b.index >= "2026-01-01"][["open", "high", "low", "close"]]
    return pd.concat([a[a.index < "2026-01-01"], b]).sort_index()


def daily_atr(m5):
    d = m5.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(20).mean().shift(1)          # known before the day starts


def simulate(sym, m5, atr, ev, th, mode):
    spread = MARKETS[sym][0]
    cost = 2 * spread + 2 * 0.5 * spread
    idx = m5.index
    out = []
    for t in ev:
        k0 = idx.searchsorted(t - pd.Timedelta(minutes=5))       # bar ending at the release
        if k0 >= len(idx) or idx[k0] != t - pd.Timedelta(minutes=5):
            continue
        k15 = k0 + 3                                              # bar ending 15 min after
        if k15 + 1 >= len(idx) or idx[k15] != t + pd.Timedelta(minutes=10):
            continue
        a = atr.get(t.normalize(), np.nan)
        if not np.isfinite(a):
            continue
        p0, p15 = m5.close.iloc[k0], m5.close.iloc[k15]
        move = p15 - p0
        if abs(move) < th * a:
            continue
        side = int(np.sign(move)) * (1 if mode == "follow" else -1)
        e = m5.open.iloc[k15 + 1]
        win = m5.iloc[k0 + 1:k15 + 1]
        if mode == "follow":
            stop = p0
        else:
            stop = win.high.max() if side < 0 else win.low.min()
        risk = side * (e - stop)
        if risk <= 0:
            continue
        end = t + pd.Timedelta(hours=4)
        be = False
        exit_ = None
        for j in range(k15 + 1, len(idx)):
            row = m5.iloc[j]
            if idx[j] >= end:
                exit_ = row.open
                break
            st = e if be else stop
            if (side > 0 and row.low <= st) or (side < 0 and row.high >= st):
                exit_ = st
                break
            if side * (row.close - e) >= risk:
                be = True
        if exit_ is None:
            continue
        out.append(dict(sym=sym, time=t, side=side, R=(side * (exit_ - e) - cost) / risk))
    return out


def main():
    E = events()
    first = E.copy()
    rows = []
    data = {s: bars(s) for s in MARKETS}
    atrs = {s: daily_atr(data[s]) for s in MARKETS}
    T = []
    for s in MARKETS:
        mine = E[E.currency.map(lambda c: s in WHO.get(c, []))]
        mine = mine.groupby(mine.time.dt.date).head(1)            # first event of the day
        for th in (0.1, 0.2, 0.3):
            for mode in ("follow", "fade"):
                for r in simulate(s, data[s], atrs[s], list(mine.time), th, mode):
                    T.append(dict(r, th=th, mode=mode))
    T = pd.DataFrame(T)
    T["y"] = T.time.dt.year
    pf = lambda x: x[x > 0].sum() / -x[x <= 0].sum() if (x <= 0).any() else np.inf
    for (th, mode), g in T.groupby(["th", "mode"]):
        ins, oos = g[g.y <= 2025], g[g.y >= 2026]
        yrs = ins.groupby("y").R.sum()
        r = dict(threshold=th, mode=mode, trades_yr=round(len(ins) / 5, 1), win=round((ins.R > 0).mean() * 100),
                 avgR=round(ins.R.mean(), 3), pf=round(pf(ins.R), 2), totR=round(ins.R.sum(), 1),
                 yrs_up=f"{(yrs > 0).sum()}/5", by_year=yrs.round(1).to_dict(),
                 n26=len(oos), R26=round(oos.R.sum(), 1))
        r["pass"] = bool(th == 0.2 and r["pf"] >= 1.15 and (yrs > 0).sum() >= 4 and r["R26"] >= 0)
        rows.append(r)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 80)
    print(pd.DataFrame(rows).to_string(index=False))
    g = T[T.th == 0.2]
    print("\nBy market at 0.2 (total R 2021-25 | 2026):")
    print(g.assign(p=np.where(g.y >= 2026, "2026", "21_25")).pivot_table(
        index="sym", columns=["mode", "p"], values="R", aggfunc="sum").round(1).to_string())
    T.to_csv("results/news_reaction_trades.csv", index=False)


if __name__ == "__main__":
    main()
