"""Weekly live-vs-backtest check: did the bots do exactly what the backtest says they should?

    python run_fidelity.py                     # last 7 days, print only
    python run_fidelity.py --days 14
    python run_fidelity.py --since 2026-11-15
    python run_fidelity.py --telegram          # also send the summary to Telegram (.env)

Re-runs every unit's backtest on MT5's own candles, reads the bots' real trades from MT5
history (by magic number, same as run_report.py), and pairs them up per unit:
  MATCH        same unit, side and entry candle; result within --tol-r of the backtest
  R DIFFERS    same entry, but the result is off by more than --tol-r (fill, spread, exit)
  LIVE ONLY    the bot traded and the backtest did not -> a bug, a config change, or a
               hand-placed trade
  MISSED       the backtest traded and the bot did not -> the bot was down, or a live-only
               guard (portfolio risk cap, margin guard, spread guard, news feed) skipped it;
               the journal's SKIP lines for that market and hour are shown
Nov 17 2026: judge the bots by this, not by P/L, while the sample is small. A losing
week where everything MATCHes is normal variance; a mismatch means something to look at.
Writes results/fidelity_<date>.csv.
"""
import argparse
import glob
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import yaml

ENTRY_TOL = pd.Timedelta("10min")       # live fills ~5 s after the candle the backtest enters on


def compare(live, bt, tol_r=0.15):
    """Pair live and backtest trades. Both need unit, side (+1/-1), entry_time (UTC), R / r_multiple.
    Returns one row per trade with a status."""
    rows, used = [], set()
    for i, lt in live.iterrows():
        cand = bt[(bt.unit == lt.unit) & (bt.side == lt.side) & ~bt.index.isin(used)]
        cand = cand[(cand.entry_time - lt.entry_time).abs() <= ENTRY_TOL]
        row = dict(unit=lt.unit, side=lt.side, entry_time=lt.entry_time, live_R=lt.R, bt_R=None,
                   tag=lt.tag)
        if cand.empty:
            # the backtest only lists closed trades, so a trade still open can't be paired yet
            row["status"] = "OPEN (check later)" if lt.open else "LIVE ONLY"
        else:
            j = (cand.entry_time - lt.entry_time).abs().idxmin()
            used.add(j)
            row["bt_R"] = bt.loc[j, "r_multiple"]
            if lt.open or pd.isna(lt.R):
                row["status"] = "MATCH (still open)"
            elif abs(lt.R - row["bt_R"]) <= tol_r:
                row["status"] = "MATCH"
            else:
                row["status"] = "R DIFFERS"
        rows.append(row)
    for j, b in bt[~bt.index.isin(used)].iterrows():
        rows.append(dict(unit=b.unit, side=b.side, entry_time=b.entry_time, live_R=None,
                         bt_R=b.r_multiple, tag=b.tag, status="MISSED"))
    out = pd.DataFrame(rows, columns=["unit", "side", "entry_time", "status", "live_R", "bt_R", "tag"])
    return out.sort_values("entry_time").reset_index(drop=True)


def skip_lines(market, t, log_dir="logs", window=pd.Timedelta("45min")):
    """Journal SKIP lines for this market near time t (journal times are the PC's local clock)."""
    out = []
    local = t.tz_convert(datetime.now().astimezone().tzinfo).tz_localize(None)
    for f in sorted(glob.glob(os.path.join(log_dir, f"journal_{local:%Y%m%d}.log"))):
        for line in open(f, encoding="utf-8", errors="replace"):
            if f" {market} " not in line or " SKIP " not in line:
                continue
            try:
                ts = pd.Timestamp(line[:19])
            except ValueError:
                continue
            if abs(ts - local) <= window:
                out.append(line.strip()[:220])
    return out[:3]


def summary_text(res, since, until):
    n = len(res)
    bad = res[~res.status.str.startswith(("MATCH", "OPEN"))]
    head = (f"Live vs backtest {since:%b %d} - {until:%b %d}: {n} trade(s), "
            f"{n - len(bad)} match" + ("" if bad.empty else f", {len(bad)} MISMATCH"))
    lines = [head]
    for r in res.itertuples():
        side = "BUY" if r.side == 1 else "SELL"
        lr = "-" if pd.isna(r.live_R) else f"{r.live_R:+.2f}R"
        br = "-" if pd.isna(r.bt_R) else f"{r.bt_R:+.2f}R"
        lines.append(f"  {r.status:<18} {r.unit} {side} {r.entry_time:%a %d %H:%M} UTC  live {lr} | backtest {br}")
        if r.status == "MISSED":
            for s in skip_lines(r.unit.split(":")[0], r.entry_time):
                lines.append(f"      journal: {s}")
    if n == 0:
        lines.append("  No trades either way - nothing to compare.")
    elif bad.empty:
        lines.append("  All good: the bots did exactly what the backtest says. P/L swings are variance.")
    else:
        lines.append("  Look at the mismatches: LIVE ONLY = bug/config change/manual trade; MISSED = bot down "
                     "or a live guard skipped it; R DIFFERS = fill/spread/exit gap.")
    return "\n".join(lines)


def send_telegram(text):
    from dotenv import load_dotenv
    import requests
    load_dotenv()
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram not set up (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env) - not sent.")
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text[:3900], "disable_web_page_preview": True}, timeout=15)
    r.raise_for_status()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--since", help="UTC date, overrides --days")
    ap.add_argument("--tol-r", type=float, default=0.15, help="allowed live-vs-backtest R gap")
    ap.add_argument("--telegram", action="store_true")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    until = datetime.now(timezone.utc)
    since = (datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc) if a.since
             else until - timedelta(days=a.days))

    import MetaTrader5 as mt5
    from run_report import live_trades
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()} (is MetaTrader 5 open?)")
    live = live_trades(mt5, cfg, since)
    mt5.shutdown()
    if live.empty:
        live = pd.DataFrame(columns=["symbol", "side", "entry_time", "R", "open", "tag"])
    live = live.rename(columns={"symbol": "unit"})
    live["side"] = live["side"].map({"BUY": 1, "SELL": -1})
    live["entry_time"] = pd.to_datetime(live["entry_time"], utc=True)

    import run_portfolio as rp
    print("Re-running every unit's backtest on MT5 candles (about a minute) ...")
    bt = rp._units_trades(cfg, "mt5")
    bt["entry_time"] = pd.to_datetime(bt["entry_time"], utc=True)
    bt = bt[(bt.entry_time >= pd.Timestamp(since)) & (bt.entry_time <= pd.Timestamp(until))].reset_index(drop=True)

    res = compare(live, bt, a.tol_r)
    text = summary_text(res, since, until)
    print("\n" + text)
    os.makedirs("results", exist_ok=True)
    res.to_csv(f"results/fidelity_{until:%Y%m%d}.csv", index=False)
    if a.telegram:
        try:
            if send_telegram(text):
                print("Sent to Telegram.")
        except Exception as e:
            print(f"Telegram send failed: {e}")


if __name__ == "__main__":
    main()
