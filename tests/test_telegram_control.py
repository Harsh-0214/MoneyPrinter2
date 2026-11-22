"""Phone commands: lock-file detection and command dispatch (no network, no processes)."""
import msvcrt

import telegram_control as tc


def test_bot_running_follows_the_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "ROOT", tmp_path)
    (tmp_path / "logs").mkdir()
    assert not tc.bot_running("EURUSD")                       # no lock file: off
    f = open(tmp_path / "logs" / ".run_live_EURUSD.lock", "a+")
    assert not tc.bot_running("EURUSD")                       # file but nobody holds it: off
    f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    assert tc.bot_running("EURUSD")                           # held, as a running bot does: on
    f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1); f.close()


def test_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(tc, "status_text", lambda: "STATUS")
    monkeypatch.setattr(tc, "start_missing", lambda: calls.append("start") or ["GBPUSD"])
    monkeypatch.setattr(tc, "stop_all", lambda: calls.append("stop") or [])
    assert tc.handle("/status") == "STATUS"
    assert tc.handle("/status@L6PLinkupsBot") == "STATUS"
    assert "Send /stopbots yes" in tc.handle("/stopbots") and calls == []     # asks first
    assert tc.handle("/stopbots yes") == "All bots stopped." and calls == ["stop"]
    assert tc.handle("/startbots").startswith("Started: GBPUSD")
    assert "/restart" in tc.handle("/help")


def test_restart_mt5_command(monkeypatch):
    monkeypatch.setattr(tc, "restart_mt5", lambda: (True, "account 1 on X"))
    assert "logged in (account 1 on X)" in tc.handle("/restartmt5")
    monkeypatch.setattr(tc, "restart_mt5", lambda: (False, "(-6, 'Terminal: Authorization failed')"))
    assert "NOT logged in" in tc.handle("/restartmt5")
    assert "/restartmt5" in tc.handle("/help")
    assert "SPX500" in tc.MARKETS
