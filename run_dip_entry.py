"""Enter on the dip after a breakout signal instead of at the breakout ("buy the retest").

    python run_dip_entry.py

When a strategy signals, the order becomes a limit order part of the way back towards its stop:
    limit = signal price - side x f x (signal price - stop)
It fills if price comes back to it within the timeout, otherwise the trade is skipped. Same stop,
same target and exits; size re-computed for the smaller stop distance (still 1% risk), so a
filled dip trade risks the same money with a better price.
Units: EURUSD and GBPUSD London (Breakout + Sweep), USDJPY breakout, gold 55-day and 20-day trend.
Scored in R: 2021-23 / 2024-25 histdata, 2026 broker feed. Also: what the skipped trades
(signals that never dipped) would have made at the breakout price.
"""
import itertools
from multiprocessing import Pool

import pandas as pd
import yaml

import fxbot.backtest as BT
from fxbot.brokers.base import Position
from fxbot.brokers.sim_broker import SimBroker

BASE = yaml.safe_load(open("config.yaml"))
GRID = {"EURUSD": ([0.1, 0.2, 0.33, 0.5], [60, 120, 240]),
        "GBPUSD": ([0.1, 0.2, 0.33, 0.5], [60, 120, 240]),
        "USDJPY": ([0.1, 0.2, 0.33, 0.5], [60, 120, 240]),
        "XAUUSD": ([0.1, 0.25, 0.5], [1440, 4320]),
        "XAUUSD:fast": ([0.1, 0.25, 0.5], [1440, 4320])}
_BARS = {}


class DipBroker(SimBroker):
    f, timeout_min = 0.0, 0

    def submit(self, order):
        if self.f <= 0:
            return super().submit(order)
        if self._pos is not None or self._pending_order is not None or getattr(self, "_limit", None):
            return False
        px = self._bar.close + (self._bar.spread_pips * self.pip if order.side == 1 else 0.0)
        dist = (px - order.stop_loss) * order.side
        if dist <= 0:
            return False
        limit = px - order.side * self.f * dist
        self._limit = (order, limit, dist, self._bar.Index + pd.Timedelta(minutes=self.timeout_min),
                       self._bar.Index)
        return True

    def on_bar(self, bar):
        lim = getattr(self, "_limit", None)
        if lim is not None and self._pos is None:
            o, limit, dist0, expire, t0 = lim
            spread = bar.spread_pips * self.pip
            if bar.Index > expire:
                self._limit = None
                self.missed.append(t0)
            else:
                lo = bar.low + (spread if o.side == 1 else 0.0)          # long fills on the ask
                hi = bar.high + (spread if o.side == -1 else 0.0)        # short fills on the ask too
                touched = lo <= limit if o.side == 1 else bar.high >= limit
                if touched:
                    open_px = bar.open + (spread if o.side == 1 else 0.0)
                    entry = min(open_px, limit) if o.side == 1 else max(bar.open, limit)
                    risk = (entry - o.stop_loss) * o.side
                    self._limit = None
                    if risk > 0:
                        units = int(o.units * dist0 / risk)
                        self._pos = Position(o.side, units, entry, bar.Index, o.stop_loss, o.take_profit,
                                             risk, 0.0, o.tag)
                        if self.swap_long or self.swap_short or self.swap_long_pct or self.swap_short_pct:
                            self._roll_key = self._roll_day(bar.Index)
                        # conservative: if the same bar also reached the stop, it's stopped
                        if (o.side == 1 and bar.low <= o.stop_loss) or (o.side == -1 and hi >= o.stop_loss):
                            self._bar = bar
                            self._exit(bar.Index, o.stop_loss - o.side * self.slip, "stop")
                            return
                        self._bar = bar
                        return                                           # stops/targets from next bar
        super().on_bar(bar)


def _init():
    from run_validate import load_pairs
    from run_london_optimize import _bars_2026
    from run_more_trades import mt5_bars
    hist = load_pairs(BASE)
    b26 = _bars_2026()
    _BARS["hist"] = {k: hist[k] for k in GRID}
    g = mt5_bars("XAUUSD", "H1", 0.1, 8.0)
    _BARS["2026"] = {"EURUSD": b26["EURUSD"], "GBPUSD": b26["GBPUSD"],
                     "USDJPY": mt5_bars("USDJPY", "M15", 0.01, 1.6), "XAUUSD": g, "XAUUSD:fast": g}


def _bt(unit, bars, f, tmo):
    units = {u["key"]: u for u in BT.expand_units(BASE)}
    c = BT.pair_config(BASE, units[unit])
    c["smt"] = {}
    c["risk"]["risk_per_trade_pct"] = 1.0
    c["risk"]["max_leverage"] = 1000
    DipBroker.f, DipBroker.timeout_min = f, tmo
    DipBroker.missed = []
    orig = BT.SimBroker
    BT.SimBroker = DipBroker
    try:
        t, _ = BT.run_backtest(bars, c)
    finally:
        BT.SimBroker = orig
    if len(t):
        t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    return t, list(DipBroker.missed)


def _run(job):
    unit, f, tmo = job
    out = dict(unit=unit, f=f, timeout_h=tmo / 60 if tmo else None)
    for src in ("hist", "2026"):
        t, missed = _bt(unit, _BARS[src][unit], f, tmo)
        yr = t.entry_time.dt.year if len(t) else pd.Series(dtype=int)
        if src == "hist":
            out.update(n=int((yr <= 2025).sum()), R21_23=round(t.r_multiple[yr <= 2023].sum(), 2),
                       R24_25=round(t.r_multiple[(yr >= 2024) & (yr <= 2025)].sum(), 2),
                       missed=len([m for m in missed if m.year <= 2025]))
            out["_missed_hist"] = missed
        else:
            o = t[yr == 2026] if len(t) else t
            out.update(n26=len(o), R26=round(o.r_multiple.sum(), 2) if len(o) else 0.0)
            out["_missed_26"] = missed
    return out


def main():
    jobs = [(u, 0.0, 0) for u in GRID] + [(u, f, tmo) for u, (fs, ts) in GRID.items()
                                          for f, tmo in itertools.product(fs, ts)]
    print(f"{len(jobs)} runs ...", flush=True)
    with Pool(6, initializer=_init) as pool:
        rows = list(pool.imap_unordered(_run, jobs))
    df = pd.DataFrame(rows)
    base = df[df.f == 0].set_index("unit")
    # what did the never-dipped signals make at the breakout price? (baseline trades at those times)
    _init()
    base_trades = {}
    for u in GRID:
        th, _ = _bt(u, _BARS["hist"][u], 0.0, 0)
        t6, _ = _bt(u, _BARS["2026"][u], 0.0, 0)
        base_trades[u] = pd.concat([th[th.entry_time.dt.year <= 2025], t6[t6.entry_time.dt.year == 2026]])
    miss_R = []
    for _, r in df.iterrows():
        if r.f == 0:
            miss_R.append(None)
            continue
        bt = base_trades[r.unit]
        sig = pd.DatetimeIndex(list(r._missed_hist) + list(r._missed_26))
        # a baseline trade enters on the bar after the signal bar
        hit = bt[bt.entry_time.isin(sig + _bar_len(r.unit))]        # baseline enters one bar after the signal
        miss_R.append(round(hit.r_multiple.sum(), 1))
    df["missed_trades_R_at_breakout"] = miss_R
    for col in ("R21_23", "R24_25", "R26"):
        df[f"d_{col}"] = (df[col] - df.unit.map(base[col])).round(2)
    df["better_all"] = (df.d_R21_23 > 0) & (df.d_R24_25 > 0) & (df.d_R26 > 0)
    df = df.drop(columns=["_missed_hist", "_missed_26"]).sort_values(["unit", "f", "timeout_h"])
    df.to_csv("results/dip_entry.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(df.to_string(index=False))


def _bar_len(unit):
    tf = BT.pair_config(BASE, {u["key"]: u for u in BT.expand_units(BASE)}[unit])["data"]["timeframe"]
    return pd.Timedelta(tf)


if __name__ == "__main__":
    main()
