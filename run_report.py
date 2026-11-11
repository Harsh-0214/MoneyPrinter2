"""Demo/live results vs what the backtest expects.

    python run_report.py                    # all bot trades on the account so far
    python run_report.py --since 2026-11-01
    python run_report.py --refresh          # recompute the backtest expectations

Reads the bot's own trades from MT5 history (by magic number, one per pair in
config.yaml), works out each trade's result in R from its ORIGINAL stop, the
fill slippage, and compares win rate / average R / trades per week with the
2021-2025 backtest of the same strategy on the same market.
Writes results/live_trades.csv.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import yaml

EXPECTED_FILE = "results/expected_stats.json"


def strategy_of(tag):
    tag = str(tag or "")
    if tag.startswith("sweep_"):
        return "London Sweep"
    if tag.endswith("_break"):
        return "London Breakout"
    if tag.startswith("trend_"):
        return "Gold trend"
    return tag or "unknown"


def expected_stats(cfg, refresh=False):
    """Backtest stats per (symbol, strategy), cached in results/expected_stats.json."""
    if os.path.exists(EXPECTED_FILE) and not refresh:
        with open(EXPECTED_FILE) as f:
            return json.load(f)
    print("Computing backtest expectations (about a minute) ...")
    from run_validate import load_pairs, run_multi
    t, _ = run_multi(load_pairs(cfg), cfg)
    t["strategy"] = t.tag.map(strategy_of)
    out = {}
    for (sym, st), g in t.groupby(["symbol", "strategy"]):
        out[f"{sym}|{st}"] = {"trades_per_week": len(g) / (5 * 52), "win_rate": float((g.pnl > 0).mean()),
                              "avg_r": float(g.r_multiple.mean()), "n": int(len(g))}
    os.makedirs("results", exist_ok=True)
    with open(EXPECTED_FILE, "w") as f:
        json.dump(out, f, indent=1)
    return out


def live_trades(mt5, cfg, since):
    from fxbot.data import server_ts_to_utc
    base = int(cfg["live"]["magic"])
    magics = {base + i: p["symbol"] for i, p in enumerate(cfg["pairs"])}
    pips = {p["symbol"]: p.get("instrument", {}).get("pip", 0.0001) for p in cfg["pairs"]}
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc) + timedelta(days=1)) or []
    by_pos = {}
    for d in deals:
        if d.magic in magics:
            by_pos.setdefault(d.position_id, []).append(d)
    rows = []
    for pid, ds in by_pos.items():
        ins = [d for d in ds if d.entry == mt5.DEAL_ENTRY_IN]
        outs = [d for d in ds if d.entry == mt5.DEAL_ENTRY_OUT]
        if not ins:
            continue
        e = ins[0]
        sym = magics[e.magic]
        side = 1 if e.type == mt5.DEAL_TYPE_BUY else -1
        orders = mt5.history_orders_get(position=pid) or []
        first = min(orders, key=lambda o: o.time_setup_msc) if orders else None
        sl = first.sl if first and first.sl else None
        requested = first.price_open if first and first.price_open else e.price
        slip_pips = (e.price - requested) * side / pips[sym]       # + = worse than asked
        pnl = sum(d.profit + d.commission + d.swap for d in ds)
        row = dict(symbol=sym, strategy=strategy_of(e.comment), tag=e.comment, side="BUY" if side == 1 else "SELL",
                   volume=e.volume, entry_time=server_ts_to_utc([e.time])[0], entry=e.price, stop=sl,
                   slippage_pips=round(slip_pips, 2), pnl=round(pnl, 2), open=not outs)
        if outs:
            x = outs[-1]
            row.update(exit_time=server_ts_to_utc([x.time])[0], exit=x.price, exit_reason=x.comment)
            if sl:
                risk_money = abs(mt5.order_calc_profit(e.type, e.symbol, e.volume, e.price, sl) or 0)
                row["R"] = round(pnl / risk_money, 3) if risk_money else None
        rows.append(row)
    return pd.DataFrame(rows).sort_values("entry_time") if rows else pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--since", default="2026-11-01")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config))
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()} (is MetaTrader 5 open?)")
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    acct = mt5.account_info()
    t = live_trades(mt5, cfg, since)
    mt5.shutdown()
    exp = expected_stats(cfg, args.refresh)

    print(f"\nAccount {acct.login} ({acct.currency})  balance {acct.balance:,.2f}  equity {acct.equity:,.2f}")
    if t.empty:
        print(f"No bot trades since {args.since}.")
        return
    os.makedirs("results", exist_ok=True)
    t.to_csv("results/live_trades.csv", index=False)
    weeks = max((datetime.now(timezone.utc) - since).days / 7, 1 / 7)
    pd.set_option("display.width", 220)
    cols = ["symbol", "strategy", "side", "volume", "entry_time", "entry", "stop", "exit", "exit_reason",
            "pnl", "R", "slippage_pips"]
    print("\n=== TRADES ===")
    print(t[[c for c in cols if c in t]].to_string(index=False))

    print(f"\n=== LIVE vs BACKTEST  ({weeks:.1f} weeks) ===")
    closed = t[~t.open]
    for (sym, st), g in t.groupby(["symbol", "strategy"]):
        c = closed[(closed.symbol == sym) & (closed.strategy == st)]
        e = exp.get(f"{sym}|{st}")
        n = len(c)
        live_wr = (c.pnl > 0).mean() * 100 if n else float("nan")
        live_r = c["R"].mean() if n and "R" in c else float("nan")
        line = (f"{sym} {st}: {len(g)} trades ({len(g) / weeks:.1f}/wk), {n} closed | "
                f"win {live_wr:.0f}%  avg {live_r:+.2f}R  P/L {c.pnl.sum():+,.2f}")
        if e:
            line += (f"  ||  backtest: {e['trades_per_week']:.1f}/wk  win {e['win_rate'] * 100:.0f}%  "
                     f"avg {e['avg_r']:+.2f}R")
        print(line)
    n_closed = len(closed)
    print(f"\nTotal P/L {closed.pnl.sum():+,.2f} {acct.currency} over {n_closed} closed trades. "
          f"Average entry slippage {t.slippage_pips.mean():+.2f} pips.")
    if n_closed < 30:
        print(f"Only {n_closed} closed trades - too few to judge yet (aim for 30+; win rate can swing "
              f"+/-20% on small samples).")


if __name__ == "__main__":
    main()
