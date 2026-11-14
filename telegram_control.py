"""Control the bots from your phone through the same Telegram bot that sends notifications.

    python telegram_control.py        (start_bots.bat starts it; one copy at a time)

Commands (only your own chat, TELEGRAM_CHAT_ID in .env, is answered; everyone else is ignored):
    /status       which market bots are running, when each last did something, open trades, equity
    /startbots    start MetaTrader (if needed) and every market bot that isn't running
    /stopbots     stop all market bots (asks you to confirm with /stopbots yes); open trades keep
                  their stop losses at the broker
    /restart      stop and start all market bots
    /help         this list

This program keeps running when the bots are stopped, so /startbots works afterwards. It cannot
answer while the laptop is off, asleep or restarting: no reply within a minute means exactly that.
"""
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
MARKETS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]
MT5_EXE = r"C:\Program Files\MetaTrader 5\terminal64.exe"
log = logging.getLogger("telegram_control")


# ---------------------------------------------------------------- bot state
def bot_running(pair):
    """A running bot holds an exclusive lock on logs/.run_live_<PAIR>.lock."""
    path = ROOT / "logs" / f".run_live_{pair}.lock"
    if not path.exists():
        return False
    try:
        f = open(path, "a+")
    except OSError:
        return True
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        f.close()


def last_activity(pair):
    """Time and text of the bot's last log line today, or None."""
    p = ROOT / "logs" / f"live_{pair}_{datetime.now():%Y%m%d}.log"
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000))
            lines = f.read().decode("utf-8", "replace").strip().splitlines()
        return lines[-1][:19] if lines else None
    except OSError:
        return None


def mt5_running():
    out = subprocess.run(["tasklist", "/fi", "imagename eq terminal64.exe"], capture_output=True, text=True)
    return "terminal64.exe" in out.stdout.lower()


def account_and_positions():
    """(equity line, [open bot trades]) read from MT5, or (message, [])."""
    try:
        import MetaTrader5 as mt5
        from fxbot.backtest import expand_units
        if not mt5.initialize():
            return "MT5: could not connect", []
        cfg = yaml.safe_load(open(ROOT / "config.yaml"))
        labels = {u["magic"]: u["key"] for u in expand_units(cfg)}
        a = mt5.account_info()
        eq = (f"Equity {a.equity:,.2f} {a.currency} (balance {a.balance:,.2f}, free margin {a.margin_free:,.2f})"
              if a else "MT5: no account info")
        pos = []
        for p in mt5.positions_get() or []:
            if p.magic in labels:
                pos.append(f"{labels[p.magic]} {'BUY' if p.type == 0 else 'SELL'} {p.volume:g} @ {p.price_open:g}, "
                           f"stop {p.sl:g}, P/L {p.profit:+,.2f}")
        mt5.shutdown()
        return eq, pos
    except Exception as e:
        return f"MT5: {str(e)[:80]}", []


def status_text():
    lines = ["MoneyPrinter2 status " + datetime.now().strftime("%a %d %b %H:%M"),
             f"MetaTrader: {'running' if mt5_running() else 'NOT running'}"]
    for m in MARKETS:
        on = bot_running(m)
        la = last_activity(m)
        lines.append(f"{'ON ' if on else 'OFF'} {m}" + (f" - last activity {la[11:16]}" if on and la else ""))
    eq, pos = account_and_positions()
    lines.append(eq)
    lines.append("Open trades: " + ("none" if not pos else ""))
    lines += [f"  {p}" for p in pos]
    return "\n".join(lines)


# ---------------------------------------------------------------- actions
def start_missing():
    started = []
    if not mt5_running():
        exe = os.getenv("MT5_TERMINAL_PATH") or MT5_EXE
        subprocess.Popen([exe], cwd=str(ROOT))
        time.sleep(45)                                        # let MT5 log in, as start_bots.bat does
    for m in MARKETS:
        if not bot_running(m):
            subprocess.Popen(f'start "fxbot {m}" cmd /k ""{ROOT / "run_forever.bat"}" {m}"',
                             shell=True, cwd=str(ROOT))
            started.append(m)
            time.sleep(3)
    return started


def stop_all():
    subprocess.run(["cmd", "/c", str(ROOT / "stop_bots.bat")], cwd=str(ROOT), capture_output=True)
    time.sleep(3)
    return [m for m in MARKETS if bot_running(m)]


# ---------------------------------------------------------------- telegram
class Telegram:
    def __init__(self, token, chat_id):
        self.base, self.chat = f"https://api.telegram.org/bot{token}", str(chat_id)
        self.offset = None

    def send(self, text):
        try:
            requests.post(self.base + "/sendMessage", json={"chat_id": self.chat, "text": text[:3900]}, timeout=15)
        except Exception as e:
            log.warning("send failed: %s", e)

    def updates(self):
        params = {"timeout": 50}
        if self.offset is not None:
            params["offset"] = self.offset
        r = requests.get(self.base + "/getUpdates", params=params, timeout=60).json()
        out = r.get("result", [])
        if out:
            self.offset = out[-1]["update_id"] + 1
        return out

    def set_menu(self):
        cmds = [("status", "Are the bots on? Open trades, equity"), ("startbots", "Start any bot that is off"),
                ("stopbots", "Stop all bots (asks to confirm)"), ("restart", "Restart all bots"),
                ("help", "List the commands")]
        try:
            requests.post(self.base + "/setMyCommands", timeout=15,
                          json={"commands": [{"command": c, "description": d} for c, d in cmds]})
        except Exception:
            pass


def handle(text):
    """Reply text for one command (pure dispatch, easy to test)."""
    cmd = text.strip().split()[0].lower().split("@")[0] if text.strip() else ""
    args = text.strip().lower().split()[1:]
    if cmd in ("/status", "/start"):
        return status_text()
    if cmd == "/startbots":
        s = start_missing()
        return ("Started: " + ", ".join(s) + ". Send /status in a minute to check." if s
                else "All 4 bots were already running.")
    if cmd == "/stopbots":
        if args[:1] != ["yes"]:
            return "This stops all 4 bots. Open trades stay open with their stop losses at the broker. Send /stopbots yes to confirm."
        left = stop_all()
        return "All bots stopped." if not left else "Still running: " + ", ".join(left)
    if cmd == "/restart":
        stop_all()
        s = start_missing()
        return "Restarted: " + ", ".join(s) + ". Send /status in a minute to check."
    return __doc__.split("Commands")[1].split("This program")[0].strip().replace("    ", "")


def _single_instance():
    (ROOT / "logs").mkdir(exist_ok=True)
    f = open(ROOT / "logs" / ".telegram_control.lock", "a+")
    try:
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / "telegram_control.log", encoding="utf-8")])
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("Telegram is not set up (python setup_telegram.py).")
    lock = _single_instance()
    if lock is None:
        sys.exit("telegram_control.py is already running.")
    tg = Telegram(token, chat)
    tg.set_menu()
    try:
        tg.updates()                                          # skip commands sent while it was off
    except Exception:
        pass
    log.info("Phone control running. Commands: /status /startbots /stopbots /restart /help")
    while True:
        try:
            for u in tg.updates():
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != tg.chat:
                    continue                                  # not you: ignored
                text = msg.get("text", "")
                log.info("command: %s", text)
                tg.send(handle(text))
        except Exception as e:
            log.warning("poll failed: %s", e)
            time.sleep(10)


if __name__ == "__main__":
    main()
