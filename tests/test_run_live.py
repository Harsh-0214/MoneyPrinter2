"""Offline tests for run_live helpers (no MetaTrader needed)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml

import run_live


def _fake_mt5(n_minutes):
    """MT5 stub whose M1 history ends with a still-forming bar at 'now'."""
    now = pd.Timestamp.now(tz="UTC").floor("min")
    idx = pd.date_range(end=now, periods=n_minutes, freq="1min")
    # MT5 encodes server time (NY+7) as if it were UTC
    ny = idx.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=7)
    rates = np.zeros(n_minutes, dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"),
                                       ("low", "f8"), ("close", "f8"), ("spread", "i4")])
    rates["time"] = (ny - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)
    rates["open"] = rates["close"] = 1.1
    rates["high"], rates["low"], rates["spread"] = 1.1005, 1.0995, 8
    return SimpleNamespace(TIMEFRAME_M1=1, TIMEFRAME_H1=16385, copy_rates_range=lambda *a: rates,
                           copy_rates_from_pos=lambda *a: rates), now


def test_fetch_drops_forming_bars():
    cfg = yaml.safe_load(open("config.yaml"))
    mt5, now = _fake_mt5(60)
    bars = run_live._fetch_completed_bars(mt5, "EURUSD.", None, cfg,
                                          (now - pd.Timedelta(hours=2)).to_pydatetime())
    assert len(bars) > 0
    # every returned 5-min bar has fully closed
    assert (bars.index + pd.Timedelta("5min") <= pd.Timestamp.now(tz="UTC")).all()
    assert "spread_pips" in bars.columns
    assert bars.spread_pips.min() >= cfg["costs"]["spread_pips"]


def test_resolve_pair_uses_partner_for_smt():
    cfg = yaml.safe_load(open("config.yaml"))
    sym, smt, magic = run_live._resolve_pair(cfg, "GBPUSD")
    assert sym.startswith("GBPUSD")
    assert smt.startswith("EURUSD")
    assert magic == cfg["live"]["magic"] + 1


def test_status_changes_logged_once(caplog):
    import logging
    class S:
        def __init__(self): self.msg = "Sweep: watching"
        def describe(self, lmin): return {"status": self.msg}
    s = S()
    with caplog.at_level(logging.INFO, logger="fxbot"):
        last = run_live._log_status_changes([s], 500, {})
        last = run_live._log_status_changes([s], 505, last)      # unchanged -> no log
        s.msg = "Sweep: high swept"
        run_live._log_status_changes([s], 510, last)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("STATUS")]
    assert lines == ["STATUS Sweep: watching", "STATUS Sweep: high swept"]


def test_closed_trade_logged(caplog):
    import logging
    from fxbot.brokers.base import Trade
    t = Trade(-1, 14000, pd.Timestamp("2026-11-10 10:30", tz="UTC"), 1.34283,
              pd.Timestamp("2026-11-10 15:30", tz="UTC"), 1.33644, 125.99, 0.0, 2.0,
              "[tp 1.33644]", "short_break")
    with caplog.at_level(logging.INFO, logger="fxbot"):
        run_live._log_closed_trade(SimpleNamespace(trades=[t]))
    assert any("CLOSED short_break SELL" in r.getMessage() and "125.99" in r.getMessage()
               for r in caplog.records)


def test_build_morning_uses_strategy_stack():
    cfg = yaml.safe_load(open("config.yaml"))
    names = [type(s).__name__ for s in run_live._build_morning(cfg)]
    assert names == ["LondonSweep", "LondonBreakout"]
