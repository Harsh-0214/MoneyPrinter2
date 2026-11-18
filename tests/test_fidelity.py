"""run_fidelity.compare: pairing live trades with backtest trades."""
import pandas as pd

from run_fidelity import compare, summary_text

T = lambda s: pd.Timestamp(s, tz="UTC")


def _live(rows):
    return pd.DataFrame(rows, columns=["unit", "side", "entry_time", "R", "open", "tag"])


def _bt(rows):
    return pd.DataFrame(rows, columns=["unit", "side", "entry_time", "r_multiple", "tag"])


def test_compare_statuses():
    live = _live([("GBPUSD", -1, T("2026-11-11 10:35:06"), 1.45, False, "short_break"),   # match
                  ("USDJPY", -1, T("2026-11-17 09:15:05"), -0.60, False, "vbo_short"),    # R differs
                  ("EURUSD", 1, T("2026-11-12 10:45:05"), 1.0, False, "long_break"),      # live only
                  ("XAUUSD", 1, T("2026-11-18 20:00:05"), None, True, "trend_long")])     # open, unpaired
    bt = _bt([("GBPUSD", -1, T("2026-11-11 10:35:00"), 1.44, "short_break"),
              ("USDJPY", -1, T("2026-11-17 09:15:00"), -1.01, "vbo_short"),
              ("EURUSD", -1, T("2026-11-12 10:45:00"), -1.0, "short_break"),              # wrong side
              ("GBPUSD", 1, T("2026-11-13 10:35:00"), 2.0, "long_break")])                # missed
    r = compare(live, bt).set_index(["unit", "entry_time"]).status
    assert r[("GBPUSD", T("2026-11-11 10:35:06"))] == "MATCH"
    assert r[("USDJPY", T("2026-11-17 09:15:05"))] == "R DIFFERS"
    assert r[("EURUSD", T("2026-11-12 10:45:05"))] == "LIVE ONLY"
    assert r[("EURUSD", T("2026-11-12 10:45:00"))] == "MISSED"
    assert r[("GBPUSD", T("2026-11-13 10:35:00"))] == "MISSED"
    assert r[("XAUUSD", T("2026-11-18 20:00:05"))] == "OPEN (check later)"


def test_entry_more_than_10_minutes_apart_is_not_a_match():
    live = _live([("USDJPY", 1, T("2026-11-17 09:30:05"), 1.0, False, "vbo_long")])
    bt = _bt([("USDJPY", 1, T("2026-11-17 09:15:00"), 1.0, "vbo_long")])
    assert sorted(compare(live, bt).status) == ["LIVE ONLY", "MISSED"]


def test_summary_all_good_and_empty():
    live = _live([("GBPUSD", -1, T("2026-11-11 10:35:06"), 1.45, False, "short_break")])
    bt = _bt([("GBPUSD", -1, T("2026-11-11 10:35:00"), 1.44, "short_break")])
    s = summary_text(compare(live, bt), T("2026-11-10"), T("2026-11-17"))
    assert "1 match" in s and "MISMATCH" not in s and "All good" in s
    s = summary_text(compare(_live([]), _bt([])), T("2026-11-10"), T("2026-11-17"))
    assert "No trades either way" in s
