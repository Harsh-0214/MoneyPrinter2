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
}
_ALL = tuple(p for ps in TAG_PREFIXES.values() for p in ps)


def manages(position, strategy_name):
    tag = str(getattr(position, "tag", "") or "")
    if tag.startswith(TAG_PREFIXES[strategy_name]):
        return True
    return not tag.startswith(_ALL)


def move_stop_to_breakeven(position, broker, bar_close, trigger_r):
    """Move the stop to entry once price is trigger_r R in profit (0 = off)."""
    if trigger_r <= 0 or position.risk_per_unit <= 0:   # MT5 reports 0 once at entry
        return
    if (bar_close - position.entry_price) * position.side / position.risk_per_unit >= trigger_r:
        be = position.entry_price
        if (position.side == 1 and be > position.stop_loss) or \
           (position.side == -1 and be < position.stop_loss):
            broker.update_stop(be)
