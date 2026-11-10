"""Smoke tests for the tested-but-unused strategies: they run, tag trades
correctly, and lose on random data (no lookahead edge)."""
import copy

import yaml

from fxbot.backtest import run_backtest
from fxbot.data import generate_synthetic, resample


def _run(slot, spec):
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["smt"] = {}
    cfg["strategies"] = {"morning": [], "afternoon": []}
    cfg["strategies"][slot] = [spec]
    bars = resample(generate_synthetic(days=200), "5min")
    return run_backtest(bars, cfg)


def test_tiny_range_fade_runs_and_tags():
    t, eq = _run("morning", {"name": "tiny_range_fade", "mode": "immediate",
                             "max_range_pips": 30, "min_range_pips": 0})
    assert len(t) > 0
    assert set(t.tag) <= {"fade_long", "fade_short"}
    assert eq.iloc[-1] < eq.iloc[0]          # random walk: costs win


def test_london_close_reversal_both_directions():
    for d in ("fade", "follow"):
        t, eq = _run("afternoon", {"name": "london_close_reversal", "direction": d,
                                   "min_move_pips": 5, "target_rr": 1.5})
        assert len(t) > 0
        assert set(t.tag) <= {"lcr_long", "lcr_short"}
        assert eq.iloc[-1] < eq.iloc[0]
