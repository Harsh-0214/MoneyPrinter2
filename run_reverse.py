"""USDJPY breakout: (a) fade every signal, (b) stop-and-reverse after a stop-out. R per period."""
import os, sys, copy, yaml, numpy as np, pandas as pd
os.chdir(r"C:\Users\harsh\MoneyPrinter2"); sys.path.insert(0, os.getcwd())
from fxbot.strategies import daily_patterns as dp
from fxbot.backtest import expand_units, pair_config, run_backtest
import run_portfolio as rp
from run_validate import load_pairs

cfg = yaml.safe_load(open("config.yaml"))
base = copy.deepcopy(cfg); base["risk"]["risk_per_trade_pct"] = 1.0; base["risk"]["max_leverage"] = 1000
u = [x for x in expand_units(base) if x["key"] == "USDJPY"][0]
c = pair_config(base, u); c["smt"] = {}; c["risk"]["risk_per_trade_pct"] = 1.0; c["risk"]["max_leverage"] = 1000
SPREAD = float(u.get("costs", {}).get("spread_pips", 1.6)) * 0.01
bars = {"hist": load_pairs(base)["USDJPY"], "mt5": rp._mt5_bars(base)["USDJPY"]}
orig = dp.VolBreakout.propose

def fade(self, bar, day, lmin, broker, risk):
    p = orig(self, bar, day, lmin, broker, risk)
    if p is None or self.add_on_r:
        return p
    o = p.order; dist = abs(bar.close - o.stop_loss)
    n = dp._order(-o.side, bar.close, bar.close + o.side * dist, None, bar, self.pip, broker, risk,
                  "vbo_long" if o.side == -1 else "vbo_short")
    return dp.TradeProposal(n, p.score, p.strategy_name) if n else None

def period(ts):
    y = ts.year
    return "2021-23" if y <= 2023 else "2024-25" if y <= 2025 else "2026"

def run(src, patched):
    dp.VolBreakout.propose = fade if patched else orig
    t, _ = run_backtest(bars[src], c)
    dp.VolBreakout.propose = orig
    t = t[t.tag.str.startswith("vbo")].copy()
    t["entry_time"] = pd.to_datetime(t.entry_time, utc=True); t["exit_time"] = pd.to_datetime(t.exit_time, utc=True)
    return t[(t.entry_time >= "2021-01-01") & (t.entry_time < "2026-01-01")] if src == "hist" else t[t.entry_time >= "2026-01-01"]

def sar(t, b):
    """After each stop-out: enter the other way at the stop price, same distance, BE at +1R, out 21:00."""
    out = []
    lon = b.index.tz_convert("Europe/London")
    for r in t[t.exit_reason.str.startswith("stop") & (t.r_multiple <= -0.9)].itertuples():
        side = -r.side; dist = abs(r.exit_price - r.entry_price)
        entry = r.exit_price + (SPREAD if side == 1 else 0); stop = entry - side * dist
        day_end = r.exit_time.tz_convert("Europe/London").normalize() + pd.Timedelta(hours=21)
        w = b[(b.index > r.exit_time) & (lon <= day_end)]
        res = None; be = False
        for x in w.itertuples():
            adverse = x.low if side == 1 else x.high + SPREAD
            fav = x.high if side == 1 else x.low + SPREAD
            if (adverse - stop) * side <= 0:
                res = (stop - entry) * side / dist; break
            if not be and (fav - entry) * side >= dist:
                be = True; stop = entry
        if res is None:
            last = w.close.iloc[-1] if len(w) else entry
            res = ((last - (SPREAD if side == -1 else 0)) - entry) * side / dist if len(w) else 0.0
        out.append(dict(entry_time=r.exit_time, R=res))
    return pd.DataFrame(out)

rows = []
for src in ("hist", "mt5"):
    live, fd = run(src, False), run(src, True)
    s = sar(live, bars[src])
    for name, d, col in (("live breakout", live, "r_multiple"), ("(a) fade every breakout", fd, "r_multiple"),
                         ("(b) reverse after stop-out (extra trades)", s, "R")):
        for p, g in d.groupby(d.entry_time.map(period)):
            rows.append(dict(rule=name, period=p, trades=len(g), win=(g[col] > 0.1).mean() * 100,
                             avgR=g[col].mean(), totR=g[col].sum()))
r = pd.DataFrame(rows).pivot_table(index="rule", columns="period", values=["trades", "avgR", "totR"], sort=False)
print(r.round(2).to_string())
