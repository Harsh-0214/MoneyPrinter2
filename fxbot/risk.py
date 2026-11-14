"""Risk management: position sizing, daily kill switch, news blackout."""
import numpy as np
import pandas as pd

from .news import currencies_for_symbol, empty_calendar, filter_currencies, load_calendar


def resolve_news_currencies(setting, symbol):
    """risk.news_currencies: "auto" (default) = derived from the symbol (EURUSD -> EUR, USD;
    XAUUSD -> USD), a list like [USD, GBP], or "all"/None = every event. With no symbol
    known, "auto" means every event (old behaviour)."""
    if setting is None or (isinstance(setting, str) and setting.lower() == "all"):
        return None
    if isinstance(setting, str) and setting.lower() == "auto":
        cur = currencies_for_symbol(symbol) if symbol else []
        return cur or None
    return [str(c).upper() for c in setting]


class RiskManager:
    def __init__(self, cfg, pip, symbol=None):
        self.risk_pct = float(cfg["risk_per_trade_pct"])
        self.max_daily_loss_pct = float(cfg["max_daily_loss_pct"])
        self.max_leverage = float(cfg["max_leverage"])
        self.min_units = int(cfg["min_units"])
        # Skip trades whose stop is closer than this many spreads (0 = off): such stops
        # get knocked out by noise and pay the spread as a big share of the risk.
        self.min_stop_spreads = float(cfg.get("min_stop_spreads", 0) or 0)
        self.skipped_tight_stops = 0
        self.pip = pip
        self.day_start_equity = None
        # Account-currency value of 1.0 price unit per 1 unit traded. 1.0 when the
        # account currency is the quote currency (USD account, XXX/USD pair).
        # The live runner sets this from MT5 each bar (e.g. ~1.40 for a CAD account).
        self.quote_to_account = 1.0

        # --- news blackout ---------------------------------------------------
        # news_file (legacy, always honoured): CSV with a UTC `time` column (optional
        #   `currency`, `event`). news_filter: true additionally loads news_calendar
        #   (the historical calendar for backtests; the live runner swaps in the live
        #   feed with set_news()). Only NEW entries are blocked; open trades are kept.
        self.blackout_ns = int(cfg.get("news_blackout_minutes", 30)) * 60 * 10**9
        self.news_currencies = resolve_news_currencies(cfg.get("news_currencies", "auto"), symbol)
        self.news_day_block = [s.lower() for s in (cfg.get("news_day_block") or [])]
        # Open-trade protection before high-impact news (None = off): "close",
        # "breakeven" (move the stop to entry if the trade is in profit) or
        # "breakeven_or_close" (in profit -> breakeven, otherwise close). Applied
        # `news_protect_minutes` before the event to trades whose tag does NOT start
        # with one of news_protect_skip_tags (multi-day strategies ride news by design).
        self.news_protect = cfg.get("news_protect")
        self.news_protect_minutes = float(cfg.get("news_protect_minutes", 20))
        self.news_protect_skip = tuple(cfg.get("news_protect_skip_tags", ["trend_", "dpb_"]))
        self.on_news_skip = None          # live: callback(event_dict, t_utc) when news blocks an entry
        self.last_news_block = None
        self._static_news = load_calendar(cfg["news_file"]) if cfg.get("news_file") else empty_calendar()
        cal = (load_calendar(cfg["news_calendar"])
               if cfg.get("news_filter") and cfg.get("news_calendar") else None)
        self.set_news(cal)

    # ------------------------------------------------------------------ news
    def set_news(self, events=None):
        """Replace the dynamic calendar (live feed / historical file). The legacy
        news_file events always stay. Events are filtered to this market's currencies."""
        frames = [f for f in (self._static_news, events) if f is not None and len(f)]
        df = pd.concat(frames, ignore_index=True).sort_values("time") if frames else empty_calendar()
        df = filter_currencies(df, self.news_currencies).reset_index(drop=True)
        self.news_events = df
        # as_unit("ns"): pandas 3 parses to microseconds; compare in ns like Timestamp.value
        self.news = (df["time"].dt.as_unit("ns").astype("int64").to_numpy() if len(df)
                     else np.array([], dtype=np.int64))
        self._day_block = {}
        if self.news_day_block and len(df):
            for k, row in df.iterrows():
                name = str(row["event"]).lower()
                if any(key in name for key in self.news_day_block):
                    d = row["time"].tz_convert("Europe/London").date()
                    self._day_block.setdefault(d, k)

    def news_hit(self, t_utc):
        """The calendar event that blocks an entry at t_utc, or None."""
        if len(self.news) == 0:
            return None
        t = pd.Timestamp(t_utc)
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        v = t.value
        i = np.searchsorted(self.news, v)
        for j in (i - 1, i):
            if 0 <= j < len(self.news) and abs(self.news[j] - v) <= self.blackout_ns:
                return self.news_events.iloc[j].to_dict()
        if self._day_block:
            k = self._day_block.get(t.tz_convert("Europe/London").date())
            if k is not None:
                return self.news_events.iloc[k].to_dict()
        return None

    def event_ahead(self, t_utc, minutes):
        """The next calendar event within `minutes` AFTER t_utc (for protecting open trades)."""
        if len(self.news) == 0:
            return None
        t = pd.Timestamp(t_utc)
        v = (t.tz_localize("UTC") if t.tzinfo is None else t).value
        i = np.searchsorted(self.news, v)
        if i < len(self.news) and self.news[i] - v <= minutes * 60 * 10**9:
            return self.news_events.iloc[i].to_dict()
        return None

    def near_news(self, t_utc):
        return self.news_hit(t_utc) is not None

    # ------------------------------------------------------------------ gates
    def new_day(self, equity):
        self.day_start_equity = equity

    def daily_loss_hit(self, equity):
        if not self.day_start_equity:
            return False
        change_pct = (equity - self.day_start_equity) / self.day_start_equity * 100
        return change_pct <= -self.max_daily_loss_pct

    def can_trade(self, equity, t_utc):
        if self.daily_loss_hit(equity):
            ch = (equity - self.day_start_equity) / self.day_start_equity * 100
            self.skip_note = ("daily_loss", f"the account is down {ch:.1f}% today ({self.day_start_equity:,.2f} -> "
                                            f"{equity:,.2f}), past the {self.max_daily_loss_pct:g}% daily loss limit, "
                                            f"so no new trades until tomorrow")
            return False
        ev = self.news_hit(t_utc)
        if ev is not None:
            self.last_news_block = ev
            if self.on_news_skip is not None:
                try:
                    self.on_news_skip(ev, t_utc)
                except Exception:
                    pass
            return False
        return True

    def position_size(self, equity, entry_price, stop_price, spread_pips=0.0):
        """Units such that hitting the stop loses risk_per_trade_pct of equity."""
        if self.min_stop_spreads > 0 and spread_pips > 0 and                 abs(entry_price - stop_price) < self.min_stop_spreads * spread_pips * self.pip:
            self.skipped_tight_stops += 1
            self.skip_note = ("tight_stop", f"its stop is {abs(entry_price - stop_price) / self.pip:.1f} pips away, "
                                            f"closer than {self.min_stop_spreads:g} x the {spread_pips:.1f}-pip spread")
            return 0                                   # stop too tight for the spread
        dist = abs(entry_price - stop_price) + spread_pips * self.pip
        if dist <= 0:
            return 0
        fx = self.quote_to_account if self.quote_to_account > 0 else 1.0
        units = equity * self.risk_pct / 100 / (dist * fx)
        units = min(units, equity * self.max_leverage / (entry_price * fx))   # leverage cap
        out = int(units // self.min_units * self.min_units)
        if out <= 0:
            self.skip_note = ("size", f"risking {self.risk_pct:g}% of {equity:,.2f} with a {dist / self.pip:.1f}-pip "
                                      f"stop gives {units:,.0f} units, less than the minimum {self.min_units:,}")
        return out


def protect_before_news(risk, broker, bar_close_utc, last_price, spread_price=0.0):
    """Shared by the backtest and the live bot. Returns the action taken (or None)."""
    mode = getattr(risk, "news_protect", None)
    pos = broker.position()
    if not mode or pos is None or str(pos.tag or "").startswith(risk.news_protect_skip):
        return None
    ev = risk.event_ahead(bar_close_utc, risk.news_protect_minutes)
    if ev is None:
        return None
    in_profit = (last_price - pos.entry_price) * pos.side > spread_price
    if mode == "close" or (mode == "breakeven_or_close" and not in_profit):
        broker.close_position("news_protect")
        return "close"
    if mode in ("breakeven", "breakeven_or_close") and in_profit and             (pos.entry_price - pos.stop_loss) * pos.side > 0:
        broker.update_stop(pos.entry_price)
        return "breakeven"
    return None
