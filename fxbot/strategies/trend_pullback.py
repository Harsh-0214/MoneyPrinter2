"""Pullback-in-trend (RSI-2 style mean reversion WITH the higher-timeframe trend).

Trend:  daily trend from bar.daily_ema (price above -> longs only, below -> shorts only).
Entry:  inside the session window, when the short RSI (rsi_period, default 2)
        drops below `oversold` in an uptrend (buy the dip) or rises above
        `overbought` in a downtrend (sell the rally).
Exit:   RSI crosses back through `exit_rsi`, or close crosses the fast EMA,
        or after `max_hold_bars`, or at `exit_time`. Hard stop at stop_atr x ATR.
Can trade several times a day (max_trades_per_day, cooldown_bars between trades).
"""
from datetime import time
from typing import Optional

from ..brokers.base import Order
from .proposal import TradeProposal, manages

NAME = "trend_pullback"


def _minutes(hhmm):
    t = time.fromisoformat(hhmm)
    return t.hour * 60 + t.minute


class TrendPullback:
    def __init__(self, cfg, pip):
        self.pip = pip
        self.n          = int(cfg.get("rsi_period", 2))
        self.oversold   = float(cfg.get("oversold", 10))
        self.overbought = float(cfg.get("overbought", 90))
        self.exit_rsi   = float(cfg.get("exit_rsi", 50))
        self.exit_mode  = cfg.get("exit_mode", "rsi")         # rsi | ema
        self.ema_n      = int(cfg.get("exit_ema", 5))
        self.atr_n      = int(cfg.get("atr_period", 14))
        self.stop_atr   = float(cfg.get("stop_atr", 2.0))
        self.max_hold   = int(cfg.get("max_hold_bars", 24))
        self.start      = _minutes(cfg.get("entry_start", "07:00"))
        self.end        = _minutes(cfg.get("entry_end", "19:00"))
        self.exit_min   = _minutes(cfg.get("exit_time", "20:00"))
        self.max_trades = int(cfg.get("max_trades_per_day", 3))
        self.cooldown   = int(cfg.get("cooldown_bars", 3))
        self.score      = float(cfg.get("score", 60))
        self.need_trend = cfg.get("daily_trend_filter", True)
        self._skip_days = set(int(d) for d in cfg.get("skip_days", []))
        self.prev_close = None
        self.avg_gain = self.avg_loss = None
        self.rsi = 50.0
        self.ema = None
        self.atr = None
        self.held = 0
        self.since_exit = 99
        self.day = None
        self.trades_today = 0
        self.skip_today = False

    def _indicators(self, bar):
        c = bar.close
        if self.prev_close is not None:
            ch = c - self.prev_close
            g, l = max(ch, 0.0), max(-ch, 0.0)
            if self.avg_gain is None:
                self.avg_gain, self.avg_loss = g, l
            else:
                self.avg_gain += (g - self.avg_gain) / self.n
                self.avg_loss += (l - self.avg_loss) / self.n
            self.rsi = 100.0 if self.avg_loss == 0 else 100 - 100 / (1 + self.avg_gain / self.avg_loss)
            tr = max(bar.high - bar.low, abs(bar.high - self.prev_close), abs(bar.low - self.prev_close))
            self.atr = tr if self.atr is None else self.atr + (tr - self.atr) / self.atr_n
        a = 2 / (self.ema_n + 1)
        self.ema = c if self.ema is None else self.ema + a * (c - self.ema)
        self.prev_close = c

    def propose(self, bar, local_day, local_min, broker, risk) -> Optional[TradeProposal]:
        if local_day != self.day:
            self.day = local_day
            self.trades_today = 0
            dow = int(local_day.astype("datetime64[D]").astype(object).weekday())
            self.skip_today = dow in self._skip_days
        self._indicators(bar)
        pos = broker.position()
        if pos is not None:
            if not manages(pos, NAME):
                return None
            self.held += 1
            s = pos.side
            done = (self.exit_mode == "rsi" and ((s == 1 and self.rsi > self.exit_rsi) or
                                                  (s == -1 and self.rsi < self.exit_rsi))) or \
                   (self.exit_mode == "ema" and ((s == 1 and bar.close > self.ema) or
                                                  (s == -1 and bar.close < self.ema)))
            if done or self.held >= self.max_hold or local_min >= self.exit_min:
                broker.close_position("pullback_exit" if done else "time_exit")
                self.since_exit = 0
            return None
        self.since_exit += 1
        if self.skip_today or self.trades_today >= self.max_trades or self.atr is None:
            return None
        if not (self.start <= local_min < self.end) or self.since_exit <= self.cooldown:
            return None
        de = getattr(bar, "daily_ema", float("nan"))
        up = de == de and bar.close > de
        down = de == de and bar.close < de
        if not self.need_trend:
            up = down = True
        side = 1 if (up and self.rsi < self.oversold) else (-1 if (down and self.rsi > self.overbought) else 0)
        if side == 0:
            return None
        spread = bar.spread_pips * self.pip
        entry = bar.close + (spread if side == 1 else 0.0)
        stop = entry - side * self.stop_atr * self.atr
        eq = broker.equity()
        if not risk.can_trade(eq, bar.Index):
            return None
        units = risk.position_size(eq, entry, stop, broker.current_spread_pips())
        if units <= 0:
            return None
        self.held = 0
        return TradeProposal(Order(side, units, stop, None, "pb_long" if side == 1 else "pb_short"),
                             self.score, NAME)

    def mark_fired(self):
        self.trades_today += 1

    def on_bar(self, bar, local_day, local_min, broker, risk):
        p = self.propose(bar, local_day, local_min, broker, risk)
        if p and broker.submit(p.order):
            self.mark_fired()
