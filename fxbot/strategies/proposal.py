"""TradeProposal — scored setup returned by strategy.propose().

Each morning strategy evaluates its own setup quality and returns a
TradeProposal instead of submitting directly to the broker.  The backtest
(or live router) collects all proposals on a given bar and executes the one
with the highest score, ensuring the best-quality setup wins regardless of
which strategy's signal appeared first.
"""
from dataclasses import dataclass

from ..brokers.base import Order


@dataclass
class TradeProposal:
    order: Order
    score: float          # higher = better setup quality
    strategy_name: str


# Order-tag prefixes per strategy. A strategy only trails / session-exits a
# position whose tag it owns; positions owned by ANOTHER known strategy are
# left alone; unknown tags are still managed so nothing is left unattended.
TAG_PREFIXES = {
    "london_sweep":    ("sweep_",),
    "london_breakout": ("long_break", "short_break"),
    "tiny_range_fade": ("fade_",),
    "london_close_reversal": ("lcr_",),
    "trend_follow":    ("trend_",),
    "key_levels":      ("kl_",),
    "opening_range":   ("orb",),
    "trend_pullback":  ("pb_",),
    "daily_pullback":  ("dpb_",),
    "vol_breakout":    ("vbo_",),
    "nr_breakout":     ("nrb_",),
    "turtle_soup":     ("ts_",),
    "eighty_twenty":   ("e20_",),
    "holy_grail":      ("hg_",),
    "id_nr4":          ("idnr_",),
    "td_setup":        ("td_",),
    "bb_squeeze":      ("bbs_",),
    "double_seven":    ("d7_",),
    "weekend_gap":     ("wgap_",),
}
_ALL = tuple(p for ps in TAG_PREFIXES.values() for p in ps)


def manages(position, strategy_name):
    tag = str(getattr(position, "tag", "") or "")
    if tag.startswith(TAG_PREFIXES[strategy_name]):
        return True
    return not tag.startswith(_ALL)


class TrailState:
    """Per-strategy trailing-stop memory for the open position.

    Remembers the trade's ORIGINAL risk (MT5 reports a shrinking risk once the
    stop moves) and the best price reached since entry.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.init_risk = None
        self.best = None

    def update(self, position, bar):
        if self.init_risk is None:
            self.init_risk = position.risk_per_unit if position.risk_per_unit > 0 else None
        hi, lo = bar.high, bar.low
        if position.side == 1:
            self.best = hi if self.best is None else max(self.best, hi)
        else:
            self.best = lo if self.best is None else min(self.best, lo)


def trail_stop(position, broker, trail, start_r, dist_r):
    """Once the trade has been start_r R in profit, keep the stop dist_r R behind the
    best price reached. Only ever tightens. start_r <= 0 disables it."""
    if start_r <= 0 or trail.init_risk is None or trail.best is None:
        return
    r = trail.init_risk
    peak_r = (trail.best - position.entry_price) * position.side / r
    if peak_r < start_r:
        return
    new_stop = trail.best - position.side * dist_r * r
    if (position.side == 1 and new_stop > position.stop_loss + 1e-9) or \
       (position.side == -1 and new_stop < position.stop_loss - 1e-9):
        broker.update_stop(new_stop)


def move_stop_to_breakeven(position, broker, bar_close, trigger_r):
    """Move the stop to entry once price is trigger_r R in profit (0 = off)."""
    if trigger_r <= 0 or position.risk_per_unit <= 0:   # MT5 reports 0 once at entry
        return
    if (bar_close - position.entry_price) * position.side / position.risk_per_unit >= trigger_r:
        be = position.entry_price
        if (position.side == 1 and be > position.stop_loss) or \
           (position.side == -1 and be < position.stop_loss):
            broker.update_stop(be)


def extend_target(position, broker, bar, trail, trigger, step_r, lock_r, momentum=0.0):
    """'Let it run': when a trade with a target is at least `trigger` of the way
    there at a bar close (and, if momentum > 0, the bar closed in the top
    `momentum` share of its range in the trade's direction), push the target
    `step_r` R further out and pull the stop to `lock_r` R behind the close
    (never loosening it). Repeats on later bars while the move keeps going.
    R = the trade's ORIGINAL risk (trail.init_risk). trigger <= 0 disables it.
    Returns True if it moved anything."""
    tp, r = position.take_profit, trail.init_risk
    if trigger <= 0 or tp is None or not r:
        return False
    side, entry = position.side, position.entry_price
    total = (tp - entry) * side
    if total <= 0 or (bar.close - entry) * side / total < trigger:
        return False
    if momentum > 0:
        rng = bar.high - bar.low
        strength = ((bar.close - bar.low) if side == 1 else (bar.high - bar.close)) / rng if rng > 0 else 1.0
        if strength < momentum:
            return False
    new_tp = tp + side * step_r * r
    lock = bar.close - side * lock_r * r
    new_sl = lock if (lock - position.stop_loss) * side > 0 else position.stop_loss
    broker.update_stop(new_sl, take_profit=new_tp)
    return True
