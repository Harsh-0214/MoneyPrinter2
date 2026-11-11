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


def test_single_instance_lock():
    a = run_live._single_instance_lock("TESTPAIR")
    assert a is not None
    assert run_live._single_instance_lock("TESTPAIR") is None     # second copy refused
    a.close()
    b = run_live._single_instance_lock("TESTPAIR")                # free again after release
    assert b is not None
    b.close()


def test_units_and_magics_are_unique():
    from fxbot.backtest import expand_units
    cfg = yaml.safe_load(open("config.yaml"))
    units = expand_units(cfg)
    keys = [u["key"] for u in units]
    assert {"EURUSD", "GBPUSD", "XAUUSD", "EURUSD:pullback", "GBPUSD:pullback", "XAUUSD:fast"} <= set(keys)
    magics = [u["magic"] for u in units]
    assert len(set(magics)) == len(magics)                       # every bot tracks its own trades
    m = {u["key"]: u["magic"] for u in units}
    assert m["EURUSD"] == 12345 and m["GBPUSD"] == 12346 and m["XAUUSD"] == 12347   # unchanged
    sleeve = run_live._unit(cfg, "EURUSD", "pullback")
    assert sleeve["strategies"]["morning"][0]["name"] == "daily_pullback"
    assert "smt" not in sleeve


def test_portfolio_risk_guard_blocks_over_cap():
    class P:   # an open long whose stop is 500 below entry
        def __init__(self, magic, sl): self.magic, self.sl, self.type = magic, sl, 0
        price_open, symbol, volume = 1.1, "EURUSD.", 1.0
    class M:
        ORDER_TYPE_BUY = 0
        def __init__(self, ps): self.ps = ps
        def positions_get(self): return self.ps
        def order_calc_profit(self, t, s, v, a, b): return -500.0
    class B:
        sent = 0
        def submit(self, o): B.sent += 1; return True
    guard = run_live.PortfolioRiskGuard(B(), M([P(12345, 1.09), P(12446, 1.09)]), {12345, 12446},
                                        cap_money=1200, new_trade_risk=500)
    assert guard.open_risk() == 1000
    assert guard.submit(object()) is False and B.sent == 0           # 1000 + 500 > 1200
    guard2 = run_live.PortfolioRiskGuard(B(), M([P(12345, 1.11)]), {12345}, 1200, 500)
    assert guard2.open_risk() == 0                                    # stop past entry = no risk
    assert guard2.submit(object()) is True


def test_spread_guard_skips_wide_spread():
    class B:
        sp, sent = 1.4, 0
        def current_spread_pips(self): return B.sp
        def submit(self, o): B.sent += 1; return True
    g = run_live.SpreadGuard(B(), 3.5, "London")
    assert g.submit(object()) is True and B.sent == 1
    B.sp = 6.0
    assert g.submit(object()) is False and B.sent == 1


def test_drawdown_breaker(tmp_path, monkeypatch):
    monkeypatch.setattr(run_live.DrawdownBreaker, "STATE", tmp_path / "peak.json")
    class B:
        sent = 0
        def submit(self, o): B.sent += 1; return True
    class M:
        eq = 50000.0
        def account_info(self): return SimpleNamespace(equity=M.eq)
    run_live.DrawdownBreaker.update_peak(52000.0)
    br = run_live.DrawdownBreaker(B(), M(), 50000, 15.0, "London")
    assert br.submit(object()) is True                       # 2000 / 50000 = 4% below peak
    M.eq = 44000.0                                           # 8000 / 50000 = 16% below peak
    assert br.submit(object()) is False and B.sent == 1
    assert run_live.DrawdownBreaker.update_peak(44000.0) == 52000.0   # peak never drops


def test_stall_watchdog_respects_market_hours():
    import pandas as pd
    wed = pd.Timestamp("2026-11-11 10:00", tz="UTC")              # Wednesday, market open
    assert run_live.stalled(wed - pd.Timedelta(minutes=10), "5min", wed) is False
    assert run_live.stalled(wed - pd.Timedelta(minutes=60), "5min", wed) is True
    assert run_live.stalled(wed - pd.Timedelta(hours=2), "1h", wed) is False
    sat = pd.Timestamp("2026-11-14 10:00", tz="UTC")              # weekend: never "stalled"
    assert run_live.stalled(sat - pd.Timedelta(hours=30), "5min", sat) is False
    sun_open = pd.Timestamp("2026-11-15 22:10", tz="UTC")         # just reopened after the weekend
    assert run_live.stalled(pd.Timestamp("2026-11-13 20:55", tz="UTC"), "5min", sun_open) is False
    daily = pd.Timestamp("2026-11-11 23:05", tz="UTC")            # just after the daily break
    assert run_live.stalled(pd.Timestamp("2026-11-11 20:55", tz="UTC"), "5min", daily) is False


def test_build_morning_uses_strategy_stack():
    cfg = yaml.safe_load(open("config.yaml"))
    names = [type(s).__name__ for s in run_live._build_morning(cfg)]
    assert names == ["LondonSweep", "LondonBreakout"]
