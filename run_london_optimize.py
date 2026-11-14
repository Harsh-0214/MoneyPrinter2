"""Optimise the London stack's limits honestly: walk-forward, as if each year were unseen.

    python run_london_optimize.py              # grid (~10-20 min, 6 workers) + walk-forward report

Limits searched (everything else = live config):
  Breakout  min_range_pips 16-28, max_range_pips 60/80/100/999 (= no limit), max_defer_extension_pips 10-25/none
  Sweep     min_rr 1.0-2.0, max_stop_pips 20-40
Score = total R at 1% risk on EURUSD + GBPUSD (= profit, no compounding noise).

How "never saw the data" is enforced:
  * anchored walk-forward on histdata: the limits used for 2023 are the best on 2021-22 only,
    for 2024 the best on 2021-23, for 2025 the best on 2021-24;
  * final exam: the limits picked on all of 2021-25 are run on 2026 (broker's own M5/M15 feed),
    data no setting was ever chosen on;
  * "best" = highest average score of a setting AND its grid neighbours (a plateau, not a spike).
The live limits were themselves chosen looking at 2021-25, so only their 2026 result is a fair
comparison.
"""
import copy
import itertools
import os
from multiprocessing import Pool

import numpy as np
import pandas as pd
import yaml

BASE = yaml.safe_load(open("config.yaml"))
GRID_B = dict(min_range_pips=[16, 18, 20, 22, 24, 26, 28], max_range_pips=[60, 80, 100, 999],
              max_defer_extension_pips=[10, 15, 20, 25, None])
GRID_S = dict(min_rr=[1.0, 1.25, 1.5, 2.0], max_stop_pips=[20, 25, 30, 40])
LIVE_B = {k: next(s for s in BASE["strategies"]["morning"] if s["name"] == "london_breakout")[k] for k in GRID_B}
LIVE_S = {k: next(s for s in BASE["strategies"]["morning"] if s["name"] == "london_sweep")[k] for k in GRID_S}
YEARS = [2021, 2022, 2023, 2024, 2025]
_BARS = {}


def _mt5_frame(fn, spread_col):
    df = pd.read_csv(fn, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    out = df[["open", "high", "low", "close"]].copy()
    out["data_spread_pips"] = df[spread_col] / 10.0
    return out


def _bars_2026():
    """Broker bars for the 2026 exam, same timeframes as live (EUR 15 min, GBP 5 min) with the
    partner pair as SMT feed. GBP/EUR 5-min files start Dec 2025, so 15-min bars before that are
    prepended only to warm up the 50-day average (no trades are scored before 2026)."""
    from fxbot.data import resample
    m15 = {s: _mt5_frame(f"data/mt5/{s}_M15.csv", "spread_pts") for s in ("EURUSD", "GBPUSD")}
    m5 = {s: _mt5_frame(f"data/mt5/{s}_M5_2026.csv", "spread") for s in ("EURUSD", "GBPUSD")}
    out = {}
    e = m15["EURUSD"][m15["EURUSD"].index >= "2025-06-01"].copy()
    g = m15["GBPUSD"][["high", "low"]].reindex(e.index)
    e["smt_high"], e["smt_low"] = g["high"], g["low"]
    out["EURUSD"] = e
    pre = m15["GBPUSD"][(m15["GBPUSD"].index >= "2025-06-01") & (m15["GBPUSD"].index < m5["GBPUSD"].index[0])]
    g5 = pd.concat([pre, m5["GBPUSD"]])
    e5 = pd.concat([m15["EURUSD"][(m15["EURUSD"].index >= "2025-06-01") &
                                  (m15["EURUSD"].index < m5["EURUSD"].index[0])], m5["EURUSD"]])
    s = e5[["high", "low"]].reindex(g5.index)
    g5["smt_high"], g5["smt_low"] = s["high"], s["low"]
    out["GBPUSD"] = g5
    return out


def _init():
    from run_validate import load_pairs
    b = load_pairs(BASE)
    _BARS["hist"] = {k: b[k] for k in ("EURUSD", "GBPUSD")}
    _BARS["2026"] = _bars_2026()


def _cfg(pb, ps):
    c = copy.deepcopy(BASE)
    c["risk"]["risk_per_trade_pct"] = 1.0
    for s in c["strategies"]["morning"]:
        if s["name"] == "london_breakout":
            s.update(pb)
        if s["name"] == "london_sweep":
            s.update(ps)
    return c


def _run(job):
    """R by year (2021-2026) for one setting."""
    from fxbot.backtest import expand_units, pair_config, run_backtest
    pb, ps = job
    c = _cfg(pb, ps)
    units = {u["key"]: u for u in expand_units(c)}
    R = {y: 0.0 for y in YEARS + [2026]}
    n = {y: 0 for y in R}
    for src in ("hist", "2026"):
        for sym, bars in _BARS[src].items():
            cp = pair_config(c, units[sym])
            cp["smt"] = {}
            t, _ = run_backtest(bars, cp)
            if not len(t):
                continue
            yr = pd.to_datetime(t["entry_time"], utc=True).dt.year
            for y in R:
                if (src == "2026") == (y == 2026):
                    m = yr == y
                    R[y] += float(t.r_multiple[m].sum())
                    n[y] += int(m.sum())
    return dict(**{f"b_{k}": v for k, v in pb.items()}, **{f"s_{k}": v for k, v in ps.items()},
                **{f"R{y}": round(R[y], 2) for y in R}, **{f"n{y}": n[y] for y in n})


def _grid_jobs():
    jobs = []
    for vals in itertools.product(*GRID_B.values()):
        jobs.append((dict(zip(GRID_B, vals)), dict(LIVE_S)))
    for vals in itertools.product(*GRID_S.values()):
        ps = dict(zip(GRID_S, vals))
        if ps != LIVE_S:
            jobs.append((dict(LIVE_B), ps))
    return jobs


def _key(row, cols):
    return tuple("none" if pd.isna(row[c]) else row[c] for c in cols)


def plateau_best(df, cols, grid, years):
    """Setting with the best mean score over itself + its grid neighbours (one step on one axis)."""
    score = df[[f"R{y}" for y in years]].sum(axis=1)
    idx = {_key(r, cols): s for (_, r), s in zip(df.iterrows(), score)}
    levels = [[("none" if v is None else v) for v in grid[c.split("_", 1)[1]]] for c in cols]
    best, best_val = None, -1e9
    for k, s in idx.items():
        nb = [s]
        for i, lv in enumerate(levels):
            j = lv.index(k[i])
            for jj in (j - 1, j + 1):
                if 0 <= jj < len(lv):
                    kk = k[:i] + (lv[jj],) + k[i + 1:]
                    if kk in idx:
                        nb.append(idx[kk])
        v = float(np.mean(nb))
        if v > best_val:
            best, best_val = k, v
    return best, best_val, idx[best]


def main():
    out = "results/london_optimize.csv"
    if not os.path.exists(out):
        jobs = _grid_jobs()
        print(f"{len(jobs)} settings ...", flush=True)
        rows = []
        with Pool(6, initializer=_init) as pool:
            for k, r in enumerate(pool.imap_unordered(_run, jobs), 1):
                rows.append(r)
                if k % 10 == 0:
                    print(f"  {k}/{len(jobs)}", flush=True)
        pd.DataFrame(rows).to_csv(out, index=False)
    df = pd.read_csv(out)
    bcols = [f"b_{k}" for k in GRID_B]
    scols = [f"s_{k}" for k in GRID_S]
    is_live_s = np.all([df[c] == LIVE_S[c[2:]] for c in scols], axis=0)
    is_live_b = np.all([(df[c].isna() if LIVE_B[c[2:]] is None else df[c] == LIVE_B[c[2:]]) for c in bcols], axis=0)
    dB, dS = df[is_live_s].reset_index(drop=True), df[is_live_b].reset_index(drop=True)
    live = df[is_live_s & is_live_b].iloc[0]

    print("\n=== Walk-forward: limits picked on earlier years only, scored on the next year ===")
    rows = []
    for test_y in (2023, 2024, 2025, 2026):
        train = [y for y in YEARS if y < test_y]
        kb, vb, _ = plateau_best(dB, bcols, GRID_B, train)
        ks, vs, _ = plateau_best(dS, scols, GRID_S, train)
        rb = dB[[_key(r, bcols) == kb for _, r in dB.iterrows()]].iloc[0]
        rs = dS[[_key(r, scols) == ks for _, r in dS.iterrows()]].iloc[0]
        # combined effect on the test year = live + breakout change + sweep change (run jointly below)
        rows.append(dict(test_year=test_y, trained_on=f"{train[0]}-{train[-1]}",
                         breakout=dict(zip(GRID_B, kb)), sweep=dict(zip(GRID_S, ks)),
                         live_R=live[f"R{test_y}"], picked_breakout_R=rb[f"R{test_y}"],
                         picked_sweep_R=rs[f"R{test_y}"], live_n=int(live[f"n{test_y}"]),
                         picked_n=int(rb[f"n{test_y}"])))
    wf = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 80)
    print(wf.to_string(index=False))
    wf.to_csv("results/london_walkforward.csv", index=False)

    print("\n=== Top 10 breakout settings on 2021-25 (and how they did on unseen 2026) ===")
    dB["R21_25"] = dB[[f"R{y}" for y in YEARS]].sum(axis=1)
    print(dB.sort_values("R21_25", ascending=False).head(10)[bcols + ["R21_25"] + [f"R{y}" for y in YEARS]
                                                             + ["R2026", "n2026"]].to_string(index=False))
    print("\nlive:", {c: live[c] for c in bcols + scols}, " R21-25", round(sum(live[f"R{y}"] for y in YEARS), 1),
          " R2026", live["R2026"])
    dS["R21_25"] = dS[[f"R{y}" for y in YEARS]].sum(axis=1)
    print("\n=== Sweep settings (breakout at live) ===")
    print(dS.sort_values("R21_25", ascending=False)[scols + ["R21_25", "R2026", "n2026"]].to_string(index=False))


if __name__ == "__main__":
    main()
