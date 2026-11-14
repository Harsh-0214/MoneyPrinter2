"""One-time Telegram setup for phone notifications.

    1. In Telegram, open @BotFather, send /newbot, pick any name; it replies with a token.
    2. Put it in .env:   TELEGRAM_BOT_TOKEN=123456:ABC...
    3. In Telegram, open your new bot and send it any message (e.g. "hi").
    4. python setup_telegram.py

This finds your chat id from that message, writes TELEGRAM_CHAT_ID into .env, and sends a
test message. Then restart the bots (stop_bots.bat, start_bots.bat).
"""
import os
import re
import sys

import requests
from dotenv import load_dotenv

ENV = ".env"


def main():
    load_dotenv(ENV)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is not in .env yet (step 2 in this file's header).")
    me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
    if not me.get("ok"):
        sys.exit(f"Telegram rejected the token: {me.get('description')}")
    name = me["result"]["username"]
    up = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10).json()
    chats = [u["message"]["chat"] for u in up.get("result", []) if "message" in u]
    if not chats:
        sys.exit(f"No messages yet. Open @{name} in Telegram, send it any message, then run this again.")
    chat = chats[-1]
    chat_id = str(chat["id"])
    text = open(ENV, encoding="utf-8").read() if os.path.exists(ENV) else ""
    if re.search(r"^TELEGRAM_CHAT_ID=.*$", text, re.M):
        text = re.sub(r"^TELEGRAM_CHAT_ID=.*$", f"TELEGRAM_CHAT_ID={chat_id}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\nTELEGRAM_CHAT_ID={chat_id}\n"
    open(ENV, "w", encoding="utf-8").write(text)
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=10,
                      json={"chat_id": chat_id, "text": "MoneyPrinter2: phone notifications are set up. "
                                                        "Restart the bots to switch them on."}).json()
    print(f"Bot @{name}, chat id {chat_id} saved to .env. Test message "
          f"{'sent - check your phone' if r.get('ok') else 'FAILED: ' + str(r.get('description'))}.")
    print("Now restart the bots: stop_bots.bat, then start_bots.bat")


if __name__ == "__main__":
    main()
