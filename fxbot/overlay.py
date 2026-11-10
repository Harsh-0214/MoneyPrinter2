"""Write what the strategies "see" to a file the MT5 FxbotOverlay indicator draws.

File: <MT5 common data>/Files/fxbot_<SYMBOL>.txt  (one item per line, '|'-separated)
  STATUS|<text>
  HLINE|<price>|<r,g,b>|<solid|dash|dot>|<label>
  BOX|<t1 server epoch>|<price1>|<t2 server epoch>|<price2>|<r,g,b>|<label>
"""
import os
import time

from .data import utc_to_server_epoch

COLORS = {
    "dodgerblue": "30,144,255", "steelblue": "70,130,180", "orangered": "255,69,0",
    "gold": "255,215,0", "seagreen": "46,139,87", "dimgray": "105,105,105",
    "silver": "192,192,192", "white": "255,255,255",
}


def _rgb(name):
    return COLORS.get(name, COLORS["white"])


def build_lines(strategies, local_min, broker=None, symbol=""):
    rows, status = [], []
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
        for b in d.get("boxes", []):
            rows.append(f"BOX|{utc_to_server_epoch(b['t1'])}|{b['p1']:.5f}|{utc_to_server_epoch(b['t2'])}|"
                        f"{b['p2']:.5f}|{_rgb(b.get('color'))}|{b.get('label', '').replace('|', '/')}")
    if broker is not None:
        pos = broker.position()
        if pos is not None:
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
