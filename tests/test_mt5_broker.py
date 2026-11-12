import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Inject fake MetaTrader5 before any project imports touch it
mt5_mock = MagicMock()
mt5_mock.ACCOUNT_TRADE_MODE_DEMO = 0
mt5_mock.ACCOUNT_TRADE_MODE_REAL = 1
mt5_mock.TRADE_RETCODE_DONE = 10009
mt5_mock.ORDER_TYPE_BUY = 0
mt5_mock.ORDER_TYPE_SELL = 1
mt5_mock.ORDER_FILLING_FOK = 0
mt5_mock.ORDER_FILLING_IOC = 1
mt5_mock.ORDER_FILLING_RETURN = 2
sys.modules["MetaTrader5"] = mt5_mock

from fxbot.brokers.base import Order  # noqa: E402
from fxbot.brokers.mt5_broker import MT5Broker  # noqa: E402

CFG = {
    "live": {"symbol": "EURUSD", "server_tz": "Europe/Helsinki", "magic": 12345},
    "costs": {"commission_per_lot_per_side": 0.0},
}

FAKE_ENV = {
    "MT5_LOGIN": "11111111",
    "MT5_PASSWORD": "secret",
    "MT5_SERVER": "FOREX.com-Demo",
    "MT5_TERMINAL_PATH": r"C:\MT5\terminal64.exe",
}


def _demo_account():
    acc = MagicMock()
    acc.trade_mode = mt5_mock.ACCOUNT_TRADE_MODE_DEMO
    acc.equity = 10000.0
    return acc


def make_broker(allow_live=False):
    mt5_mock.reset_mock()
    mt5_mock.initialize.return_value = True
    mt5_mock.account_info.return_value = _demo_account()
    sym = MagicMock()
    sym.volume_min = 0.01
    sym.volume_max = 100.0
    sym.volume_step = 0.01
    sym.trade_tick_size = 0.00001
    sym.filling_mode = mt5_mock.ORDER_FILLING_FOK
    mt5_mock.symbol_info.return_value = sym
    with patch("fxbot.brokers.mt5_broker.load_dotenv"), \
         patch.dict(os.environ, FAKE_ENV):
        return MT5Broker(CFG, logging.getLogger("test"), allow_live=allow_live)


# ---------------------------------------------------------------------------


def test_init_fails_if_mt5_initialize_returns_false():
    mt5_mock.reset_mock()
    mt5_mock.initialize.return_value = False
    mt5_mock.last_error.return_value = (1, "some error")
    with patch("fxbot.brokers.mt5_broker.load_dotenv"), \
         patch.dict(os.environ, FAKE_ENV):
        with pytest.raises(RuntimeError):
            MT5Broker(CFG, logging.getLogger("test"))


def test_init_raises_on_live_account_without_flag():
    mt5_mock.reset_mock()
    mt5_mock.initialize.return_value = True
    acc = MagicMock()
    acc.trade_mode = mt5_mock.ACCOUNT_TRADE_MODE_REAL
    mt5_mock.account_info.return_value = acc
    with patch("fxbot.brokers.mt5_broker.load_dotenv"), \
         patch.dict(os.environ, FAKE_ENV):
        with pytest.raises(RuntimeError, match="demo"):
            MT5Broker(CFG, logging.getLogger("test"))


def test_init_allows_live_account_with_flag():
    mt5_mock.reset_mock()
    mt5_mock.initialize.return_value = True
    acc = MagicMock()
    acc.trade_mode = mt5_mock.ACCOUNT_TRADE_MODE_REAL
    mt5_mock.account_info.return_value = acc
    sym = MagicMock()
    sym.volume_min = 0.01
    sym.volume_max = 100.0
    sym.volume_step = 0.01
    sym.trade_tick_size = 0.00001
    sym.filling_mode = mt5_mock.ORDER_FILLING_FOK
    mt5_mock.symbol_info.return_value = sym
    with patch("fxbot.brokers.mt5_broker.load_dotenv"), \
         patch.dict(os.environ, FAKE_ENV):
        broker = MT5Broker(CFG, logging.getLogger("test"), allow_live=True)
    assert broker is not None


def test_equity_returns_account_equity():
    broker = make_broker()
    acc = MagicMock()
    acc.trade_mode = mt5_mock.ACCOUNT_TRADE_MODE_DEMO
    acc.equity = 9876.54
    mt5_mock.account_info.return_value = acc

    assert broker.equity() == pytest.approx(9876.54)


def test_position_returns_none_when_no_open_positions():
    broker = make_broker()
    mt5_mock.positions_get.return_value = []

    assert broker.position() is None


def test_position_returns_position_when_magic_matches():
    broker = make_broker()
    pos = MagicMock()
    pos.magic = 12345
    pos.type = mt5_mock.ORDER_TYPE_BUY
    pos.volume = 0.01
    pos.price_open = 1.10000
    pos.time = 1704182400  # a unix timestamp
    pos.sl = 1.09800
    pos.tp = 1.10300
    mt5_mock.positions_get.return_value = [pos]

    result = broker.position()
    assert result is not None


def test_submit_returns_false_on_order_send_failure():
    broker = make_broker()
    result_mock = MagicMock()
    result_mock.retcode = 10006  # rejected
    mt5_mock.order_send.return_value = result_mock
    mt5_mock.positions_get.return_value = []

    order = Order(side=1, units=10000, stop_loss=1.0980, take_profit=1.1040)
    sym_tick = MagicMock()
    sym_tick.ask = 1.10010
    sym_tick.bid = 1.10000
    mt5_mock.symbol_info_tick.return_value = sym_tick

    assert broker.submit(order) is False


def test_submit_returns_true_on_success():
    broker = make_broker()
    result_mock = MagicMock()
    result_mock.retcode = mt5_mock.TRADE_RETCODE_DONE  # 10009
    mt5_mock.order_send.return_value = result_mock
    mt5_mock.positions_get.return_value = []

    sym_tick = MagicMock()
    sym_tick.ask = 1.10010
    sym_tick.bid = 1.10000
    mt5_mock.symbol_info_tick.return_value = sym_tick

    order = Order(side=1, units=10000, stop_loss=1.0980, take_profit=1.1040)
    assert broker.submit(order) is True


def test_current_spread_pips_calculates_correctly():
    broker = make_broker()
    tick = MagicMock()
    tick.ask = 1.10015
    tick.bid = 1.10005
    mt5_mock.symbol_info_tick.return_value = tick

    spread = broker.current_spread_pips()
    assert spread == pytest.approx(1.0, abs=0.01)


def test_close_position_does_nothing_when_no_position():
    broker = make_broker()
    mt5_mock.positions_get.return_value = []

    broker.close_position()

    mt5_mock.order_send.assert_not_called()


def test_missing_tick_does_not_crash():
    """MT5 can return no tick for a moment (seen live Nov 11 2026): the bot must not raise."""
    broker = make_broker()
    tick = MagicMock()
    tick.ask, tick.bid = 1.10015, 1.10005
    mt5_mock.symbol_info_tick.return_value = tick
    assert broker.current_spread_pips() == pytest.approx(1.0, abs=0.01)
    mt5_mock.symbol_info_tick.return_value = None
    assert broker.current_spread_pips() == pytest.approx(1.0, abs=0.01)   # last known spread
    mt5_mock.positions_get.return_value = []
    assert broker.submit(Order(side=1, units=10000, stop_loss=1.0980)) is False
    mt5_mock.order_send.assert_not_called()
