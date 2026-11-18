"""Whole-account replay (all bots, live sizing/caps/brake) with USDJPY breakout filter variants."""
import sys, os, yaml, numpy as np, pandas as pd
os.chdir(r"C:\Users\harsh\MoneyPrinter2"); sys.path.insert(0, os.getcwd())
import run_portfolio as rp
feat = pd.read_csv(sys.argv[1]); feat["entry_time"] = pd.to_datetime(feat.entry_time, utc=True)
MC = int(sys.argv[2]) if len(sys.argv) > 2 else 0
cfg = yaml.safe_load(open("config.yaml")); live = dict(cfg["live"]); max_lev = float(cfg["risk"]["max_leverage"])
RISK = float(cfg["risk"]["risk_per_trade_pct"])
data = {}
for src in ("hist", "mt5"):
    t = rp.load_trades(cfg, src).reset_index(drop=True)
    f = feat[feat.src == src][["entry_time", "tag", "close_loc", "past", "with_trend"]]
    t = t.merge(f, on=["entry_time", "tag"], how="left")
    vbo = (t.unit == "USDJPY") & t.tag.str.startswith("vbo")
    miss = vbo & t.close_loc.isna()
    print(f"{src}: {vbo.sum()} USDJPY breakout trades, {miss.sum()} without features")
    t["vbo"] = vbo
    data[src] = t
periods = {"2021-23": ("hist", "2021-01-01", "2024-01-01"), "2024-25": ("hist", "2024-01-01", "2026-01-01"),
           "2026": ("mt5", "2026-01-01", "2027-01-01")}
def weak(t): return t.close_loc <= 0.77
def far(t): return t.past > 0.114
def ctr(t): return t.with_trend == False
V = {  # variant -> size multiplier for each USDJPY breakout trade (0 = skipped)
    "A live (filter off)":            lambda t: 1.0,
    "B skip weak close":              lambda t: np.where(weak(t), 0, 1.0),
    "C skip far past level":          lambda t: np.where(far(t), 0, 1.0),
    "D skip weak OR far":             lambda t: np.where(weak(t) | far(t), 0, 1.0),
    "E half size if weak OR far":     lambda t: np.where(weak(t) | far(t), .5, 1.0),
    "F trend filter on (pre Nov 14)": lambda t: np.where(ctr(t), 0, 1.0),
    "G trend on + skip weak OR far":  lambda t: np.where(ctr(t) | weak(t) | far(t), 0, 1.0),
    "H counter-trend only if strong": lambda t: np.where(ctr(t) & (weak(t) | far(t)), 0, 1.0),
}
def apply(t, fn):
    t = t.copy(); m = np.ones(len(t)); m[t.vbo.to_numpy()] = np.asarray(fn(t[t.vbo]) * np.ones(t.vbo.sum()))
    t["r_multiple"] *= m; t["lev_per_1pct"] *= m
    return t[m > 0].reset_index(drop=True)
rows = []
for name, fn in V.items():
    row = {"variant": name}
    for p, (src, a, b) in periods.items():
        t = data[src]; t = t[(t.entry_time >= a) & (t.entry_time < b)].reset_index(drop=True)
        t = apply(t, fn)
        eq, taken = rp.replay(t, RISK, live, max_lev); s = rp.stats(eq)
        u = t[t.vbo & taken]
        row[f"{p} month%"] = s["geo_month"]; row[f"{p} DD%"] = s["maxdd"]; row[f"{p} worst mo"] = s["worst_month"]
        row[f"{p} jpy tr/fakes"] = f"{len(u)}/{int((u.r_multiple < -0.45).sum())}"
    if MC:
        t = data["hist"]; t = apply(t[(t.entry_time >= "2021-01-01") & (t.entry_time < "2026-01-01")].reset_index(drop=True), fn)
        m = rp.monte_carlo(t, RISK, live, max_lev, MC)
        row["MC21-25 month p10"] = m["geo_p10"]; row["MC month median"] = m["geo_med"]; row["MC DD med"] = m["dd_median"]; row["MC DD 1in100"] = m["dd_p99"]
    rows.append(row); print(name, "done", flush=True)
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 50)
out = pd.DataFrame(rows).set_index("variant"); print(out.T.to_string())
out.to_csv(sys.argv[1].replace("feat_both", "fakeout_sim_results"))
