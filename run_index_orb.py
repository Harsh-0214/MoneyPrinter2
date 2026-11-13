"""US index opening-range breakout (NASDAQ / S&P 500 / Dow), research only.

    python run_index_orb.py          # needs data/mt5/<IDX>_M15.csv and _M5.csv (MT5 export)

Opening range = the first 15 or 30 minutes after the 09:30 New York cash open. A close
beyond it (until 11:00 NY) enters in that direction; stop at the other side of the range;
target 2R or none; stop to breakeven at +1R; everything closed 15:45 NY.
Bars are re-labelled so the bot's "London clock" reads New York time + 5 h, which keeps
the open at 09:30 NY on every day of the year (US and UK change clocks on different dates).
Costs: each bar's recorded spread, floored at today's typical spread, plus slippage.
Only ~2.5 years of 15-min data exist on MT5 (Apr 2024 on), so this is a rough check.
"""
import copy

import pandas as pd

from fxbot.backtest import run_backtest
from run_new_markets import make_cfg
from run_validate import summarize

ORB = dict(name="opening_range", open_time="14:30", or_minutes=15, entry_end="16:00",
           exit_time="20:45", target_rr=2.0, daily_trend_filter=True, trail_to_breakeven_rr=1.0,
           buffer_pips=0, tag="orbus")
VARIANTS = {
    "OR 15m, 2R target, trend":  {},
    "OR 30m, 2R target, trend":  {"or_minutes": 30},
    "OR 15m, no target, trend":  {"target_rr": None},
    "OR 15m, 2R target, no trend": {"daily_trend_filter": False},
}
FLOOR = {"NAS100": 30, "SPX500": 6, "US30": 50}


def ny_clock(df):
    """Index the bars so London local time == New York local time + 5 h."""
    ny = df.index.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=5)
    out = df.copy()
    out.index = ny.tz_localize("Europe/London", ambiguous="NaT", nonexistent="NaT")
    out = out[out.index.notna()]
    out.index = out.index.tz_convert("UTC")
    return out[~out.index.duplicated()].sort_index()


def load(sym, tf):
    df = pd.read_csv(f"data/mt5/{sym}_{tf}.csv", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "spread_pts"]].rename(columns={"spread_pts": "data_spread_pips"})
    df["data_spread_pips"] = df["data_spread_pips"].clip(lower=FLOOR[sym])
    return ny_clock(df)


def main():
    rows = []
    for sym in FLOOR:
        for tf in ("M15", "M5"):
            bars = load(sym, tf)
            for name, kw in VARIANTS.items():
                spec = dict(copy.deepcopy(ORB), **kw)
                c = make_cfg(sym, spec)
                se = c["account"]["starting_equity"]
                t, eq = run_backtest(bars, c)
                if not len(t):
                    continue
                t = t.copy()
                t["y"] = pd.to_datetime(t.entry_time).dt.year
                m = summarize(t, eq, se)
                by = t.groupby("y").r_multiple.sum().round(1).to_dict()
                rows.append(dict(market=sym, bars=tf, variant=name, trades=len(t),
                                 per_month=round(len(t) / ((bars.index[-1] - bars.index[0]).days / 30.4), 1),
                                 win=m["win%"], pf=m["pf"], avgR=m["avgR"], totalR=round(t.r_multiple.sum(), 1),
                                 R_by_year=by))
                print(rows[-1], flush=True)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 60)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
