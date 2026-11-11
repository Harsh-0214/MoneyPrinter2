"""Strategy arsenal: every strategy idea x every market, year by year, real costs.

    python run_arsenal.py                 # all strategies, all markets (~15-25 min, 4 workers)
    python run_arsenal.py --only orb      # strategies whose name contains "orb"
    python run_arsenal.py --markets XAUUSD

Each strategy runs ALONE on each market at the risk in config.yaml. Pip-based
settings are written for EURUSD and scaled per market by its typical daily range
(gold moves ~5-6x more "pips" than EURUSD). Results -> results/arsenal.csv and a
ranked table. "Consistent" = profitable in >= 4 of 5 years with PF >= 1.15.
"""
import argparse
import copy
import os
from multiprocessing import Pool

import pandas as pd
import yaml

MARKETS = {
    #  symbol    data file                          pip     spread  min_units  smt partner
    "EURUSD": ("data/EURUSD_M1_histdata.csv", 0.0001, 1.4, 1000, "GBPUSD"),
    "GBPUSD": ("data/GBPUSD_M1_histdata.csv", 0.0001, 2.0, 1000, "EURUSD"),
    "AUDUSD": ("data/AUDUSD_M1_histdata.csv", 0.0001, 1.5, 1000, None),
    "XAUUSD": ("data/XAUUSD_M1_histdata.csv", 0.1,   10.0, 1,    None),   # $1.00 spread
    "USDJPY": ("data/USDJPY_M1_histdata.csv", 0.01,  1.6, 1000, None),    # FOREX.com ~1.6 pips
}

# USD-base pairs (USD/JPY): P/L is in JPY, converted to the USD account at the exit price
# (instrument.inverse_quote). Swaps in USD per 100k per night: long USDJPY earned carry in
# 2021-25; pessimistic: longs get nothing, shorts pay ~$10.
QUOTE_FIX = {"USDJPY": dict(swap_long_per_lot=0.0, swap_short_per_lot=-10.0)}

# Overnight financing for non-FX instruments, annual % of position value (long, short).
# Pessimistic: both sides pay. FOREX.com demo reports 0 swap, so this is an estimate.
SWAP_PCT = {"XAUUSD": (-6.5, -1.5)}

BASE = yaml.safe_load(open("config.yaml"))
SWEEP = next(s for s in BASE["strategies"]["morning"] if s["name"] == "london_sweep")
BREAK = next(s for s in BASE["strategies"]["morning"] if s["name"] == "london_breakout")


def _v(base, **kw):
    s = copy.deepcopy(base)
    s.update(kw)
    return s


ORB_L = dict(name="opening_range", open_time="08:00", or_minutes=30, entry_end="11:00",
             exit_time="16:00", target_rr=2.0, daily_trend_filter=True, trail_to_breakeven_rr=1.0,
             skip_days=[0], tag="orbl")
ORB_NY = dict(name="opening_range", open_time="13:30", or_minutes=15, entry_end="15:30",
              exit_time="19:30", target_rr=2.0, daily_trend_filter=True, trail_to_breakeven_rr=1.0,
              tag="orbny")
PB = dict(name="trend_pullback", rsi_period=2, oversold=10, overbought=90, exit_rsi=50,
          stop_atr=2.0, max_hold_bars=24, entry_start="07:00", entry_end="19:00",
          exit_time="20:00", max_trades_per_day=3, cooldown_bars=3, daily_trend_filter=True)
DPB = dict(name="daily_pullback", trend_sma=100, rsi_period=2, oversold=10, overbought=90,
           exit_sma=5, max_hold_days=10, stop_atr=3.0)
VBO = dict(name="vol_breakout", k=0.5, entry_start="07:00", entry_end="16:00", exit_time="21:00",
           stop_range=0.5, trend_sma=50, skip_days=[0])
NRB = dict(name="nr_breakout", pattern="nr7", entry_start="07:00", entry_end="16:00",
           exit_time="21:00", target_rr=2.0, trend_sma=50, trail_to_breakeven_rr=1.0)
ORB_TK = dict(name="opening_range", open_time="00:00", or_minutes=60, entry_end="04:00",
              exit_time="08:00", target_rr=2.0, daily_trend_filter=True, trail_to_breakeven_rr=1.0,
              tag="orbtk")          # Tokyo open (09:00 JST = 00:00 London in winter)
NY_SWEEP = _v(SWEEP, range_start="08:00", range_end="12:00", sweep_window_start="13:00",
              sweep_window_end="15:00", entry_cutoff="15:30", session_exit="19:00")

#  name: (timeframe, slot, [specs], slot_max_trades)
STRATS = {
    "stack (Sweep+Breakout, current)": ("5min", "morning", [SWEEP, BREAK], 1),
    "London Sweep only":               ("5min", "morning", [SWEEP], 1),
    "London Breakout only":            ("5min", "morning", [BREAK], 1),
    "Breakout, no trend filter":       ("5min", "morning", [_v(BREAK, daily_trend_filter=False)], 1),
    "NY Sweep (London range)":         ("5min", "morning", [NY_SWEEP], 1),
    "ORB London 30m":                  ("5min", "morning", [ORB_L], 1),
    "ORB London 60m":                  ("5min", "morning", [_v(ORB_L, or_minutes=60)], 1),
    "ORB London 30m no target":        ("5min", "morning", [_v(ORB_L, target_rr=None)], 1),
    "ORB London 30m no trend":         ("5min", "morning", [_v(ORB_L, daily_trend_filter=False)], 1),
    "ORB NY 15m":                      ("5min", "morning", [ORB_NY], 1),
    "ORB NY 30m":                      ("5min", "morning", [_v(ORB_NY, or_minutes=30)], 1),
    "ORB NY 15m no target":            ("5min", "morning", [_v(ORB_NY, target_rr=None)], 1),
    "ORB NY 15m no trend":             ("5min", "morning", [_v(ORB_NY, daily_trend_filter=False)], 1),
    "ORB NY 15m mid stop":             ("5min", "morning", [_v(ORB_NY, stop_mode="mid")], 1),
    "Pullback RSI2 15m":               ("15min", "morning", [PB], 3),
    "Pullback RSI2 15m, EMA exit":     ("15min", "morning", [_v(PB, exit_mode="ema")], 3),
    "Pullback RSI2 15m, 3xATR stop":   ("15min", "morning", [_v(PB, stop_atr=3.0)], 3),
    "Pullback RSI2 5m":                ("5min", "morning", [_v(PB, max_hold_bars=48)], 3),
    "Pullback RSI2 1h":                ("1h", "morning", [_v(PB, max_hold_bars=12, exit_time="21:00")], 3),
    "Pullback RSI2 15m, extreme 5/95": ("15min", "morning", [_v(PB, oversold=5, overbought=95)], 3),
    # --- round 2 (same markets, new styles) ---
    "Daily pullback RSI2, SMA100":     ("1h", "morning", [DPB], 1),
    "Daily pullback RSI2, SMA200":     ("1h", "morning", [_v(DPB, trend_sma=200)], 1),
    "Daily pullback RSI2 <5":          ("1h", "morning", [_v(DPB, oversold=5, overbought=95)], 1),
    "Daily pullback, long only":       ("1h", "morning", [_v(DPB, long_only=True)], 1),
    "Daily pullback, 2xATR stop":      ("1h", "morning", [_v(DPB, stop_atr=2.0)], 1),
    "Vol breakout k0.5 +trend":        ("15min", "morning", [VBO], 1),
    "Vol breakout k0.3 +trend":        ("15min", "morning", [_v(VBO, k=0.3)], 1),
    "Vol breakout k0.7 +trend":        ("15min", "morning", [_v(VBO, k=0.7)], 1),
    "Vol breakout k0.5 no trend":      ("15min", "morning", [_v(VBO, trend_sma=None)], 1),
    "Vol breakout k0.5 BE+2R":         ("15min", "morning", [_v(VBO, trail_to_breakeven_rr=1.0, target_rr=2.0)], 1),
    "NR7 breakout +trend":             ("15min", "morning", [NRB], 1),
    "NR4 breakout +trend":             ("15min", "morning", [_v(NRB, pattern="nr4")], 1),
    "Inside-day breakout +trend":      ("15min", "morning", [_v(NRB, pattern="inside")], 1),
    "NR7 breakout no target":          ("15min", "morning", [_v(NRB, target_rr=None)], 1),
    "NR7 breakout no trend":           ("15min", "morning", [_v(NRB, trend_sma=None)], 1),
    "Prev-day H/L breakout":           ("5min", "morning", [dict(name="prev_day_breakout", buffer_pips=1.0,
                                                               min_range_pips=20, max_range_pips=150,
                                                               reward_risk=2.0)], 1),
    "Trend Donchian 20/10 long 2ATR":  ("1h", "morning", [dict(name="trend_follow", signal="donchian",
                                                               entry_days=20, exit_days=10, stop_atr=2.0,
                                                               long_only=True)], 1),
    "Trend Donchian 55/20 long 2ATR":  ("1h", "morning", [dict(name="trend_follow", signal="donchian",
                                                               entry_days=55, exit_days=20, stop_atr=2.0,
                                                               long_only=True)], 1),
    "Trend follow Donchian 55/20":     ("1h", "morning", [dict(name="trend_follow", signal="donchian",
                                                               entry_days=55, exit_days=20, stop_atr=3.0)], 1),
    "Trend follow Donchian 20/10":     ("1h", "morning", [dict(name="trend_follow", signal="donchian",
                                                               entry_days=20, exit_days=10, stop_atr=3.0)], 1),
    "ORB Tokyo 60m":                   ("5min", "morning", [ORB_TK], 1),
    "ORB Tokyo 30m":                   ("5min", "morning", [_v(ORB_TK, or_minutes=30)], 1),
    "ORB Tokyo 60m no trend":          ("5min", "morning", [_v(ORB_TK, daily_trend_filter=False)], 1),
    "Trend Donchian 55/20 both 2ATR":  ("1h", "morning", [dict(name="trend_follow", signal="donchian",
                                                               entry_days=55, exit_days=20, stop_atr=2.0)], 1),
    "Trend Donchian 20/10 both 2ATR":  ("1h", "morning", [dict(name="trend_follow", signal="donchian",
                                                               entry_days=20, exit_days=10, stop_atr=2.0)], 1),
    "Trend Donchian 40/15 long 2ATR":  ("1h", "morning", [dict(name="trend_follow", signal="donchian",
                                                               entry_days=40, exit_days=15, stop_atr=2.0,
                                                               long_only=True)], 1),
    "Trend Donchian 40/15 both 2ATR":  ("1h", "morning", [dict(name="trend_follow", signal="donchian",
                                                               entry_days=40, exit_days=15, stop_atr=2.0)], 1),
    "Trend follow EMA 20/100":         ("1h", "morning", [dict(name="trend_follow", signal="ema",
                                                               ema_fast=20, ema_slow=100, exit_days=None,
                                                               stop_atr=3.0)], 1),
}

_BARS, _SCALE = {}, {}


def _scale_spec(spec, k):
    s = copy.deepcopy(spec)
    for key, val in list(s.items()):
        if key.endswith("_pips") and isinstance(val, (int, float)) and val is not None:
            s[key] = val * k
    return s


def _init(markets, spread_override=None):
    from run_validate import _bars
    global _BARS, _SCALE
    for sym, sp in (spread_override or {}).items():
        m = MARKETS[sym]
        MARKETS[sym] = (m[0], m[1], sp, m[3], m[4])
    for sym in markets:
        path, pip, *_ = MARKETS[sym]
        if not os.path.exists(path):
            continue
        b5 = _bars(path, "UTC", "5min").copy()
        smt = MARKETS[sym][4]
        if smt and os.path.exists(MARKETS[smt][0]):
            sb = _bars(MARKETS[smt][0], "UTC", "5min")[["high", "low"]].reindex(b5.index)
            b5["smt_high"], b5["smt_low"] = sb["high"], sb["low"]
        _BARS[(sym, "5min")] = b5
        _BARS[(sym, "15min")] = _bars(path, "UTC", "15min")
        _BARS[(sym, "1h")] = _bars(path, "UTC", "1h")
        d = b5["high"].resample("1D").max() - b5["low"].resample("1D").min()
        _SCALE[sym] = float(d[d > 0].median() / pip)
    eur = _SCALE.get("EURUSD", 70.0)
    _SCALE.update({k: v / eur for k, v in _SCALE.items()})


def _run(job):
    from run_validate import summarize, per_year
    from fxbot.backtest import run_backtest
    name, sym = job
    tf, slot, specs, limit = STRATS[name]
    path, pip, spread, min_units, _ = MARKETS[sym]
    if (sym, tf) not in _BARS:
        return None
    c = copy.deepcopy(BASE)
    c["smt"] = {}
    c["costs"]["spread_pips"] = spread
    if sym in SWAP_PCT:              # e.g. gold: financing as % of position value per year
        c["costs"]["swap_long_per_lot"] = c["costs"]["swap_short_per_lot"] = 0.0
        c["costs"]["swap_long_pct"], c["costs"]["swap_short_pct"] = SWAP_PCT[sym]
    c["instrument"] = {"pip": pip, "min_units": min_units}
    if sym in QUOTE_FIX:
        q = QUOTE_FIX[sym]
        c["instrument"]["inverse_quote"] = True
        c["costs"]["swap_long_per_lot"], c["costs"]["swap_short_per_lot"] = q["swap_long_per_lot"], q["swap_short_per_lot"]
    c["strategies"] = {"morning": [], "afternoon": []}
    c["strategies"][slot] = [_scale_spec(s, _SCALE[sym]) for s in specs]
    c["slot_max_trades"] = limit
    c["strategy"] = {"daily_ema_period": 50}     # trend line for the filters
    se = c["account"]["starting_equity"]
    t, eq = run_backtest(_BARS[(sym, tf)], c)
    m = summarize(t, eq, se)
    py = per_year(t, eq, se)
    yrs = dict(zip(py.year, py["ret%"]))
    pos = sum(1 for v in yrs.values() if v > 0)
    return dict(strategy=name, market=sym, trades=m["trades"], per_year=round(m["trades"] / 5, 1),
                ret=m["ret%"], dd=m["dd%"], pf=m["pf"], avgR=m["avgR"], win=m["win%"],
                pos_years=pos, worst_year=min(yrs.values()) if yrs else 0,
                **{f"y{y % 100}": v for y, v in yrs.items()},
                consistent=bool(pos >= 4 and m["pf"] >= 1.15))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--markets", default=",".join(MARKETS))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--spread", default="", help='override spreads in pips, e.g. "XAUUSD=0,EURUSD=0.6"')
    ap.add_argument("--out", default="results/arsenal.csv")
    args = ap.parse_args()
    spread_override = {k: float(v) for k, v in (p.split("=") for p in args.spread.split(",") if p)}
    markets = [m for m in args.markets.split(",") if os.path.exists(MARKETS[m][0])]
    keys = [k.strip().lower() for k in args.only.split("|")]      # "--only a|b" = either
    jobs = [(n, s) for n in STRATS if any(k in n.lower() for k in keys) for s in markets]
    print(f"{len(jobs)} runs ({len(markets)} markets) ...", flush=True)
    rows = []
    with Pool(args.workers, initializer=_init, initargs=(markets, spread_override)) as pool:
        for i, r in enumerate(pool.imap_unordered(_run, jobs), 1):
            if r:
                rows.append(r)
                print(f"  [{i}/{len(jobs)}] {r['market']} {r['strategy']:<34} {r['per_year']:5.0f}/yr "
                      f"{r['ret']:+7.1f}%  dd {r['dd']:6.1f}  pf {r['pf']:.2f}  +yrs {r['pos_years']}/5",
                      flush=True)
    df = pd.DataFrame(rows).sort_values(["consistent", "pf"], ascending=False)
    os.makedirs("results", exist_ok=True)
    df.to_csv(args.out, index=False)
    pd.set_option("display.width", 250)
    cols = ["market", "strategy", "per_year", "ret", "dd", "pf", "avgR", "pos_years", "worst_year",
            "consistent"]
    print("\n=== RANKED (consistent first, then profit factor) ===")
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
