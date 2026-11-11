"""Trading journal: the important bot events, in three places.

1. logs/journal_<date>.log - ONE combined file for all market bots (progress at a glance)
2. <MT5 Common>/Files/fxbot_events_<SYMBOL>.txt - read by the FxbotOverlay indicator,
   which prints new lines into MT5's Experts tab
3. the bot's own terminal window / log (unchanged: everything goes there anyway)

Implemented as a logging.Handler on the "fxbot" logger, so every existing log call
that matters (orders, fills, stop moves, closes, skips, status, errors, daily
summaries) is journaled without touching the call sites.
"""
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

# Which log lines are journal-worthy, and the short label each gets
EVENT_PATTERNS = [
    (re.compile(r"\bORDER (BUY|SELL)\b"), "ORDER"),
    (re.compile(r"Order filled"), "FILLED"),
    (re.compile(r"order_send failed|close_position failed|update_stop failed"), "ORDER ERROR"),
    (re.compile(r"Stop moved"), "STOP"),
    (re.compile(r"Closing position|Position closed"), "CLOSE"),
    (re.compile(r"^CLOSED|\bCLOSED "), "CLOSED"),
    (re.compile(r"RISK CAP"), "SKIP"),
    (re.compile(r"\bNEWS\b"), "NEWS"),
    (re.compile(r"not traded"), "SKIP"),
    (re.compile(r"DAILY SUMMARY"), "DAILY"),
    (re.compile(r"Bot started|bot: \d+ strateg|Bot stopped"), "BOT"),
    (re.compile(r"\bSTATUS\b"), "STATUS"),
]
MAX_EVENTS_FILE = 512 * 1024        # MT5 events file is trimmed past this size


def classify(msg):
    for rx, label in EVENT_PATTERNS:
        if rx.search(msg):
            return label
    return None


class JournalHandler(logging.Handler):
    def __init__(self, market, mt5_events_path=None, log_dir="logs"):
        super().__init__(level=logging.INFO)
        self.market = market
        self.mt5_path = mt5_events_path
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

    def _combined_path(self):
        return self.log_dir / f"journal_{datetime.now().strftime('%Y%m%d')}.log"

    @staticmethod
    def _append(path, line):
        for _ in range(3):                      # three bots share the combined file
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return
            except OSError:
                time.sleep(0.05)

    def emit(self, record):
        try:
            msg = record.getMessage()
            label = "ERROR" if record.levelno >= logging.ERROR else classify(msg)
            if label is None:
                return
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            text = msg.replace("STATUS ", "", 1) if label == "STATUS" else msg
            self._append(self._combined_path(), f"{stamp} {self.market:<6} {label:<11} {text}")
            if self.mt5_path:
                self._trim()
                utc = datetime.now(timezone.utc).strftime("%H:%M")
                # ASCII only: the MT5 indicator reads the file as ANSI
                self._append(self.mt5_path, f"{label}|{utc} UTC {text}".encode("ascii", "replace").decode())
        except Exception:                       # journaling must never stop trading
            pass

    def _trim(self):
        try:
            if os.path.getsize(self.mt5_path) > MAX_EVENTS_FILE:
                with open(self.mt5_path, "r", encoding="utf-8", errors="replace") as f:
                    keep = f.readlines()[-200:]
                with open(self.mt5_path, "w", encoding="utf-8") as f:
                    f.writelines(keep)
        except OSError:
            pass


def attach(logger, market, mt5_common_files_dir=None, symbol=None, log_dir="logs"):
    """Attach (once) a JournalHandler to `logger` for this market bot."""
    for h in logger.handlers:
        if isinstance(h, JournalHandler):
            return h
    mt5_path = None
    if mt5_common_files_dir and symbol:
        mt5_path = str(Path(mt5_common_files_dir) / f"fxbot_events_{symbol}.txt")
    h = JournalHandler(market, mt5_path, log_dir)
    logger.addHandler(h)
    return h
