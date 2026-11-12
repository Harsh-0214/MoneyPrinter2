import pandas as pd

from fxbot.brokers.base import Position
from fxbot.overlay import build_lines, london_today_utc, news_rows, position_rows
from fxbot.strategies.daily_patterns import VolBreakout


def test_london_today_utc_handles_dst():
    winter = london_today_utc(600, pd.Timestamp("2026-01-15 12:00", tz="UTC"))
    summer = london_today_utc(600, pd.Timestamp("2026-07-15 12:00", tz="UTC"))
    assert winter == pd.Timestamp("2026-01-15 10:00", tz="UTC")
    assert summer == pd.Timestamp("2026-07-15 09:00", tz="UTC")     # BST = UTC+1


def test_position_rows_entry_stop_target_and_1r():
    p = Position(-1, 10000, 1.33256, pd.Timestamp("2026-11-11 10:35", tz="UTC"), 1.33569, 1.32630,
                 0.00313, 0, "short_break")
    rows = position_rows(p, be_r=True)
    prices = [float(r.split("|")[2]) for r in rows]
    assert prices[:3] == [1.33256, 1.33569, 1.32630]
    assert abs(prices[3] - (1.33256 - 0.00313)) < 1e-9                # +1R for a short is below entry
    assert "breakeven" in rows[3]


def test_position_rows_stop_at_breakeven():
    p = Position(1, 10000, 1.1, pd.Timestamp("2026-11-11", tz="UTC"), 1.1, None, 0.0, 0, "long_break")
    rows = position_rows(p)
    assert len(rows) == 2 and "locked in" in rows[1]


def test_news_rows_only_upcoming():
    ev = pd.DataFrame({"time": pd.to_datetime(["2026-11-12 13:30", "2026-11-20 13:30"], utc=True),
                       "currency": ["USD", "USD"], "event": ["CPI", "NFP"]})
    rows = news_rows(ev, pd.Timestamp("2026-11-12 08:00", tz="UTC"))
    assert len(rows) == 1 and "CPI" in rows[0] and rows[0].startswith("VLINE|")


def test_vol_breakout_describe_draws_levels_and_times():
    s = VolBreakout({"k": 0.9, "entry_start": "05:00", "entry_end": "12:00", "exit_time": "21:00",
                     "trend_sma": None}, 0.01)
    s.levels = (151.0, 149.0, 1.1, None, 150.0)
    lines = build_lines([s], 6 * 60)
    assert any(l.startswith("HLINE|151.0") and "BUY" in l for l in lines)
    assert any(l.startswith("HLINE|149.0") and "SELL" in l for l in lines)
    assert sum(l.startswith("VLINE|") for l in lines) == 3
