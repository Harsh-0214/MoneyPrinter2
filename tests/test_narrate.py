"""Narration: plain-English terminal lines; the broker wrapper must not change behaviour."""
import logging
from types import SimpleNamespace

from fxbot import narrate
from fxbot.brokers.base import Order, Trade


class _Broker:
    def __init__(self):
        self.pos, self.submitted, self.stops, self.closes = None, [], [], []
    def submit(self, o): self.submitted.append(o); return True
    def position(self): return self.pos
    def update_stop(self, px): self.stops.append(px)
    def close_position(self, r="manual"): self.closes.append(r)
    def equity(self): return 50000.0
    def current_spread_pips(self): return 1.4
    trades = []


def test_narrating_broker_passes_through_and_explains(caplog):
    b = _Broker()
    nb = narrate.NarratingBroker(b, "London", "EURUSD.", 0.0001, 100000, 500,
                                 open_risk_fn=lambda: 0.0, risk_cap=2500)
    with caplog.at_level(logging.INFO, logger="fxbot.narrate"):
        assert nb.submit(Order(-1, 113000, 1.34595, 1.33644, "short_break")) is True
        b.pos = SimpleNamespace(entry_price=1.34283)
        nb.update_stop(1.34283)
        nb.close_position("session_exit")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert b.submitted and b.stops == [1.34283] and b.closes == ["session_exit"]   # unchanged behaviour
    assert "London wants to SELL EURUSD: price broke below the overnight range" in text
    assert "1.13 lots" in text and "Filled." in text
    assert "can no longer lose" in text
    assert "session ended" in text


def test_closed_trade_line(caplog):
    t = Trade(-1, 14000, None, 1.34283, None, 1.33644, 125.99, 0.0, 2.03, "[tp 1.33644]", "short_break")
    with caplog.at_level(logging.INFO, logger="fxbot.narrate"):
        narrate.closed_trade("London", t)
    assert "London trade closed: +125.99 CAD, it hit its target." in caplog.records[-1].getMessage()
