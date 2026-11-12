"""Write what the strategies "see" to a file the MT5 FxbotOverlay indicator draws.

File: <MT5 common data>/Files/fxbot_<SYMBOL>.txt  (one item per line, '|'-separated)
  STATUS|<text>
  HLINE|<price>|<r,g,b>|<solid|dash|dot>|<label>
  BOX|<t1 server epoch>|<price1>|<t2 server epoch>|<price2>|<r,g,b>|<label>
  VLINE|<t server epoch>|<r,g,b>|<solid|dash|dot>|<label>          (a moment in time)
  TLINE|<t1 server epoch>|<price>|<r,g,b>|<solid|dash|dot>|<label>  (level from t1 to the right edge)
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from .data import utc_to_server_epoch

LONDON = "Europe/London"

COLORS = {
    "dodgerblue": "30,144,255", "steelblue": "70,130,180", "orangered": "255,69,0",
    "gold": "255,215,0", "seagreen": "46,139,87", "dimgray": "105,105,105",
    "silver": "192,192,192", "white": "255,255,255", "red": "220,20,60", "violet": "186,85,211",
}


def _rgb(name):
    return COLORS.get(name, COLORS["white"])


def london_today_utc(minute_of_day, now_utc=None):
    """Today's London time `minute_of_day` (e.g. 600 = 10:00) as a UTC timestamp."""
    now = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now
    day = now.tz_convert(LONDON).normalize()
    return (day + pd.Timedelta(minutes=int(minute_of_day))).tz_convert("UTC")


def position_rows(pos, be_r=None):
    """Entry / stop / target / +1R lines for an open trade, drawn from its entry time."""
    t0 = utc_to_server_epoch(pos.entry_time)
    side = "BUY" if pos.side == 1 else "SELL"
    rows = [f"TLINE|{t0}|{pos.entry_price:.5f}|{_rgb('white')}|solid|{side} entry ({pos.tag})",
            f"TLINE|{t0}|{pos.stop_loss:.5f}|{_rgb('red')}|solid|STOP (on the broker's server)"]
    if pos.take_profit:
        rows.append(f"TLINE|{t0}|{pos.take_profit:.5f}|{_rgb('seagreen')}|solid|TARGET")
    r = (pos.entry_price - pos.stop_loss) * pos.side
    if r > 0:                                   # 0 once the stop is at breakeven
        lbl = "+1R: stop moves to breakeven here" if be_r else "+1R (profit = the amount risked)"
        rows.append(f"TLINE|{t0}|{pos.entry_price + pos.side * r:.5f}|{_rgb('gold')}|dot|{lbl}")
    elif (pos.stop_loss - pos.entry_price) * pos.side >= 0:
        rows[1] = rows[1].replace("STOP (on the broker's server)", "STOP at breakeven or better (locked in)")
    return rows


def news_rows(events, now_utc=None, hours=24, blackout_min=30):
    """Vertical lines at the next high-impact releases (already filtered to this market)."""
    if events is None or not len(events):
        return []
    now = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now
    m = (events["time"] >= now - pd.Timedelta(minutes=blackout_min)) &         (events["time"] <= now + pd.Timedelta(hours=hours))
    out = []
    for _, ev in events[m].head(6).iterrows():
        lbl = f"NEWS {ev['currency']} {ev['event']} - no new entries +/-{blackout_min} min".replace("|", "/")
        out.append(f"VLINE|{utc_to_server_epoch(ev['time'])}|{_rgb('violet')}|dash|{lbl}")
    return out


def build_lines(strategies, local_min, broker=None, symbol=""):
    rows, status = [], []
    seen_v = set()
    for s in strategies:
        if not hasattr(s, "describe"):
            continue
        try:
            d = s.describe(local_min)
        except TypeError:
            d = s.describe()
        if d.get("status"):
            status.append(d["status"])
        for ln in d.get("lines", []):
            label = ln.get("label", "").replace("|", "/")
            rows.append(f"HLINE|{ln['price']:.5f}|{_rgb(ln.get('color'))}|{ln.get('style', 'solid')}|{label}")
        for v in d.get("vlines", []):
            key = (v["min"], v["label"])
            if key in seen_v or v["min"] >= 24 * 60:
                continue
            seen_v.add(key)
            t = utc_to_server_epoch(london_today_utc(v["min"]))
            hm = f"{v['min'] // 60:02d}:{v['min'] % 60:02d}"
            rows.append(f"VLINE|{t}|{_rgb(v.get('color'))}|{v.get('style', 'dot')}|"
                        f"{hm} London: {v['label']}".replace("||", "|"))
        for b in d.get("boxes", []):
            rows.append(f"BOX|{utc_to_server_epoch(b['t1'])}|{b['p1']:.5f}|{utc_to_server_epoch(b['t2'])}|"
                        f"{b['p2']:.5f}|{_rgb(b.get('color'))}|{b.get('label', '').replace('|', '/')}")
    if broker is not None:
        pos = broker.position()
        if pos is not None:
            be = any(getattr(st, "be", 0) or getattr(st, "trail_be_rr", 0) for st in strategies)
            rows += position_rows(pos, be)
            status.insert(0, f"IN TRADE: {'BUY' if pos.side == 1 else 'SELL'} {pos.units} @ {pos.entry_price:.5f} "
                             f"SL {pos.stop_loss:.5f} TP {pos.take_profit or 0:.5f} ({pos.tag})")
    header = f"fxbot {symbol} | updated {time.strftime('%H:%M:%S')}"
    return [f"STATUS|{header}"] + [f"STATUS|{s}" for s in status] + rows


def write_overlay(path, lines):
    """Atomic-ish write; the indicator may be reading, so retry briefly."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(lines) + "\n")
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            time.sleep(0.2)
    return False
