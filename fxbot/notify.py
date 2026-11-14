"""Phone notifications: the bot's important terminal lines, sent to Telegram.

Off unless TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env (python setup_telegram.py
fills in the chat id). Settings in config.yaml under live.telegram:

    telegram:
      enabled: true          # false = never send, even with the .env values set
      skips: true            # also send "did not trade" lines (about 1-3 a day per market)
      daily_summary: true    # the start-of-day summary per market

What is sent: trade wanted / sized / sent / filled, stop moves, trade closed with P/L,
skipped trades (news, spread, margin, risk cap, "did not trade" rules), the risk brake,
the emergency stop, errors and reconnects, bot started. Not sent: MT5 price lines and
"checked the new candle" lines (too many).

Sending happens on a background thread: lines arriving within 3 seconds go out as one
message, a failed send is retried once and then dropped. Nothing here can slow down or
stop trading.
"""
import logging
import os
import queue
import re
import threading
import time

API = "https://api.telegram.org/bot{token}/sendMessage"

ALWAYS = re.compile(
    r"wants to (BUY|SELL)|Order sent|Trade size|moved the stop|is closing its trade|trade closed|"
    r"skipped a trade|Trade skipped|STOPPED NEW TRADES|below its best level|recovered to|"
    r"Something went wrong|reconnecting|Bot started|Starting the|target further", re.I)
SKIP = re.compile(r"did not trade", re.I)
SUMMARY = re.compile(r"Daily summary", re.I)


def wanted(text, skips=True, daily_summary=True):
    """Is this terminal line worth a phone notification?"""
    if text.startswith("MT5:") or text.startswith("Checked the new candle"):
        return False
    if ALWAYS.search(text):
        return True
    if skips and SKIP.search(text):
        return True
    return bool(daily_summary and SUMMARY.search(text))


class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id, market, skips=True, daily_summary=True, batch_seconds=3.0,
                 post=None):
        super().__init__(level=logging.INFO)
        self.url = API.format(token=token)
        self.chat_id, self.market = str(chat_id), market
        self.skips, self.daily_summary = skips, daily_summary
        self.batch = batch_seconds
        self._post = post or self._requests_post
        self._q = queue.Queue(maxsize=500)
        self._warned = False
        threading.Thread(target=self._loop, daemon=True, name="telegram").start()

    # ---- logging side (trading thread): never blocks, never raises ----
    def emit(self, record):
        try:
            text = record.getMessage()
            if record.levelno >= logging.ERROR:
                text = "ERROR: " + text.splitlines()[0][:300]
            elif not wanted(text, self.skips, self.daily_summary):
                return
            self._q.put_nowait(f"{time.strftime('%H:%M')} {text}")
        except Exception:
            pass

    # ---- sender thread ----
    def _requests_post(self, url, payload):
        import requests
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()

    def _send(self, lines):
        payload = {"chat_id": self.chat_id, "text": f"[{self.market}]\n" + "\n".join(lines)[:3900],
                   "disable_web_page_preview": True}
        for attempt in (1, 2):
            try:
                self._post(self.url, payload)
                return True
            except Exception as e:
                if attempt == 2 and not self._warned:
                    self._warned = True
                    logging.getLogger("fxbot").warning("Telegram send failed (%s); will keep trying "
                                                       "quietly", str(e)[:120])
                time.sleep(2)
        return False

    def _loop(self):
        while True:
            lines = [self._q.get()]
            end = time.time() + self.batch
            while time.time() < end:
                try:
                    lines.append(self._q.get(timeout=max(0.05, end - time.time())))
                except queue.Empty:
                    break
            self._send(lines)

    def flush_now(self, timeout=10):
        """Tests / shutdown: wait until the queue is drained."""
        t0 = time.time()
        while not self._q.empty() and time.time() - t0 < timeout:
            time.sleep(0.05)
        time.sleep(self.batch + 0.2)


def attach(market, cfg_live):
    """Attach to the narration and error logs if Telegram is configured. Returns the handler or None."""
    tg = (cfg_live or {}).get("telegram") or {}
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not tg.get("enabled", True) or not token or not chat:
        return None
    h = TelegramHandler(token, chat, market, bool(tg.get("skips", True)), bool(tg.get("daily_summary", True)))
    logging.getLogger("fxbot.narrate").addHandler(h)
    logging.getLogger("fxbot").addHandler(_ErrorsOnly(h))   # errors from the technical log too
    return h


class _ErrorsOnly(logging.Handler):
    def __init__(self, target):
        super().__init__(level=logging.ERROR)
        self.target = target

    def emit(self, record):
        self.target.emit(record)
