"""Strategy search, round 3 (Nov 18 2026): four families never tested here.

    python run_round3.py            # all four (needs MetaTrader 5 open for the daily data)
    python run_round3.py --only ibs

A. Relative-value mean reversion: AUDNZD, EURGBP, EURCHF (single crosses) and gold vs silver
   (log price ratio). z = (log price - its N-day mean) / N-day std. Enter at the close when
   |z| > 2 (sell when stretched up, buy when stretched down), exit when z crosses 0 or after H days.
   N = 20 / 60, H = 10 / 20. (Pairs were only tested on single stocks before.)
B. IBS mean reversion on stock indices: IBS = (close - low) / (high - low). Buy at the close when
   IBS < 0.2 (optionally only above the 200-day average); sell at the next close, or when a close is
   above the previous day's high (max 5 days). 8 index CFDs. (Tested before on single stocks only.)
C. Monthly seasonality, walk-forward: for each year, a month is traded long (short) only if it rose
   (fell) in >= 70% of the previous 15 years (at least 10 years of history). Gold, silver, 8 indices,
   7 FX pairs. Never uses the year it trades.
D. NASDAQ opening-gap fade (Dukascopy M1 2021-26): when the 09:30 New York open is more than
   0.25% / 0.5% away from the previous 16:00 close, trade toward the previous close (target = gap
   filled, stop = the same distance the other way), out at 16:00 if neither.

Costs, deliberately pessimistic: 2x the broker's current spread per round trip; index and gold
CFDs pay 6%/yr financing per night held (long or short); FX financing not included (small on these
crosses). Daily data: the broker's D1 history (FX crosses from 1993-96, indices from 2000, metals
from 2006). Results are per trade as % of the position (1x, no leverage) and summed per year.
Pass (fixed before the run): PF >= 1.15 over 2021-25 with >= 4 of 5 years up, 2026 not negative,
AND profitable over the history before 2021 (which no live rule was ever fitted on).
"""
import argparse

import numpy as np
import pandas as pd

INDICES = ["SPX500", "US30", "NAS100", "GER40", "UK100", "JPN225", "AUS200", "FRA40"]
FINANCE = 0.06 / 365                       # per night, index / gold CFDs


def load_daily(symbols):
    import MetaTrader5 as mt5
    mt5.initialize()
    out, cost = {}, {}
    for s in symbols:
        mt5.symbol_select(s, True)
        r = pd.DataFrame(mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 9000))
        i = mt5.symbol_info(s)
        df = r[["open", "high", "low", "close"]].copy()
        df.index = pd.to_datetime(r.time, unit="s")
        out[s] = df[df.high > df.low]                      # drop flat holiday bars
        cost[s] = 2 * i.spread * i.point / float(df.close.iloc[-1])
    mt5.shutdown()
    return out, cost


def pf(x):
    w, l = x[x > 0].sum(), -x[x <= 0].sum()
    return round(w / l, 2) if l > 0 else np.inf


def verdict(trades, label):
    """trades: Series of per-trade returns (fraction) indexed by exit date."""
    t = trades.dropna()
    row = dict(rule=label, trades=len(t))
    if not len(t):
        return row
    y = t.index.year
    for name, m in (("pre-2021", y < 2021), ("2021-25", (y >= 2021) & (y <= 2025)), ("2026", y == 2026)):
        x = t[m]
        nyears = max(len(set(y[m])), 1)
        row[f"{name} %/yr"] = round(x.sum() * 100 / nyears, 2) if len(x) else np.nan
        row[f"{name} PF"] = pf(x) if len(x) else np.nan
    h = t[(y >= 2021) & (y <= 2025)]
    row["yrs up 21-25"] = int((h.groupby(h.index.year).sum() > 0).sum())
    row["avg %/trade"] = round(t.mean() * 100, 3)
    row["PASS"] = bool(row.get("2021-25 PF", 0) >= 1.15 and row["yrs up 21-25"] >= 4
                       and not (row.get("2026 %/yr", 0) < 0) and row.get("pre-2021 %/yr", -1) > 0)
    return row


# ---------------------------------------------------------------- A. relative value
def zscore_trades(logp, cost, N, H, finance=0.0):
    z = (logp - logp.rolling(N).mean()) / logp.rolling(N).std()
    out, i, n = [], N, len(logp)
    v, zz, idx = logp.to_numpy(), z.to_numpy(), logp.index
    while i < n - 1:
        if abs(zz[i]) > 2:
            side = -np.sign(zz[i])
            j = i + 1
            while j < n - 1 and j - i < H and np.sign(zz[j]) == np.sign(zz[i]):
                j += 1
            out.append((idx[j], side * (v[j] - v[i]) - cost - finance * (idx[j] - idx[i]).days))
            i = j + 1
        else:
            i += 1
    return pd.Series(dict(out)).sort_index() if out else pd.Series(dtype=float)


def part_a(d, cost):
    rows = []
    series = {s: np.log(d[s].close) for s in ("AUDNZD.", "EURGBP.", "EURCHF.")}
    g, sv = d["XAUUSD"].close, d["XAGUSD"].close
    j = g.index.intersection(sv.index)
    series["gold/silver"] = np.log(g[j] / sv[j])
    cost["gold/silver"] = cost["XAUUSD"] + cost["XAGUSD"]
    for name, lp in series.items():
        fin = FINANCE * 2 if name == "gold/silver" else 0.0   # two metal legs
        for N in (20, 60):
            for H in (10, 20):
                rows.append(verdict(zscore_trades(lp.dropna(), cost[name], N, H, fin), f"A {name} z>2 N{N} H{H}"))
    return rows


# ---------------------------------------------------------------- B. IBS on indices
def ibs_trades(df, cost, trend, exit_rule):
    ibs = (df.close - df.low) / (df.high - df.low)
    sma = df.close.rolling(200).mean()
    c, h, idx = df.close.to_numpy(), df.high.to_numpy(), df.index
    out, i, n = [], 200, len(df)
    ib, sm = ibs.to_numpy(), sma.to_numpy()
    while i < n - 1:
        if ib[i] < 0.2 and (not trend or c[i] > sm[i]):
            j = i + 1
            if exit_rule == "high":
                while j < n - 1 and j - i < 5 and c[j] <= h[j - 1]:
                    j += 1
            out.append((idx[j], c[j] / c[i] - 1 - cost - FINANCE * (idx[j] - idx[i]).days))
            i = j
        else:
            i += 1
    return pd.Series(dict(out)).sort_index() if out else pd.Series(dtype=float)


def part_b(d, cost):
    rows = []
    for s in INDICES:
        for trend in (False, True):
            for ex in ("next close", "high"):
                rows.append(verdict(ibs_trades(d[s], cost[s], trend, ex),
                                    f"B {s} IBS<0.2{' >200d' if trend else ''} exit {ex}"))
    return rows


# ---------------------------------------------------------------- C. seasonality
def season_trades(df, cost, finance):
    m = df.close.resample("ME").last()
    r = m.pct_change().dropna()
    out = []
    for t, ret in r.items():
        past = r[(r.index.month == t.month) & (r.index.year < t.year) & (r.index.year >= t.year - 15)]
        if len(past) < 10:
            continue
        up = (past > 0).mean()
        side = 1 if up >= 0.7 else -1 if up <= 0.3 else 0
        if side:
            out.append((t, side * ret - cost - finance * 30))
    return pd.Series(dict(out)) if out else pd.Series(dtype=float)


def part_c(d, cost):
    rows, all_t = [], []
    for s in ["XAUUSD", "XAGUSD"] + INDICES + ["EURUSD.", "GBPUSD.", "USDJPY.", "AUDUSD.", "USDCAD.", "USDCHF.", "NZDUSD."]:
        t = season_trades(d[s], cost[s], 0.0 if s.endswith(".") else FINANCE)
        rows.append(verdict(t, f"C {s} seasonal months"))
        all_t.append(t)
    rows.append(verdict(pd.concat(all_t).sort_index(), "C ALL markets seasonal months"))
    return rows


# ---------------------------------------------------------------- D. NASDAQ gap fade
def part_d():
    import run_fvg123 as F
    b = F._load("NAS100")
    b.index = b.index.tz_convert("America/New_York")
    hm = b.index.strftime("%H:%M")
    rows = []
    days = pd.Series(b.index.normalize()).unique()
    prev_close = b.close[hm == "15:59"]
    prev_close.index = prev_close.index.normalize()
    opens = b.open[hm == "09:30"]
    opens.index = opens.index.normalize()
    pc = prev_close.shift(1).reindex(opens.index)
    sess = b[(hm >= "09:30") & (hm <= "15:59")]
    by_day = {k: g for k, g in sess.groupby(sess.index.normalize())}
    for thr in (0.0025, 0.005):
        out = []
        for d0, o in opens.items():
            p = pc.get(d0)
            if p is None or np.isnan(p):
                continue
            gap = (o - p) / p
            if abs(gap) <= thr:
                continue
            side = -np.sign(gap)
            dist = abs(o - p)
            entry, target, stop = o + 1.75 * side, p, o - side * dist
            g = by_day.get(d0)
            res = None
            for x in g.iloc[1:].itertuples():
                if (x.low <= stop if side == 1 else x.high >= stop):
                    res = stop
                    break
                if (x.high >= target if side == 1 else x.low <= target):
                    res = target
                    break
            if res is None:
                res = g.close.iloc[-1]
            pts = (res - entry) * side - 1.75 - 0.5
            out.append((d0.tz_localize(None), pts / o))
        rows.append(verdict(pd.Series(dict(out)).sort_index(), f"D NAS100 gap fade > {thr * 100:.2f}%"))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="a,b,c,d")
    a = ap.parse_args()
    parts = a.only.split(",")
    rows = []
    if any(p in parts for p in ("a", "b", "c")):
        syms = ["AUDNZD.", "EURGBP.", "EURCHF.", "XAUUSD", "XAGUSD", "EURUSD.", "GBPUSD.", "USDJPY.",
                "AUDUSD.", "USDCAD.", "USDCHF.", "NZDUSD."] + INDICES
        d, cost = load_daily(syms)
        if "a" in parts:
            rows += part_a(d, cost)
        if "b" in parts:
            rows += part_b(d, cost)
        if "c" in parts:
            rows += part_c(d, cost)
    if "d" in parts:
        rows += part_d()
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 300)
    print(df.to_string(index=False))
    print(f"\nPASS: {int(df.PASS.fillna(False).sum())} of {len(df)}")
    df.to_csv("results/round3.csv", index=False)


if __name__ == "__main__":
    main()
