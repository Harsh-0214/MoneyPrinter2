"""MT5Broker — live/demo MetaTrader 5 implementation of the Broker interface.

cfg["live"] fields required:
    symbol      : str  — broker symbol name, e.g. "EURUSD" or "EURUSD.a"
    server_tz   : str  — broker server timezone, e.g. "Europe/Helsinki"
    magic       : int  — unique magic number so the bot only manages its own orders
"""
import os
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
from dotenv import load_dotenv

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from .base import LOT, Broker, Order, Position, Trade

PIP = 0.0001  # EUR/USD


class MT5Broker(Broker):
    def __init__(self, cfg: dict, logger, allow_live: bool = False):
        if mt5 is None:
            raise ImportError(
                "MetaTrader5 package is not installed or this is not Windows."
            )

        load_dotenv()

        live = cfg["live"]
        self._symbol = live["symbol"]
        self._magic = int(live["magic"])
        self._commission_per_lot = float(
            cfg["costs"].get("commission_per_lot_per_side", 0.0)
        )
        self._logger = logger

        login = int(os.environ["MT5_LOGIN"])
        password = os.environ["MT5_PASSWORD"]
        server = os.environ["MT5_SERVER"]
        path = os.environ.get("MT5_TERMINAL_PATH")

        init_kwargs: dict = dict(login=login, password=password, server=server)
        if path:
            init_kwargs["path"] = path

        if not mt5.initialize(**init_kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

        account = mt5.account_info()
        if account is None:
            mt5.shutdown()
            raise RuntimeError("Could not retrieve account info after connecting.")

        if account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO and not allow_live:
            mt5.shutdown()
            raise RuntimeError(
                "Safety: not a demo account. Pass allow_live=True to override."
            )

        mode = "DEMO" if account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "LIVE"
        logger.info(
            "Connected to MT5 | account=%d | %s | server=%s | equity=%.2f",
            account.login,
            mode,
            account.server,
            account.equity,
        )

    # ------------------------------------------------------------------
    # Broker interface
    # ------------------------------------------------------------------

    def equity(self) -> float:
        return mt5.account_info().equity

    def position(self) -> Optional[Position]:
        positions = mt5.positions_get(symbol=self._symbol)
        if not positions:
            return None
        for p in positions:
            if p.magic != self._magic:
                continue
            side = 1 if p.type == mt5.ORDER_TYPE_BUY else -1
            return Position(
                side=side,
                units=round(p.volume * LOT),
                entry_price=p.price_open,
                entry_time=pd.Timestamp(p.time, unit="s", tz="UTC"),
                stop_loss=p.sl,
                take_profit=p.tp if p.tp != 0.0 else None,
                risk_per_unit=abs(p.price_open - p.sl),
                entry_commission=self._commission_per_lot * p.volume,
                tag=p.comment,
            )
        return None

    def submit(self, order: Order) -> bool:
        info = mt5.symbol_info(self._symbol)
        if info is None:
            self._logger.error("submit: symbol %s not found", self._symbol)
            return False

        lots = self._to_lots(order.units, info)
        if lots <= 0:
            self._logger.error("submit: computed lots=0 for units=%d", order.units)
            return False

        tick = mt5.symbol_info_tick(self._symbol)
        price = tick.ask if order.side == 1 else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if order.side == 1 else mt5.ORDER_TYPE_SELL

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self._symbol,
            "volume": lots,
            "type": order_type,
            "price": price,
            "sl": order.stop_loss,
            "tp": order.take_profit or 0.0,
            "deviation": 20,
            "magic": self._magic,
            "comment": order.tag,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }

        self._logger.info(
            "ORDER %s %.2f lots @ ~%.5f  SL=%.5f  TP=%.5f  spread=%.1f pips",
            "BUY" if order.side == 1 else "SELL",
            lots,
            price,
            order.stop_loss,
            order.take_profit or 0.0,
            self.current_spread_pips(),
        )

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self._logger.error(
                "order_send failed: retcode=%d '%s' | last_error=%s",
                result.retcode,
                result.comment,
                mt5.last_error(),
            )
            return False

        self._logger.info(
            "Order filled: ticket=%d fill_price=%.5f requested=%.5f",
            result.order,
            result.price,
            price,
        )
        return True

    def close_position(self, reason: str = "manual") -> None:
        pos = self.position()
        if pos is None:
            return

        info = mt5.symbol_info(self._symbol)
        if info is None:
            self._logger.error("close_position: symbol %s not found", self._symbol)
            return

        close_type = mt5.ORDER_TYPE_SELL if pos.side == 1 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(self._symbol)
        price = tick.bid if pos.side == 1 else tick.ask
        lots = self._to_lots(pos.units, info)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self._symbol,
            "volume": lots,
            "type": close_type,
            "price": price,
            "deviation": 20,
            "magic": self._magic,
            "comment": reason,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }

        self._logger.info("Closing position: reason=%s price=%.5f", reason, price)
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self._logger.error(
                "close_position failed: retcode=%d '%s' | last_error=%s",
                result.retcode,
                result.comment,
                mt5.last_error(),
            )
        else:
            self._logger.info(
                "Position closed: ticket=%d fill_price=%.5f", result.order, result.price
            )

    def current_spread_pips(self) -> float:
        tick = mt5.symbol_info_tick(self._symbol)
        return (tick.ask - tick.bid) / PIP

    # ------------------------------------------------------------------
    # Additional methods
    # ------------------------------------------------------------------

    @property
    def trades(self) -> List[Trade]:
        """Today's closed trades built from MT5 deal history, filtered by magic."""
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        deals = mt5.history_deals_get(today, datetime.now(timezone.utc))
        if not deals:
            return []

        by_pos: dict = {}
        for d in deals:
            if d.magic != self._magic:
                continue
            by_pos.setdefault(d.position_id, []).append(d)

        result = []
        for _, ds in by_pos.items():
            entry = next((d for d in ds if d.entry == mt5.DEAL_ENTRY_IN), None)
            exits = [d for d in ds if d.entry == mt5.DEAL_ENTRY_OUT]
            if entry is None or not exits:
                continue

            exit_deal = exits[-1]
            side = 1 if entry.type == mt5.DEAL_TYPE_BUY else -1
            units = round(entry.volume * LOT)
            total_commission = sum(d.commission for d in ds)
            total_pnl = sum(d.profit for d in ds) + total_commission

            # r_multiple: MT5 deals don't store the original SL price, so we
            # approximate using the actual risk taken (entry -> exit distance).
            # This won't match the sim's r_multiple exactly, but is good enough
            # for logging. The kill switch uses live equity, not this value.
            dist = abs(exit_deal.price - entry.price) * units
            r_mult = (total_pnl / dist) if dist > 0 else 0.0

            result.append(
                Trade(
                    side=side,
                    units=units,
                    entry_time=pd.Timestamp(entry.time, unit="s", tz="UTC"),
                    entry_price=entry.price,
                    exit_time=pd.Timestamp(exit_deal.time, unit="s", tz="UTC"),
                    exit_price=exit_deal.price,
                    pnl=total_pnl,
                    commission=total_commission,
                    r_multiple=r_mult,
                    exit_reason=exit_deal.comment or "unknown",
                    tag=entry.comment or "",
                )
            )

        return result

    def shutdown(self) -> None:
        mt5.shutdown()
        self._logger.info("MT5 connection closed.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_lots(self, units: int, symbol_info) -> float:
        """Convert integer units to a valid lot size for this symbol."""
        step = symbol_info.volume_step
        lots = round(units / LOT / step) * step
        lots = max(symbol_info.volume_min, min(symbol_info.volume_max, lots))
        return round(lots, 8)

    def _filling_mode(self, symbol_info):
        """Pick the best filling mode supported by this symbol.

        filling_mode bitmask: bit 0 = FOK, bit 1 = IOC.
        IOC is preferred; fall back to RETURN for brokers that support neither.
        """
        if symbol_info.filling_mode & 2:
            return mt5.ORDER_FILLING_IOC
        if symbol_info.filling_mode & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN
