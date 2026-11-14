"""Losing-streak count, alert text, and the optional streak sizing in the live runner."""
import logging
from types import SimpleNamespace as NS

from fxbot import streaks


def test_trailing_losses():
    assert streaks.trailing_losses([]) == 0
    assert streaks.trailing_losses([5, -1, -2, -3]) == 3
    assert streaks.trailing_losses([-1, -1, 4]) == 0


def test_alert_text_uses_the_test_history():
    hist = {"runs": [1, 3, 2, 4, 3, 1], "longest": 4, "years": 6.0, "trades": 100}
    s = streaks.alert_text("GBPUSD London", 3, hist)
    assert "lost 3 trades in a row" in s and "3 times in 6 years" in s and "longest streak was 4" in s
    assert "keeps trading normally" in streaks.alert_text("X", 3, None)


def _runner(size_after=None):
    from run_live import StrategyRunner
    r = StrategyRunner.__new__(StrategyRunner)
    r.label, r.log, r.loss_streak = "London", logging.getLogger("t"), 0
    r._streak_alert, r._streak_size_after, r._streak_mult, r._streak_hist = 3, size_after, 0.5, None
    r._base_risk, r._brake, r.risk = 3.0, [], NS(risk_pct=3.0)
    return r


def _close(r, pnl, said):
    r.broker = NS(trades=[NS(exit_time=1, pnl=pnl)])
    r._on_trade_closed()


def test_streak_alert_and_reset(monkeypatch):
    said = []
    monkeypatch.setattr("fxbot.narrate.say", lambda *a: said.append(a[0] % a[1:] if len(a) > 1 else a[0]))
    r = _runner()
    for p in (-10, -10):
        _close(r, p, said)
    assert said == []
    _close(r, -10, said)
    assert r.loss_streak == 3 and "lost 3 trades in a row" in said[-1]
    _close(r, 50, said)
    assert r.loss_streak == 0 and "won after 3 losses" in said[-1]


def test_streak_sizing_only_when_switched_on(monkeypatch):
    monkeypatch.setattr("fxbot.narrate.say", lambda *a: None)
    off, on = _runner(None), _runner(3)
    for r in (off, on):
        r.loss_streak = 3
        r._apply_risk_brake()
    assert off.risk.risk_pct == 3.0 and on.risk.risk_pct == 1.5
    on.loss_streak = 0
    on._apply_risk_brake()
    assert on.risk.risk_pct == 3.0
