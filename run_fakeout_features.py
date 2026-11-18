"""Record breakout-candle features for every USDJPY vol-breakout trade (hist + mt5).

    python run_fakeout_features.py results/fakeout_features.csv
    python run_fakeout_sim.py results/fakeout_features.csv [reshuffles]
"""
import sys, copy, yaml, pandas as pd
sys.path.insert(0, r"C:\Users\harsh\MoneyPrinter2")
import os; os.chdir(r"C:\Users\harsh\MoneyPrinter2")
from fxbot.strategies import daily_patterns as dp
from fxbot.backtest import expand_units, pair_config, run_backtest
import run_portfolio as rp

REC = []
orig = dp.VolBreakout.propose
def propose(self, bar, day, lmin, broker, risk):
    p = orig(self, bar, day, lmin, broker, risk)
    if p is not None and not self.add_on_r:
        up, dn, rng, trend, yc = self.levels
        s = p.order.side
        hi, lo, c = bar.high, bar.low, bar.close
        cl = ((c - lo) if s == 1 else (hi - c)) / (hi - lo) if hi > lo else 0.5
        lvl = up if s == 1 else dn
        REC.append(dict(t=bar.Index, side=s, close_loc=cl, past=(c - lvl) * s / rng,
                        body=abs(c - bar.open) / rng, lmin=lmin, rng_pips=rng / 0.01,
                        with_trend=(lambda t5: None if t5 is None else bool((yc - t5) * s >= 0))(self.d.sma(50)),
                        try_no=self.n_traded + 1))
    return p
dp.VolBreakout.propose = propose

cfg = yaml.safe_load(open("config.yaml"))
base = copy.deepcopy(cfg); base["risk"]["risk_per_trade_pct"] = 1.0; base["risk"]["max_leverage"] = 1000
out = []
for src in ("hist", "mt5"):
    if src == "hist":
        from run_validate import load_pairs; bars = load_pairs(base)
    else:
        bars = rp._mt5_bars(base)
    for u in expand_units(base):
        if u["key"] != "USDJPY" or u["key"] not in bars: continue
        c = pair_config(base, u); c["smt"] = {}
        c["risk"]["risk_per_trade_pct"] = 1.0; c["risk"]["max_leverage"] = 1000
        # with_trend needs the 50-day average even though live has the filter off
        REC.clear()
        for s in c.get("strategies", []) if isinstance(c.get("strategies"), list) else []:
            pass
        t, _ = run_backtest(bars[u["key"]], c)
        f = pd.DataFrame(REC)
        t = t[t.tag.str.startswith("vbo")].copy()
        t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
        f["t"] = pd.to_datetime(f["t"], utc=True)
        m = pd.merge_asof(t.sort_values("entry_time"), f.sort_values("t"), left_on="entry_time",
                          right_on="t", direction="backward", tolerance=pd.Timedelta("30min"))
        m["src"] = src; out.append(m)
d = pd.concat(out)
d.to_csv(sys.argv[1], index=False)
print(len(d), "trades,", d.close_loc.isna().sum(), "unmatched", d.entry_time.min(), d.entry_time.max())
