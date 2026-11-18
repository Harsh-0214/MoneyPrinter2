"""Cross-sectional currency momentum: buy the strongest currencies, sell the weakest, monthly.

    python run_fx_momentum.py

Nine currencies against the dollar (EUR GBP JPY AUD NZD CAD CHF NOK SEK; broker daily closes,
1993 - Nov 2026). At each month end, rank them by their return over the last L months (L = 1, 3,
6, 12), hold the top K long and bottom K short (K = 2 or 3; equal weight) for the next month.
P/L per month = average long-leg return - average short-leg return, on 1x per side (account-size
independent). Cost: each rebalanced leg pays the broker's current spread (x2 to be safe).
Financing (swap) NOT included: the demo shows 0, real accounts charge it and momentum often holds
high-carry currencies long, so this is optimistic on that side.
Pass (fixed before the run): PF of monthly P/L >= 1.15 over 2021-25 with >= 4 of 5 years up,
2026 not negative, AND positive over 1994-2010 and 2011-20 (the long history the bot never saw).
"""
import numpy as np
import pandas as pd

LEGS = {"EUR": ("EURUSD.", 1), "GBP": ("GBPUSD.", 1), "AUD": ("AUDUSD.", 1), "NZD": ("NZDUSD.", 1),
        "JPY": ("USDJPY.", -1), "CAD": ("USDCAD.", -1), "CHF": ("USDCHF.", -1), "NOK": ("USDNOK.", -1),
        "SEK": ("USDSEK.", -1)}


def load():
    import MetaTrader5 as mt5
    mt5.initialize()
    px, cost = {}, {}
    for ccy, (sym, sign) in LEGS.items():
        mt5.symbol_select(sym, True)
        r = pd.DataFrame(mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 9000))
        i = mt5.symbol_info(sym)
        s = pd.Series(r.close.values, index=pd.to_datetime(r.time, unit="s"))
        px[ccy] = s if sign == 1 else 1 / s                   # value of 1 unit of ccy in USD
        cost[ccy] = 2 * i.spread * i.point / float(s.iloc[-1])  # 2x current spread, as a fraction
    mt5.shutdown()
    return pd.DataFrame(px).sort_index(), pd.Series(cost)


def backtest(px, cost, L, K):
    m = px.resample("ME").last()
    ret = m.pct_change()
    past = m / m.shift(L) - 1
    rows, prev_long, prev_short = [], set(), set()
    for t in range(L + 1, len(m)):
        sig = past.iloc[t - 1].dropna()
        if len(sig) < 2 * K + 1:
            continue
        rank = sig.sort_values()
        longs, shorts = set(rank.index[-K:]), set(rank.index[:K])
        r = ret.iloc[t]
        pnl = r[list(longs)].mean() - r[list(shorts)].mean()
        changed = (longs ^ prev_long) | (shorts ^ prev_short)
        pnl -= sum(cost[c] for c in changed) / K / 2         # each changed leg: spread on its 1/K slice
        rows.append((m.index[t], pnl))
        prev_long, prev_short = longs, shorts
    return pd.Series(dict(rows))


def summarize(s):
    def pf(x):
        return round(x[x > 0].sum() / -x[x < 0].sum(), 2) if (x < 0).any() else np.inf
    out = {}
    for name, a, b in (("1994-2010", 1994, 2010), ("2011-20", 2011, 2020), ("2021-25", 2021, 2025), ("2026", 2026, 2026)):
        x = s[(s.index.year >= a) & (s.index.year <= b)]
        out[f"{name} %/yr"] = round(x.mean() * 1200, 1) if len(x) else np.nan
        out[f"{name} PF"] = pf(x) if len(x) else np.nan
    h = s[(s.index.year >= 2021) & (s.index.year <= 2025)]
    out["yrs up 21-25"] = int((h.groupby(h.index.year).sum() > 0).sum())
    out["sharpe all"] = round(s.mean() / s.std() * np.sqrt(12), 2)
    out["PASS"] = bool(out["2021-25 PF"] >= 1.15 and out["yrs up 21-25"] >= 4 and out["2026 %/yr"] >= 0
                       and out["1994-2010 %/yr"] > 0 and out["2011-20 %/yr"] > 0)
    return out


def main():
    px, cost = load()
    print("data from", px.dropna(how="all").index[0].date(), "| cost per leg change (2x spread, %):",
          (cost * 100).round(3).to_dict())
    rows = []
    for L in (1, 3, 6, 12):
        for K in (2, 3):
            rows.append(dict(lookback_months=L, top_bottom=K, **summarize(backtest(px, cost, L, K))))
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))
    df.to_csv("results/fx_momentum.csv", index=False)


if __name__ == "__main__":
    main()
