"""IBS mean reversion on US indices (fxbot/strategies/ibs.py): hand-driven hourly bars."""
from types import SimpleNamespace

import pandas as pd
import yaml

from fxbot.strategies.ibs import IBSReversion

NY = "America/New_York"


class _Risk:
    def can_trade(self, eq, t): return True
    def position_size(self, eq, entry, stop, sp): return 5


class _Broker:
    def __init__(self): self.pos, self.closed = None, []
    def position(self): return self.pos
    def equity(self): return 50000
    def current_spread_pips(self): return 0.0
    def close_position(self, reason="x"): self.closed.append(reason); self.pos = None


def _day(date, hi, lo, c16):
    """Hourly bars for one NY trading day: 18:00 the evening before to the 15:00 candle (closes 16:00)."""
    start = pd.Timestamp(f"{date} 18:00", tz=NY) - pd.Timedelta(days=1)
    rows = []
    for k in range(22):                                    # 18:00 .. 15:00 next day
        t = start + pd.Timedelta(hours=k)
        if t.hour in (16, 17):
            continue
        last = t.hour == 15
        rows.append(SimpleNamespace(Index=t.tz_convert("UTC"), open=c16, high=hi if k == 5 else c16 + 0.1,
                                    low=lo if k == 9 else c16 - 0.1, close=c16 if last else (hi + lo) / 2,
                                    spread_pips=0.0))
    return rows


def _feed(s, rows, broker, risk=_Risk()):
    out = []
    for b in rows:
        p = s.propose(b, None, 0, broker, risk)
        if p:
            out.append(p)
            s.mark_fired()
            broker.pos = SimpleNamespace(tag=p.order.tag, entry_price=b.close)
    return out


def _history(n=20):
    rows = []
    for d in pd.bdate_range("2024-01-02", periods=n):
        rows += _day(d.date(), 101.0, 99.0, 100.6)          # range 2, IBS 0.8: no signal
    return rows


def test_buys_at_16ny_when_ibs_low_with_stop_3x_avg_range():
    s = IBSReversion({"entry_ibs": 0.2, "stop_range": 3.0}, 0.1)
    b = _Broker()
    rows = _history() + _day("2024-01-30", 101.0, 99.0, 99.2)      # IBS 0.1
    out = _feed(s, rows, b)
    assert len(out) == 1
    o = out[0].order
    assert o.side == 1 and o.tag == "ibs_long" and abs(o.stop_loss - (99.2 - 3.0 * 2.0)) < 1e-9
    assert pd.Timestamp(rows[-1].Index).tz_convert(NY).hour == 15        # decided on the 15:00 candle


def test_no_signal_before_enough_history_or_when_ibs_high():
    s = IBSReversion({}, 0.1)
    assert _feed(s, _history(5) + _day("2024-01-10", 101.0, 99.0, 99.2), _Broker()) == []   # < 20 days
    s = IBSReversion({}, 0.1)
    assert _feed(s, _history() + _day("2024-01-30", 101.0, 99.0, 100.0), _Broker()) == []   # IBS 0.5


def test_sells_above_previous_high_or_after_5_days():
    s = IBSReversion({}, 0.1)
    b = _Broker()
    _feed(s, _history() + _day("2024-01-30", 101.0, 99.0, 99.2), b)
    _feed(s, _day("2024-01-31", 100.5, 99.5, 100.0), b)            # 100.0 < prev high 101: hold
    assert b.pos is not None and not b.closed
    _feed(s, _day("2024-02-01", 101.5, 99.9, 101.2), b)            # 101.2 > prev high 100.5: sell
    assert b.closed == ["ibs_exit"]
    s = IBSReversion({"max_days": 5}, 0.1)
    b = _Broker()
    _feed(s, _history() + _day("2024-01-30", 101.0, 99.0, 99.2), b)
    for d in pd.bdate_range("2024-01-31", periods=5):
        _feed(s, _day(d.date(), 101.0, 99.0, 100.4), b)            # never above 101, IBS 0.7
    assert b.closed == ["ibs_exit"]


def test_exit_day_that_is_also_a_buy_signal_keeps_holding():
    s = IBSReversion({"max_days": 2}, 0.1)
    b = _Broker()
    _feed(s, _history() + _day("2024-01-30", 101.0, 99.0, 99.2), b)
    _feed(s, _day("2024-01-31", 101.0, 99.0, 100.4), b)            # day 1
    _feed(s, _day("2024-02-01", 101.0, 99.0, 99.1), b)             # day 2 = exit due, but IBS 0.05
    assert b.pos is not None and not b.closed and s.held == 0
    assert "holding, count restarted" in s.last


def test_ignores_positions_it_does_not_own():
    s = IBSReversion({}, 0.1)
    b = _Broker()
    b.pos = SimpleNamespace(tag="trend_long", entry_price=100)
    assert _feed(s, _history() + _day("2024-01-30", 101.0, 99.0, 99.2), b) == [] and not b.closed


def test_config_unit_exists_and_backtests():
    from fxbot.backtest import expand_units
    cfg = yaml.safe_load(open("config.yaml"))
    u = [x for x in expand_units(cfg) if x["key"] == "SPX500"]
    assert u and u[0]["magic"] == 12349 and u[0]["strategies"]["morning"][0]["name"] == "ibs"


def test_fractional_index_sizing_keeps_0_1_lot_steps():
    """Nov 18 2026: $1-a-point index contracts sized in whole units rounded 1.5 -> 1 (or 0)."""
    from fxbot.risk import RiskManager, units_floor
    cfg = yaml.safe_load(open("config.yaml"))["risk"]
    r = RiskManager(dict(cfg, news_filter=False, risk_per_trade_pct=2.0, min_units=0.1, max_leverage=100), 0.1)
    u = r.position_size(50000, 7400.0, 7400.0 - 450.0)        # 1000 / 450 = 2.22 contracts
    assert abs(u - 2.2) < 1e-9 and isinstance(u, float)
    fx = RiskManager(dict(cfg, news_filter=False, min_units=1000), 0.0001)
    assert isinstance(fx.position_size(50000, 1.1, 1.09), int)  # FX stays whole units
    assert units_floor(13999.7, 1000) == 13000 and units_floor(2.96, 0.1) == 2.9


def test_mt5_units_from_volume():
    from fxbot.brokers.mt5_broker import _units
    assert _units(0.13 * 100000) == 13000 and isinstance(_units(0.13 * 100000), int)
    assert _units(2.9 * 1.0) == 2.9
