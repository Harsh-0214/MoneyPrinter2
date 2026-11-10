"""Risk management: position sizing, daily kill switch, news blackout."""
import numpy as np
import pandas as pd


class RiskManager:
    def __init__(self, cfg, pip):
        self.risk_pct = float(cfg["risk_per_trade_pct"])
        self.max_daily_loss_pct = float(cfg["max_daily_loss_pct"])
        self.max_leverage = float(cfg["max_leverage"])
        self.min_units = int(cfg["min_units"])
        self.pip = pip
        self.day_start_equity = None
        # Account-currency value of 1.0 price unit per 1 unit traded. 1.0 when the
        # account currency is the quote currency (USD account, XXX/USD pair).
        # The live runner sets this from MT5 each bar (e.g. ~1.40 for a CAD account).
        self.quote_to_account = 1.0
        self.blackout_ns = int(cfg.get("news_blackout_minutes", 30)) * 60 * 10**9
        self.news = np.array([], dtype=np.int64)
        if cfg.get("news_file"):
            times = pd.to_datetime(pd.read_csv(cfg["news_file"])["time"], utc=True)
            self.news = np.sort(times.astype("int64").to_numpy())

    def new_day(self, equity):
        self.day_start_equity = equity

    def daily_loss_hit(self, equity):
        if not self.day_start_equity:
            return False
        change_pct = (equity - self.day_start_equity) / self.day_start_equity * 100
        return change_pct <= -self.max_daily_loss_pct

    def near_news(self, t_utc):
        if len(self.news) == 0:
            return False
        t = t_utc.value
        i = np.searchsorted(self.news, t)
        for j in (i - 1, i):
            if 0 <= j < len(self.news) and abs(self.news[j] - t) <= self.blackout_ns:
                return True
        return False

    def can_trade(self, equity, t_utc):
        return not self.daily_loss_hit(equity) and not self.near_news(t_utc)

    def position_size(self, equity, entry_price, stop_price, spread_pips=0.0):
        """Units such that hitting the stop loses risk_per_trade_pct of equity."""
        dist = abs(entry_price - stop_price) + spread_pips * self.pip
        if dist <= 0:
            return 0
        fx = self.quote_to_account if self.quote_to_account > 0 else 1.0
        units = equity * self.risk_pct / 100 / (dist * fx)
        units = min(units, equity * self.max_leverage / (entry_price * fx))   # leverage cap
        return int(units // self.min_units * self.min_units)
