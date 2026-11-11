"""Simulated broker: fills orders on historical bars with realistic costs.

Rules (all chosen to be pessimistic rather than flattering):
  * Orders sent at a bar's close fill at the NEXT bar's open (no lookahead).
  * Buys fill at ASK (bid + spread), sells at BID. Slippage on top.
  * Stops fill at the stop price minus slippage, or at the open if price
    gapped through the stop.
  * If stop and target are both touched inside one bar, we assume the
    STOP was hit first (we can't know the order within a bar).
"""
import numpy as np
import pandas as pd

from .base import LOT, Broker, Position, Trade
from ..data import PIP


def compute_spread_pips(df, costs):
    """Spread to charge on each bar: floor, data spread, and rollover widening."""
    spread = pd.Series(float(costs["spread_pips"]), index=df.index)
    if costs.get("use_data_spread", True) and "data_spread_pips" in df.columns:
        spread = np.maximum(spread, df["data_spread_pips"].fillna(0.0))
    ny = df.index.tz_convert("America/New_York")
    mins = ny.hour * 60 + ny.minute
    rollover = (mins >= 16 * 60 + 55) & (mins < 18 * 60)   # 4:55pm - 6pm New York
    spread[rollover] = np.maximum(spread[rollover], float(costs["rollover_spread_pips"]))
    return spread


class SimBroker(Broker):
    def __init__(self, starting_equity, slippage_pips=0.0, commission_per_lot_per_side=0.0, pip=PIP,
                 swap_long_per_lot=0.0, swap_short_per_lot=0.0,
                 swap_long_pct=0.0, swap_short_pct=0.0, inverse_quote=False):
        self.balance = float(starting_equity)
        # inverse_quote: the account currency is the pair's BASE (USD account, USD/JPY).
        # Price moves are in the quote currency (JPY), so P/L is converted at the exit
        # price; per-lot swaps are then already in account currency.
        self.inverse_quote = bool(inverse_quote)
        # Alternative financing model: annual % of position value (e.g. gold longs
        # ~ -6.5%/yr). Charged per night like the per-lot swap (Wed x3).
        self.swap_long_pct = float(swap_long_pct) / 100 / 365
        self.swap_short_pct = float(swap_short_pct) / 100 / 365
        # Overnight financing, USD per 100k units per night (negative = you pay).
        # Charged when a position is held through the 17:00 New York rollover;
        # the Wednesday rollover counts 3 nights (weekend), like real brokers.
        self.swap_long = float(swap_long_per_lot) / LOT
        self.swap_short = float(swap_short_per_lot) / LOT
        self._roll_key = None
        self.pip = pip
        self.slip = slippage_pips * pip
        self.comm_per_unit = commission_per_lot_per_side / LOT
        self.trades = []
        self._pos = None
        self._pending_order = None
        self._pending_close = None
        self._bar = None

    # ---------------- Broker interface ----------------
    def equity(self):
        if self._pos is None or self._bar is None:
            return self.balance
        return self.balance + self._pnl_at(self._exit_price_at_close())

    def position(self):
        return self._pos

    def submit(self, order):
        if self._pos is not None or self._pending_order is not None or order.units <= 0:
            return False
        self._pending_order = order
        return True

    def close_position(self, reason="manual"):
        if self._pos is not None:
            self._pending_close = reason

    def update_stop(self, new_stop_price: float, take_profit=None) -> None:
        if self._pos is not None:
            self._pos.stop_loss = new_stop_price
            if take_profit is not None:
                self._pos.take_profit = take_profit

    def current_spread_pips(self):
        return float(self._bar.spread_pips) if self._bar is not None else 0.0

    # ---------------- simulation ----------------
    def on_bar(self, bar):
        """Process one bar. bar needs: Index, open, high, low, close, spread_pips."""
        self._bar = bar
        t = bar.Index
        spread = bar.spread_pips * self.pip
        bid_o, bid_h, bid_l = bar.open, bar.high, bar.low
        ask_o, ask_h, ask_l = bid_o + spread, bid_h + spread, bid_l + spread

        # 0) overnight swap: did a 17:00 New York rollover pass since the last bar?
        if self.swap_long or self.swap_short or self.swap_long_pct or self.swap_short_pct:
            self._apply_swap(t)

        # 1) close requested on the previous bar -> fill at this open
        if self._pending_close and self._pos is not None:
            px = bid_o - self.slip if self._pos.side == 1 else ask_o + self.slip
            self._exit(t, px, self._pending_close)
        self._pending_close = None

        # 2) new order requested on the previous bar -> fill at this open
        if self._pending_order is not None and self._pos is None:
            o = self._pending_order
            entry = ask_o + self.slip if o.side == 1 else bid_o - self.slip
            risk = (entry - o.stop_loss) * o.side
            if risk > 0:   # skip if price already gapped past the stop
                comm = o.units * self.comm_per_unit
                self.balance -= comm
                self._pos = Position(o.side, o.units, entry, t, o.stop_loss, o.take_profit,
                                     risk, comm, o.tag)
                if self.swap_long or self.swap_short or self.swap_long_pct or self.swap_short_pct:
                    self._roll_key = self._roll_day(t)
        self._pending_order = None

        # 3) stop loss / take profit inside this bar
        p = self._pos
        if p is None:
            return
        if p.side == 1:     # long exits on the BID
            if bid_o <= p.stop_loss:
                self._exit(t, bid_o - self.slip, "stop_gap")
            elif bid_l <= p.stop_loss:
                self._exit(t, p.stop_loss - self.slip, "stop")
            elif p.take_profit is not None and bid_h >= p.take_profit:
                self._exit(t, p.take_profit, "target")
        else:               # short exits on the ASK
            if ask_o >= p.stop_loss:
                self._exit(t, ask_o + self.slip, "stop_gap")
            elif ask_h >= p.stop_loss:
                self._exit(t, p.stop_loss + self.slip, "stop")
            elif p.take_profit is not None and ask_l <= p.take_profit:
                self._exit(t, p.take_profit, "target")

    def close_at_end(self):
        if self._pos is not None and self._bar is not None:
            self._exit(self._bar.Index, self._exit_price_at_close(), "end_of_data")

    # ---------------- helpers ----------------
    @staticmethod
    def _roll_day(t):
        """Rollover 'day' a timestamp belongs to (changes at 17:00 New York)."""
        return (t.tz_convert("America/New_York") - pd.Timedelta(hours=17)).date()

    def _apply_swap(self, t):
        """Charge financing for every 17:00 New York rollover crossed since the last bar.
        Only does work while a position is open (keeps intraday backtests fast)."""
        if self._pos is None:
            return
        key = self._roll_day(t)
        if self._roll_key is not None and key != self._roll_key:
            nights = 0
            d = self._roll_key
            one = pd.Timedelta(days=1).to_pytimedelta()
            while d < key:
                d = d + one          # rollover at 17:00 NY on date d
                wd = d.weekday()
                nights += 3 if wd == 2 else (0 if wd >= 5 else 1)
            rate = self.swap_long if self._pos.side == 1 else self.swap_short
            pct = self.swap_long_pct if self._pos.side == 1 else self.swap_short_pct
            px = self._bar.close if self._bar is not None else self._pos.entry_price
            amt = (rate + pct * (1.0 if self.inverse_quote else px)) * self._pos.units * nights
            self.balance += amt
            self._pos.swap += amt
        self._roll_key = key

    def _exit_price_at_close(self):
        bid_c = self._bar.close
        return bid_c if self._pos.side == 1 else bid_c + self._bar.spread_pips * self.pip

    def _pnl_at(self, px):
        p = self._pos
        gross = p.side * (px - p.entry_price) * p.units
        return gross / px if self.inverse_quote else gross

    def _exit(self, t, px, reason):
        p = self._pos
        gross = self._pnl_at(px)
        comm = p.units * self.comm_per_unit
        self.balance += gross - comm
        total_comm = comm + p.entry_commission
        net = gross - total_comm + p.swap          # swap already booked to balance nightly
        risk_money = p.risk_per_unit * p.units / (p.entry_price if self.inverse_quote else 1.0)
        r = net / risk_money
        self.trades.append(Trade(p.side, p.units, p.entry_time, p.entry_price, t, px,
                                 net, total_comm, r, reason, p.tag, p.swap))
        self._pos = None
