"""The broker interface.

The strategy ONLY talks to these methods. SimBroker implements them on
historical data; MT5Broker (next phase) will implement them on MetaTrader.
Switching from simulation to MetaTrader = swapping the broker object.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd

LOT = 100_000  # units in one standard lot


@dataclass
class Order:
    side: int                 # +1 buy, -1 sell
    units: int
    stop_loss: float          # absolute price
    take_profit: Optional[float] = None
    tag: str = ""


@dataclass
class Position:
    side: int
    units: int
    entry_price: float
    entry_time: pd.Timestamp
    stop_loss: float
    take_profit: Optional[float]
    risk_per_unit: float      # distance entry -> stop, in price
    entry_commission: float = 0.0
    tag: str = ""


@dataclass
class Trade:
    side: int
    units: int
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    pnl: float                # net of spread, slippage and commission
    commission: float
    r_multiple: float         # pnl / amount risked
    exit_reason: str
    tag: str = ""


class Broker(ABC):
    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def position(self) -> Optional[Position]: ...

    @abstractmethod
    def submit(self, order: Order) -> bool:
        """Send a market order with attached stop loss / take profit."""

    @abstractmethod
    def close_position(self, reason: str = "manual") -> None: ...

    @abstractmethod
    def update_stop(self, new_stop_price: float) -> None:
        """Move the stop loss on the current open position (trailing stop support)."""

    @abstractmethod
    def current_spread_pips(self) -> float: ...
