"""USD-base pairs (USD/JPY on a USD account): JPY price moves converted to USD."""
import pandas as pd

from fxbot.brokers.base import Position
from fxbot.brokers.sim_broker import SimBroker
from fxbot.risk import RiskManager

RISK = dict(risk_per_trade_pct=1.0, max_daily_loss_pct=2.0, max_leverage=10, min_units=1000)


def test_sizing_risks_one_percent_in_usd():
    r = RiskManager(RISK, 0.01)
    r.quote_to_account = 1 / 150.0                  # 1 JPY = 1/150 USD
    units = r.position_size(50000, 150.00, 149.00)  # 1-yen stop = $0.00667 per unit
    assert 74000 <= units <= 75000                  # ~$500 at risk
    assert units * 1.0 / 150.0 <= 500.01


def test_pnl_and_r_in_usd():
    b = SimBroker(50000, pip=0.01, inverse_quote=True)
    b._pos = Position(1, 75000, 150.00, pd.Timestamp("2024-01-03", tz="UTC"), 149.00, None, 1.00)
    assert abs(b._pnl_at(152.00) - 75000 * 2 / 152.0) < 1e-6      # ~ +$987
    b._exit(pd.Timestamp("2024-01-04", tz="UTC"), 152.00, "tp")
    t = b.trades[-1]
    assert abs(t.pnl - 986.84) < 0.01
    assert 1.95 < t.r_multiple < 2.0               # +2 yen on a 1-yen stop, at the exit rate


def test_usd_quote_pairs_unchanged():
    b = SimBroker(50000)
    b._pos = Position(1, 100000, 1.1000, pd.Timestamp("2024-01-03", tz="UTC"), 1.0950, None, 0.0050)
    assert abs(b._pnl_at(1.1100) - 1000.0) < 1e-6
