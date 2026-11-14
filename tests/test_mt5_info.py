"""Terminal 'MT5:' lines: built from MetaTrader's own data, never raise."""
from types import SimpleNamespace as NS

import pandas as pd

from fxbot import mt5_info


class FakeMT5:
    def __init__(self, positions=(), margin=0.0, tick=True):
        self._pos, self._margin, self._tick = list(positions), margin, tick
    def account_info(self):
        return NS(login=1, server="Demo", trade_mode=0, currency="CAD", leverage=50, balance=50000.0,
                  equity=50250.5, margin=self._margin, margin_free=50250.5 - self._margin,
                  margin_level=(50250.5 / self._margin * 100) if self._margin else 0.0)
    def symbol_info(self, s):
        return NS(digits=3, trade_contract_size=100000.0, volume_min=0.01, volume_max=50.0,
                  volume_step=0.01, swap_long=0.0, swap_short=0.0, trade_stops_level=0)
    def symbol_info_tick(self, s):
        return NS(bid=154.351, ask=154.367) if self._tick else None
    def positions_get(self, symbol=None):
        return self._pos


def test_startup_lines_show_account_symbol_and_no_positions():
    lines = mt5_info.startup_lines(FakeMT5(), "USDJPY.", {12348: "Breakout"})
    assert "DEMO" in lines[0] and "equity 50,250.50" in lines[0] and "nothing open" in lines[0]
    assert "1 lot = 100,000" in lines[1] and "step 0.01" in lines[1]
    assert lines[2] == "MT5: open: none"


def test_poll_lines_show_candle_price_and_own_positions_only():
    mine = NS(magic=12348, type=0, volume=0.52, price_open=154.102, sl=153.73, tp=0.0,
              price_current=154.351, profit=1021.4, swap=0.0)
    other = NS(magic=99999, type=1, volume=1.0, price_open=1, sl=0, tp=0, price_current=1, profit=0, swap=0)
    r = NS(label="Breakout", new_bars=1, cfg={"data": {"timeframe": "15min"}},
           last_bar=(pd.Timestamp("2026-11-16 14:15", tz="UTC"),
                     NS(open=154.21, high=154.38, low=154.19, close=154.355)))
    lines = mt5_info.poll_lines(FakeMT5([mine, other], margin=2000.0), "USDJPY.", [r], {12348: "Breakout"}, 0.01, 1.6)
    assert lines[0] == "MT5: [Breakout] candle 14:15 London (15min) O 154.210 H 154.380 L 154.190 C 154.355"
    assert "spread 1.6p (normal 1.6)" in lines[1] and "margin level" in lines[1]
    assert len(lines) == 3 and "BUY 0.52 lots @ 154.102" in lines[2] and "P/L +1,021.40 CAD" in lines[2]


def test_missing_tick_gives_a_short_line():
    r = NS(label="x", new_bars=0, cfg={"data": {"timeframe": "1h"}})
    lines = mt5_info.poll_lines(FakeMT5(tick=False), "XAUUSD", [r], {}, 0.1)
    assert lines[0].startswith("MT5: no live price right now")
