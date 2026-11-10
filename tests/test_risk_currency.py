"""Position size must risk the right amount in the ACCOUNT currency (e.g. CAD)."""
from fxbot.risk import RiskManager


def _rm():
    return RiskManager({"risk_per_trade_pct": 0.5, "max_daily_loss_pct": 2,
                        "max_leverage": 10, "min_units": 1}, 0.0001)


def test_usd_account_default():
    assert _rm().position_size(10000, 1.1000, 1.0950) == 10000      # 50 / 50 pips


def test_cad_account_scales_down():
    r = _rm()
    r.quote_to_account = 1.40                                       # 1 USD = 1.40 CAD
    units = r.position_size(10000, 1.1000, 1.0950)
    assert abs(units * 0.0050 * 1.40 - 50) < 0.1                    # still risks 50 CAD
