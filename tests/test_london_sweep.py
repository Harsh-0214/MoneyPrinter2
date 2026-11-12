"""Tests for the London Sweep strategy.

Covers:
  1. Swing point lookahead guard (not available before bar i+k closes)
  2. Hand-built day: high swept, BOS → exactly one short with correct stop/target
  3. Failed sweep (price exceeds sweep_max_pips) → no trade
  4. BOS never happens → no trade
  5. Long mirror case
  6. Synthetic random-walk: should lose (no edge in random data)
  7. SMT filter blocks trade when confirmation pair also swept
  8. SMT filter allows trade when confirmation pair did NOT sweep
"""
import numpy as np
import pandas as pd
import pytest

from fxbot.strategies.london_sweep import LondonSweep
from fxbot.data import PIP


# ---------------------------------------------------------------------------
# Minimal helpers
# ---------------------------------------------------------------------------

CFG = {
    "range_start":            "00:00",
    "range_end":              "08:00",
    "sweep_window_start":     "08:00",
    "sweep_window_end":       "10:30",
    "entry_cutoff":           "11:00",
    "session_exit":           "16:00",
    "sweep_min_pips":          1.0,
    "sweep_max_pips":         15.0,
    "swing_k":                 2,
    "bos_buffer_pips":         0.5,
    "max_bars_after_sweep":   12,
    "require_close_inside_range": True,
    "stop_buffer_pips":        1.0,
    "max_stop_pips":          25.0,
    "target_mode":            "opposite_range",
    "reward_risk":             2.0,
    "min_rr":                  1.5,
    "max_trades_per_day":      1,
}
PIP_ = PIP


def _make_bar(open_, high, low, close, spread_pips=1.0, atr=10 * PIP_,
              smt_high=float("nan"), smt_low=float("nan")):
    """Return a namedtuple that mimics itertuples() output."""
    from collections import namedtuple
    Bar = namedtuple("Bar", ["Index", "open", "high", "low", "close",
                              "spread_pips", "atr", "ema", "smt_high", "smt_low"])
    ts = pd.Timestamp("2026-01-02 09:00:00", tz="UTC")
    return Bar(ts, open_, high, low, close, spread_pips, atr, 1.08, smt_high, smt_low)


def _day():
    """London date object for 2026-01-02."""
    import numpy as np
    return np.datetime64("2026-01-02", "D")


class FakeBroker:
    """Minimal broker that records submitted orders and can hold one position."""
    def __init__(self):
        self.orders = []
        self._pos = None

    def equity(self): return 50_000.0
    def position(self): return self._pos
    def current_spread_pips(self): return 1.0

    def submit(self, order):
        self.orders.append(order)
        return True

    def close_position(self, reason="manual"):
        self._pos = None


class FakeRisk:
    def can_trade(self, equity, t): return True
    def position_size(self, equity, entry, stop, spread_pips=0.0):
        dist = abs(entry - stop)
        if dist <= 0:
            return 0
        return int(equity * 0.005 / dist // 1000 * 1000)


# ---------------------------------------------------------------------------
# Test 1: swing point lookahead guard
# ---------------------------------------------------------------------------

def test_swing_not_available_before_confirmation():
    """Swing at bar i should NOT appear in _sw_lows until bar i+k is processed."""
    strat = LondonSweep(CFG, PIP_)
    day = _day()
    broker = FakeBroker()
    risk = FakeRisk()

    # Feed 5 bars: bar 2 is a swing low (k=2, needs bars 0-4)
    prices = [1.0800, 1.0790, 1.0780, 1.0790, 1.0800]  # bar 2 is lowest
    k = CFG["swing_k"]

    for i, p in enumerate(prices):
        bar = _make_bar(p, p + 0.0005, p - 0.0005, p)
        strat.on_bar(bar, day, 10, broker, risk)   # local_min=10 (Asian range build)

        if i < k + 2:    # bar index = i, confirmed at i == 2 + k
            # swing low at index 2 is confirmed when bar 2+k = bar 4 arrives
            confirmed = any(idx == 2 for idx, _ in strat._sw_lows)
            if i < 2 + k:   # before bar 4
                assert not confirmed, f"Swing low confirmed too early at bar {i}"
            else:            # bar 4 and beyond
                assert confirmed, f"Swing low should be confirmed at bar {i}"


# ---------------------------------------------------------------------------
# Test 2: hand-built short setup
# ---------------------------------------------------------------------------

def test_short_setup_correct_stop_and_target():
    """
    Manual day:
      Asian range (bars at 00:00-08:00): hi=1.0850, lo=1.0800
      Bars 08:xx: swing lows at 1.0845 → 1.0840 → 1.0845 (swing low at 1.0840)
      Sweep: bar high reaches 1.0860 (> asian_hi + 1 pip)
      BOS: a bar closes below 1.0840 - 0.5pip = 1.08395
    Expect: one short order, stop = 1.0860 + 1pip + spread, target = asian_lo = 1.0800
    """
    strat = LondonSweep(CFG, PIP_)
    broker = FakeBroker()
    risk = FakeRisk()
    day = _day()

    spread = 1.0  # pip
    spread_px = spread * PIP_
    asian_hi = 1.0850
    asian_lo = 1.0800

    # -- Asian range bars (minutes 0 to 479 = 00:00 to 07:59) --
    for m in range(0, 480, 5):
        bar = _make_bar(asian_hi - 0.0010, asian_hi, asian_lo, asian_hi - 0.0010, spread)
        strat.on_bar(bar, day, m, broker, risk)

    assert strat.asian_hi == pytest.approx(asian_hi)
    assert strat.asian_lo == pytest.approx(asian_lo)

    # -- Sweep window bars building a swing low at the 3rd bar (index 2 of sweep) --
    # We feed 5 bars so swing_k=2 is confirmed:
    # bar0: high=1.0845
    # bar1: high=1.0845
    # bar2: HIGH=1.0840 (this will be both swing low AND the sweep extreme bar)
    # Actually we need bar2 to be the SWING LOW, not the sweep extreme.
    # The swing low must be BEFORE the sweep extreme.
    # Let's structure it:
    #   sweep bars 0-1: lows descend (not sweep yet)
    #   sweep bar 2: low=1.0840 (the swing low candidate, confirmed at bar 4)
    #   sweep bars 3-4: lows go back up → confirms bar 2 as swing low
    #   sweep bar 5: HIGH reaches 1.0860 (sweep extreme, after swing is confirmed)
    #   sweep bar 6+: BOS bar closes below 1.0840 - 0.5pip

    sweep_bars = [
        # (open, high, low, close)
        (1.0848, 1.0852, 1.0845, 1.0848),   # idx 0 — no swing yet
        (1.0847, 1.0851, 1.0843, 1.0847),   # idx 1 — descending
        (1.0845, 1.0847, 1.0840, 1.0845),   # idx 2 — SWING LOW candidate (1.0840)
        (1.0846, 1.0850, 1.0843, 1.0846),   # idx 3 — after swing low
        (1.0848, 1.0852, 1.0845, 1.0848),   # idx 4 — confirms bar 2 as swing low
        (1.0855, 1.0860, 1.0853, 1.0855),   # idx 5 — SWEEP (1.0860 > asian_hi+1pip=1.08510)
        (1.0853, 1.0855, 1.0848, 1.0852),   # idx 6 — still above sw_lo
        (1.0848, 1.0850, 1.0838, 1.0838),   # idx 7 — BOS: close=1.0838 < 1.0840-0.5pip=1.08395
    ]

    sweep_start_min = 8 * 60  # 480
    for i, (o, h, l, c) in enumerate(sweep_bars):
        bar = _make_bar(o, h, l, c, spread)
        strat.on_bar(bar, day, sweep_start_min + i * 5, broker, risk)

    assert len(broker.orders) == 1, f"Expected 1 order, got {len(broker.orders)}: {broker.orders}"
    order = broker.orders[0]
    assert order.side == -1, "Expected short"

    expected_stop = strat.ext_hi + CFG["stop_buffer_pips"] * PIP_ + spread_px
    assert order.stop_loss == pytest.approx(expected_stop, abs=1e-6)
    assert order.take_profit == pytest.approx(asian_lo, abs=1e-5)
    assert order.tag == "sweep_short"


# ---------------------------------------------------------------------------
# Test 3: failed sweep → no trade
# ---------------------------------------------------------------------------

def test_failed_sweep_no_trade():
    """If price exceeds asian_hi + sweep_max_pips, the sweep is invalidated."""
    strat = LondonSweep(CFG, PIP_)
    broker = FakeBroker()
    risk = FakeRisk()
    day = _day()
    asian_hi = 1.0850

    for m in range(0, 480, 5):
        bar = _make_bar(1.0820, asian_hi, 1.0800, 1.0820)
        strat.on_bar(bar, day, m, broker, risk)

    # Price exceeds asian_hi + sweep_max_pips (15 pips = 0.0015)
    breakout_bar = _make_bar(1.0860, 1.0870, 1.0855, 1.0865)  # high=1.0870 > 1.0850+0.0015=1.0865
    strat.on_bar(breakout_bar, day, 490, broker, risk)

    # Even a "BOS" bar now should not trigger a trade
    bos_bar = _make_bar(1.0845, 1.0848, 1.0830, 1.0831)
    strat.on_bar(bos_bar, day, 495, broker, risk)

    assert len(broker.orders) == 0
    assert strat.high_failed


# ---------------------------------------------------------------------------
# Test 4: BOS never happens → no trade
# ---------------------------------------------------------------------------

def test_no_bos_no_trade():
    """Sweep happens but price never breaks back below the swing low."""
    strat = LondonSweep(CFG, PIP_)
    broker = FakeBroker()
    risk = FakeRisk()
    day = _day()
    asian_hi, asian_lo = 1.0850, 1.0800

    for m in range(0, 480, 5):
        bar = _make_bar(1.0820, asian_hi, asian_lo, 1.0820)
        strat.on_bar(bar, day, m, broker, risk)

    # Sweep
    strat.on_bar(_make_bar(1.0855, 1.0858, 1.0853, 1.0855), day, 485, broker, risk)
    # Price stays ABOVE swing low for many bars (no BOS)
    for i in range(15):
        strat.on_bar(_make_bar(1.0853, 1.0856, 1.0851, 1.0853), day, 490 + i * 5, broker, risk)

    assert len(broker.orders) == 0


# ---------------------------------------------------------------------------
# Test 5: long mirror case
# ---------------------------------------------------------------------------

def test_long_setup():
    """Low swept → BOS above swing high → long order placed."""
    # asian_hi=1.0880, asian_lo=1.0800 → target dist ~59 pips, stop ~32 pips, R:R~1.8 ≥ 1.5
    cfg = {**CFG, "max_stop_pips": 50}
    strat = LondonSweep(cfg, PIP_)
    broker = FakeBroker()
    risk = FakeRisk()
    day = _day()
    asian_hi = 1.0880
    asian_lo = 1.0800

    for m in range(0, 480, 5):
        bar = _make_bar(1.0840, asian_hi, asian_lo, 1.0840)
        strat.on_bar(bar, day, m, broker, risk)

    # Sweep low bars building a swing HIGH before the extreme
    sweep_bars = [
        (1.0802, 1.0810, 1.0800, 1.0805),   # idx 0
        (1.0803, 1.0812, 1.0801, 1.0806),   # idx 1
        (1.0805, 1.0815, 1.0803, 1.0810),   # idx 2 — SWING HIGH candidate (1.0815)
        (1.0808, 1.0812, 1.0805, 1.0808),   # idx 3
        (1.0806, 1.0810, 1.0803, 1.0806),   # idx 4 — confirms bar 2 as swing high
        (1.0800, 1.0802, 1.0790, 1.0792),   # idx 5 — SWEEP LOW (1.0790 < asian_lo-1pip)
        (1.0793, 1.0800, 1.0791, 1.0796),   # idx 6 — still below sw_hi
        (1.0797, 1.0820, 1.0795, 1.0820),   # idx 7 — BOS: close=1.0820 > 1.0815+0.5pip
    ]
    for i, (o, h, l, c) in enumerate(sweep_bars):
        bar = _make_bar(o, h, l, c)
        strat.on_bar(bar, day, 480 + i * 5, broker, risk)

    assert len(broker.orders) == 1
    order = broker.orders[0]
    assert order.side == 1, "Expected long"
    assert order.tag == "sweep_long"
    assert order.take_profit == pytest.approx(asian_hi, abs=1e-5)  # target = asian_hi = 1.0880


# ---------------------------------------------------------------------------
# Test 6: synthetic random-walk — strategy should NOT profit
# ---------------------------------------------------------------------------

def test_synthetic_no_edge():
    """
    On random-walk data there is no edge. The strategy should lose (or at
    best be flat) compared to starting equity, since all PnL comes from
    spread/slippage costs.
    If it shows a meaningful profit on random data, there's a lookahead bug.
    """
    from fxbot.data import generate_synthetic, resample
    from fxbot.backtest import run_backtest, compute_metrics
    import yaml

    cfg = yaml.safe_load(open("config.yaml"))          # repo root (pytest runs from there)
    cfg["strategy"]["name"] = "london_sweep"

    raw = generate_synthetic(days=365, seed=99)
    bars = resample(raw, "5min")

    from fxbot.strategies.london_sweep import LondonSweep
    trades, equity = run_backtest(bars, cfg, LondonSweep)
    m = compute_metrics(trades, equity, cfg["account"]["starting_equity"])

    # On random data with costs, expect a loss (or at most trivially positive)
    assert m["total_return_pct"] < 5.0, (
        f"Strategy made {m['total_return_pct']:.1f}% on random data — "
        "this suggests a lookahead bug!"
    )
    print(f"\nSynthetic test: {m['trades']} trades, return={m['total_return_pct']:.2f}%")


# ---------------------------------------------------------------------------
# Test 7: SMT filter blocks trade when confirmation pair also swept
# ---------------------------------------------------------------------------

def test_smt_blocks_when_confirmation_pair_also_swept():
    """When EUR sweeps high AND GBP also sweeps its Asian high → both pairs
    moved together → real breakout, not a stop hunt → SMT filter must block entry."""
    cfg = {**CFG, "smt_filter": True, "smt_min_pips": 1.0}
    strat = LondonSweep(cfg, PIP_)
    broker = FakeBroker()
    risk = FakeRisk()
    day = _day()
    asian_hi, asian_lo = 1.0850, 1.0800
    gbp_asian_hi = 1.2600  # GBPUSD Asian high

    # Asian range bars — include GBP high/low
    for m in range(0, 480, 5):
        bar = _make_bar(1.0820, asian_hi, asian_lo, 1.0820,
                        smt_high=gbp_asian_hi, smt_low=1.2550)
        strat.on_bar(bar, day, m, broker, risk)

    # Sweep window bars: EUR sweeps high, GBP also sweeps its Asian high
    sweep_bars = [
        # EUR                                           GBP H/L
        (1.0848, 1.0852, 1.0845, 1.0848,  gbp_asian_hi + 0.0005, 1.2595),  # idx 0
        (1.0847, 1.0851, 1.0843, 1.0847,  gbp_asian_hi + 0.0003, 1.2594),  # idx 1
        (1.0845, 1.0847, 1.0840, 1.0845,  gbp_asian_hi + 0.0002, 1.2593),  # idx 2 — EUR swing low
        (1.0846, 1.0850, 1.0843, 1.0846,  gbp_asian_hi + 0.0003, 1.2594),  # idx 3
        (1.0848, 1.0852, 1.0845, 1.0848,  gbp_asian_hi + 0.0004, 1.2595),  # idx 4 — confirms swing
        # GBP sweeps its own Asian high here (> gbp_asian_hi + smt_min_pips)
        (1.0855, 1.0860, 1.0853, 1.0855,  gbp_asian_hi + 0.0015, 1.2596),  # idx 5 — EUR sweep + GBP sweep
        (1.0853, 1.0855, 1.0848, 1.0852,  gbp_asian_hi + 0.0010, 1.2595),  # idx 6
        (1.0848, 1.0850, 1.0838, 1.0838,  gbp_asian_hi + 0.0005, 1.2594),  # idx 7 — EUR BOS
    ]
    for i, row in enumerate(sweep_bars):
        o, h, l, c, sh, sl = row
        bar = _make_bar(o, h, l, c, smt_high=sh, smt_low=sl)
        strat.on_bar(bar, day, 480 + i * 5, broker, risk)

    # GBP also swept → SMT divergence NOT present → no trade
    assert len(broker.orders) == 0, (
        f"SMT filter should have blocked the trade (GBP also swept), got {len(broker.orders)} order(s)"
    )
    assert strat.smt_hi_swept, "GBP should be marked as having swept its Asian high"


# ---------------------------------------------------------------------------
# Test 8: SMT filter allows trade when confirmation pair did NOT sweep
# ---------------------------------------------------------------------------

def test_smt_allows_when_confirmation_pair_did_not_sweep():
    """When EUR sweeps high but GBP did NOT sweep its Asian high → divergence
    confirmed → SMT filter must allow the short entry."""
    cfg = {**CFG, "smt_filter": True, "smt_min_pips": 1.0}
    strat = LondonSweep(cfg, PIP_)
    broker = FakeBroker()
    risk = FakeRisk()
    day = _day()
    asian_hi, asian_lo = 1.0850, 1.0800
    gbp_asian_hi = 1.2600

    for m in range(0, 480, 5):
        bar = _make_bar(1.0820, asian_hi, asian_lo, 1.0820,
                        smt_high=gbp_asian_hi, smt_low=1.2550)
        strat.on_bar(bar, day, m, broker, risk)

    # Sweep window: EUR sweeps high, GBP stays BELOW its Asian high (divergence)
    sweep_bars = [
        # EUR                                           GBP H/L — stays below gbp_asian_hi
        (1.0848, 1.0852, 1.0845, 1.0848,  gbp_asian_hi - 0.0005, 1.2590),  # idx 0
        (1.0847, 1.0851, 1.0843, 1.0847,  gbp_asian_hi - 0.0004, 1.2591),  # idx 1
        (1.0845, 1.0847, 1.0840, 1.0845,  gbp_asian_hi - 0.0006, 1.2589),  # idx 2 — EUR swing low
        (1.0846, 1.0850, 1.0843, 1.0846,  gbp_asian_hi - 0.0005, 1.2590),  # idx 3
        (1.0848, 1.0852, 1.0845, 1.0848,  gbp_asian_hi - 0.0004, 1.2591),  # idx 4 — confirms swing
        (1.0855, 1.0860, 1.0853, 1.0855,  gbp_asian_hi - 0.0003, 1.2592),  # idx 5 — EUR sweeps, GBP doesn't
        (1.0853, 1.0855, 1.0848, 1.0852,  gbp_asian_hi - 0.0004, 1.2591),  # idx 6
        (1.0848, 1.0850, 1.0838, 1.0838,  gbp_asian_hi - 0.0005, 1.2590),  # idx 7 — EUR BOS
    ]
    for i, row in enumerate(sweep_bars):
        o, h, l, c, sh, sl = row
        bar = _make_bar(o, h, l, c, smt_high=sh, smt_low=sl)
        strat.on_bar(bar, day, 480 + i * 5, broker, risk)

    # GBP did NOT sweep → divergence → trade should fire
    assert len(broker.orders) == 1, (
        f"SMT divergence confirmed (GBP didn't sweep) — expected 1 order, got {len(broker.orders)}"
    )
    assert broker.orders[0].side == -1, "Expected short"
    assert not strat.smt_hi_swept, "GBP should NOT be marked as swept"
