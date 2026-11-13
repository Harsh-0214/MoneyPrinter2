"""Portfolio simulator: every live strategy together, compounding, the way the bots size.

    python run_portfolio.py                       # 2021-25 histdata + 2026 MT5, risk 1..6%
    python run_portfolio.py --risk 3 --mc 3000    # one risk level + reshuffle Monte Carlo
    python run_portfolio.py --refresh             # re-run the unit backtests (else cached)

Step 1 runs each unit (market stack / sleeve) alone at 1% risk and keeps its trades as
R-multiples, with the notional each trade needed (leverage per 1% risk).
Step 2 replays all trades in time order on ONE account:
  * risk per trade = risk% x current equity (compounding), cut by the live risk brake
    (live.risk_brake) and stopped at live.max_drawdown_pct below the peak;
  * a trade is skipped if all open trades' risk + this one would exceed live.max_open_risk_pct;
  * a trade's size is cut so its notional stays <= risk.max_leverage x equity, and so the
    margin of all open trades stays <= live.max_margin_used_pct of equity (MARGIN_RATE per
    market, as the broker charges it: gold needs 4.4x the margin of FX per $ of notional).
P/L of a trade is booked at its exit. That's what this measures and what it ignores:
it doesn't re-route trades the single-account bot would have taken differently.
"""
import argparse
import copy
import os

import numpy as np
import pandas as pd
import yaml

CACHE = "results/portfolio_trades_{}.csv"
# Margin as a share of notional, measured on the FOREX.com demo with mt5.order_calc_margin
# (Nov 2026): FX majors 5% (20:1), gold 22% (~4.5:1), US indices 10%.
MARGIN_RATE = {"EURUSD": 0.05, "GBPUSD": 0.05, "USDJPY": 0.05, "AUDUSD": 0.05, "XAUUSD": 0.22}


def _units_trades(cfg, source):
    from fxbot.backtest import expand_units, pair_config, run_backtest
    base = copy.deepcopy(cfg)
    base["risk"]["risk_per_trade_pct"] = 1.0
    base["risk"]["max_leverage"] = 1000            # leverage is applied in the replay instead
    se = base["account"]["starting_equity"]
    if source == "hist":
        from run_validate import load_pairs
        bars = load_pairs(base)
    else:
        bars = _mt5_bars(base)
    out = []
    for u in expand_units(base):
        if u["key"] not in bars:
            continue
        c = pair_config(base, u)
        c["smt"] = {}
        t, eq = run_backtest(bars[u["key"]], c)
        if not len(t):
            continue
        t = t.copy()
        t["unit"], t["market"] = u["key"], u["market"]
        t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
        t["exit_time"] = pd.to_datetime(t["exit_time"], utc=True)
        # notional in account money per unit traded (USDJPY units are already USD)
        px = 1.0 if c.get("instrument", {}).get("inverse_quote") else t["entry_price"]
        notional = t["units"] * px
        # money risked = 1% of that unit's equity at entry, recovered from pnl / R
        eq_at = eq.reindex(t["entry_time"], method="ffill").to_numpy()
        risk_money = 0.01 * np.where(np.isfinite(eq_at), eq_at, se)
        t["lev_per_1pct"] = notional.to_numpy() / (risk_money / 0.01) / 1.0
        out.append(t[["unit", "market", "entry_time", "exit_time", "side", "r_multiple",
                      "lev_per_1pct", "exit_reason", "tag"]])
        print(f"  {u['key']:<16} {len(t):4d} trades  avg R {t.r_multiple.mean():+.3f}", flush=True)
    return pd.concat(out, ignore_index=True).sort_values("entry_time").reset_index(drop=True)


def _mt5_bars(cfg):
    import MetaTrader5 as mt5
    from fxbot.backtest import expand_units, pair_config
    from fxbot.data import server_ts_to_utc
    mt5.initialize()
    tfm = {"5min": mt5.TIMEFRAME_M5, "15min": mt5.TIMEFRAME_M15, "1h": mt5.TIMEFRAME_H1}
    sym = {"EURUSD": "EURUSD.", "GBPUSD": "GBPUSD.", "XAUUSD": "XAUUSD", "USDJPY": "USDJPY."}
    cache, out = {}, {}

    def get(s, tf):
        if (s, tf) not in cache:
            r = mt5.copy_rates_from_pos(sym[s], tfm[tf], 0, {"5min": 99000, "15min": 60000}.get(tf, 12000))
            df = pd.DataFrame(r)
            df.index = server_ts_to_utc(df["time"].values)
            df = df[df.index.notna()][["open", "high", "low", "close"]]
            cache[(s, tf)] = df[~df.index.duplicated()].sort_index()
        return cache[(s, tf)]

    for u in expand_units(cfg):
        c = pair_config(cfg, u)
        tf = c["data"]["timeframe"]
        b = get(u["market"], tf).copy()
        if u.get("smt") and u["market"] in ("EURUSD", "GBPUSD"):
            other = "GBPUSD" if u["market"] == "EURUSD" else "EURUSD"
            s = get(other, tf)[["high", "low"]].reindex(b.index)
            b["smt_high"], b["smt_low"] = s["high"], s["low"]
        out[u["key"]] = b
    mt5.shutdown()
    return out


def load_trades(cfg, source, refresh=False):
    path = CACHE.format(source)
    if os.path.exists(path) and not refresh:
        t = pd.read_csv(path)
        for c in ("entry_time", "exit_time"):
            t[c] = pd.to_datetime(t[c], utc=True)
        return t
    print(f"running unit backtests ({source}) ...")
    t = _units_trades(cfg, source)
    os.makedirs("results", exist_ok=True)
    t.to_csv(path, index=False)
    return t


def replay(trades, risk_pct, live, max_lev, weights=None, start_eq=50_000.0, detail=False):
    """One account, trades in time order. Returns (equity series at each event, taken mask),
    plus each trade's P/L in money when detail=True."""
    brake = sorted(live.get("risk_brake") or [], key=lambda x: x[0])
    stop_dd = float(live.get("max_drawdown_pct") or 1e9)
    cap = float(live.get("max_open_risk_pct") or 1e9)
    margin_cap = float(live.get("max_margin_used_pct", 100)) / 100
    mrate = trades["market"].map(MARGIN_RATE).fillna(0.05).to_numpy()
    ev = []
    for i, r in enumerate(trades.itertuples()):
        ev.append((r.entry_time.value, 1, i))
        ev.append((r.exit_time.value, 0, i))
    ev.sort()                                  # exits before entries at the same instant
    bal, peak = start_eq, start_eq
    open_ = {}                                 # i -> (risk money, margin money)
    times, eqs = [], []
    taken = np.zeros(len(trades), bool)
    money = np.zeros(len(trades))
    R = trades["r_multiple"].to_numpy()
    lev1 = trades["lev_per_1pct"].to_numpy()
    w = np.ones(len(trades)) if weights is None else trades["unit"].map(weights).fillna(1.0).to_numpy()
    for t, kind, i in ev:
        if kind == 0:
            if i in open_:
                risk_m, _ = open_.pop(i)
                bal += R[i] * risk_m
                money[i] = R[i] * risk_m
                peak = max(peak, bal)
                times.append(t)
                eqs.append(bal)
            continue
        dd = (1 - bal / peak) * 100
        if dd >= stop_dd:
            continue
        rp = risk_pct * w[i]
        for lvl, r_ in brake:                   # same absolute caps as run_live.brake_risk
            if dd >= lvl:
                rp = min(rp, r_)
        open_risk = sum(v[0] for v in open_.values()) / bal * 100
        if open_risk + rp > cap + 1e-9:
            continue
        lev = lev1[i] * rp                      # notional / equity at this risk
        if lev > max_lev:
            rp *= max_lev / lev
            lev = max_lev
        used = sum(v[1] for v in open_.values()) / bal
        room = margin_cap - used                # share of equity still free for margin
        if room <= 1e-6:
            continue
        if lev * mrate[i] > room:
            rp *= room / (lev * mrate[i])
            lev = room / mrate[i]
        open_[i] = (rp / 100 * bal, lev * mrate[i] * bal)
        taken[i] = True
    eq = pd.Series(eqs, index=pd.to_datetime(times, utc=True))
    return (eq, taken, money) if detail else (eq, taken)


def stats(eq, start_eq=50_000.0):
    if not len(eq):
        return {}
    full = pd.concat([pd.Series([start_eq], index=[eq.index[0] - pd.Timedelta(seconds=1)]), eq])
    m = full.resample("ME").last().ffill()
    prev = m.shift(1).fillna(start_eq)
    mret = (m / prev - 1) * 100
    dd = (full / full.cummax() - 1).min() * 100
    months = len(mret)
    geo = ((full.iloc[-1] / start_eq) ** (1 / months) - 1) * 100
    return dict(months=months, geo_month=round(geo, 2), median_month=round(mret.median(), 2),
                losing_months=int((mret < 0).sum()), worst_month=round(mret.min(), 2),
                maxdd=round(dd, 1), final_x=round(full.iloc[-1] / start_eq, 2))


def monte_carlo(trades, risk_pct, live, max_lev, n=1000, seed=1):
    """Reshuffle which trade lands where (keeping each unit's timing and hold length),
    so a different ordering of the same wins and losses. Returns drawdown + month stats."""
    rng = np.random.default_rng(seed)
    dds, geos = [], []
    for _ in range(n):
        t = trades.copy()
        for u, g in t.groupby("unit").groups.items():          # shuffle R within each unit
            idx = np.asarray(g)
            t.loc[idx, "r_multiple"] = rng.permutation(t.loc[idx, "r_multiple"].to_numpy())
        eq, _ = replay(t, risk_pct, live, max_lev)
        s = stats(eq)
        dds.append(s["maxdd"])
        geos.append(s["geo_month"])
    dds, geos = np.array(dds), np.array(geos)
    return dict(dd_median=round(np.median(dds), 1), dd_p95=round(np.percentile(dds, 5), 1),
                dd_p99=round(np.percentile(dds, 1), 1), share_past_30=round((dds <= -30).mean() * 100, 1),
                share_past_50=round((dds <= -50).mean() * 100, 1),
                geo_p10=round(np.percentile(geos, 10), 2), geo_med=round(np.median(geos), 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--risk", default="1,2,3,4,5,6")
    ap.add_argument("--mc", type=int, default=0, help="Monte Carlo reshuffles per risk level")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--no-brake", action="store_true")
    ap.add_argument("--sources", default="hist,mt5")
    a = ap.parse_args()
    cfg = yaml.safe_load(open("config.yaml"))
    live = dict(cfg["live"])
    if a.no_brake:
        live["risk_brake"] = []
    max_lev = float(cfg["risk"]["max_leverage"])
    pd.set_option("display.width", 220)
    for src in a.sources.split(","):
        tr = load_trades(cfg, src, a.refresh)
        if src == "hist":
            tr = tr[(tr.entry_time >= "2021-01-01") & (tr.entry_time < "2026-01-01")]
        else:
            tr = tr[tr.entry_time >= "2026-01-01"]
        tr = tr.reset_index(drop=True)
        print(f"\n=== {src}: {len(tr)} trades, {tr.entry_time.min().date()} .. {tr.exit_time.max().date()} ===")
        rows = []
        for rp in [float(x) for x in a.risk.split(",")]:
            eq, taken = replay(tr, rp, live, max_lev)
            row = dict(risk=rp, taken=int(taken.sum()), **stats(eq))
            if a.mc and src == "hist":
                row.update(monte_carlo(tr, rp, live, max_lev, a.mc))
            rows.append(row)
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
