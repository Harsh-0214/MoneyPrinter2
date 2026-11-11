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
from ..data import server_ts_to_utc

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
        # Instrument: pip size (FX 0.0001, gold 0.1). Contract size comes from MT5
        # (EURUSD 100,000 units per lot, FOREX.com XAUUSD 1 oz per lot).
        self._pip = float(cfg.get("instrument", {}).get("pip", PIP))
        self._commission_per_lot = float(
            cfg["costs"].get("commission_per_lot_per_side", 0.0)
        )
        self._logger = logger

        path = os.environ.get("MT5_TERMINAL_PATH")
        if os.environ.get("MT5_LOGIN"):
            init_kwargs: dict = dict(login=int(os.environ["MT5_LOGIN"]),
                                     password=os.environ["MT5_PASSWORD"],
                                     server=os.environ["MT5_SERVER"])
        else:
            # No credentials in .env: attach to the terminal's logged-in account
            logger.info("MT5_LOGIN not set - attaching to the running terminal's account")
            init_kwargs = {}
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
        for p in self._my_positions():
            side = 1 if p.type == mt5.ORDER_TYPE_BUY else -1
            return Position(
                side=side,
                units=round(p.volume * self._contract()),
                entry_price=p.price_open,
                # MT5 position times are server time encoded as epoch -> real UTC
                entry_time=server_ts_to_utc([p.time])[0],
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
            "sl": round(order.stop_loss, info.digits),
            "tp": round(order.take_profit, info.digits) if order.take_profit else 0.0,
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

        ticket = self._my_ticket()
        if ticket is None:
            return
        close_type = mt5.ORDER_TYPE_SELL if pos.side == 1 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(self._symbol)
        price = tick.bid if pos.side == 1 else tick.ask
        lots = self._to_lots(pos.units, info)

        # "position": ticket is REQUIRED on hedging accounts (FOREX.com demo is
        # one) - without it the opposite deal opens a new hedge position.
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self._symbol,
            "position": ticket,
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

    def update_stop(self, new_stop_price: float) -> None:
        pos = self.position()
        if pos is None:
            return
        ticket = self._my_ticket()
        if ticket is None:
            return
        info = mt5.symbol_info(self._symbol)
        if info is not None:
            new_stop_price = round(new_stop_price, info.digits)
            if abs(new_stop_price - pos.stop_loss) < info.point / 2:
                return                                   # unchanged after rounding
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self._symbol,
            "sl": new_stop_price,
            "tp": pos.take_profit or 0.0,
            "position": ticket,
        }
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self._logger.error(
                "update_stop failed: retcode=%d '%s'", result.retcode, result.comment
            )
        else:
            self._logger.info("Stop moved to %.5f", new_stop_price)

    def quote_to_account(self) -> float:
        """Account-currency value of a 1.0 price move per 1 unit traded.

        For a CAD account trading EURUSD or gold this is ~USDCAD (~1.42). Uses
        MT5's own profit calculator (tick_value is wrong for FOREX.com gold).
        """
        info = mt5.symbol_info(self._symbol)
        tick = mt5.symbol_info_tick(self._symbol)
        if info is None or tick is None or not info.trade_contract_size:
            return 1.0
        p = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, self._symbol, 1.0, tick.ask, tick.ask + 1.0)
        if p is None or p <= 0:
            if not info.trade_tick_size:
                return 1.0
            p = info.trade_tick_value / info.trade_tick_size
        return p / info.trade_contract_size

    def current_spread_pips(self) -> float:
        tick = mt5.symbol_info_tick(self._symbol)
        return (tick.ask - tick.bid) / self._pip

    def _contract(self) -> float:
        info = mt5.symbol_info(self._symbol)
        return float(info.trade_contract_size) if info and info.trade_contract_size else float(LOT)

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
            units = round(entry.volume * self._contract())
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

    def _my_positions(self):
        """This bot's open positions on this symbol, oldest first."""
        ps = [p for p in (mt5.positions_get(symbol=self._symbol) or []) if p.magic == self._magic]
        return sorted(ps, key=lambda p: p.time_msc)

    def _my_ticket(self):
        ps = self._my_positions()
        if len(ps) > 1:
            self._logger.error("%d positions open for magic %d - expected 1", len(ps), self._magic)
        return ps[0].ticket if ps else None

    def _to_lots(self, units: int, symbol_info) -> float:
        """Convert integer units to a valid lot size for this symbol."""
        step = symbol_info.volume_step
        lots = round(units / self._contract() / step) * step
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
