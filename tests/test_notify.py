"""Telegram notifications: right lines, batched, never in the way of trading."""
import logging

from fxbot import notify


def test_filter_keeps_trades_skips_and_errors_but_not_price_lines():
    w = notify.wanted
    assert w("London wants to SELL GBPUSD: price broke below the overnight range.")
    assert w("Order sent: SELL 1.05 lots GBPUSD. Filled.")
    assert w("London trade closed: +683.36 CAD, the session ended.")
    assert w("GBPUSD London did not trade: price broke above the overnight range 1.3 ...")
    assert not w("GBPUSD London did not trade: x", skips=False)
    assert w("Breakout: the account is 9.1% below its best level, so trades are now smaller")
    assert not w("MT5: bid 154.351 ask 154.367 spread 1.6p")
    assert not w("Checked the new candle: nothing to do.")
    assert not w("[London] Breakout: range so far 18p")


def test_lines_are_batched_into_one_message_and_errors_forwarded():
    sent = []
    h = notify.TelegramHandler("T", "42", "GBPUSD", batch_seconds=0.3, post=lambda url, p: sent.append(p))
    lg = logging.getLogger("fxbot.test_notify"); lg.addHandler(h); lg.setLevel(logging.INFO)
    lg.info("London wants to SELL GBPUSD: x.")
    lg.info("MT5: bid 1 ask 2")
    lg.info("Order sent: SELL 1.05 lots GBPUSD. Filled.")
    lg.error("Error (failure 1/5): boom\nTraceback ...")
    h.flush_now(2)
    lg.removeHandler(h)
    text = "\n".join(p["text"] for p in sent)
    assert sent and sent[0]["chat_id"] == "42" and text.startswith("[GBPUSD]")
    assert "wants to SELL" in text and "Order sent" in text and "ERROR: Error (failure 1/5): boom" in text
    assert "MT5:" not in text and "Traceback" not in text
    assert len(sent) == 1                                  # one message for the burst


def test_a_failing_send_never_raises():
    def boom(url, p):
        raise RuntimeError("no internet")
    h = notify.TelegramHandler("T", "1", "X", batch_seconds=0.1, post=boom)
    rec = logging.LogRecord("fxbot.narrate", logging.INFO, "", 0, "Order sent: BUY", None, None)
    h.emit(rec)                                            # returns at once even though sending fails


def test_off_without_env_or_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.attach("EURUSD", {"telegram": {"enabled": True}}) is None
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t"); monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    assert notify.attach("EURUSD", {"telegram": {"enabled": False}}) is None
