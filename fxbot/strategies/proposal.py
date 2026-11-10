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
