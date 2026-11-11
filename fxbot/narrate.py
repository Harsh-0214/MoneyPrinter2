"""Plain-English narration for the terminal.

The terminal shows short, comment-style lines that explain what the bot is doing:

    08:35  # London wants to SELL: price broke below the overnight range.
    08:35  # Trade size: risking 500 CAD with a 31.2-pip stop = 1.13 lots.
    08:35  # Order sent: SELL 1.13 lots at 1.34283. Filled.

The detailed technical log still goes to logs/live_<PAIR>_<date>.log for debugging.

How it plugs in:
  * say(...)            - any code can narrate a line
  * NarratingBroker     - wraps the broker; narrates every order, stop move and close
                          (so strategies don't need to know narration exists)
"""
import logging
from datetime import datetime

narrator = logging.getLogger("fxbot.narrate")

# Readable names for order tags (the tag is set by each strategy)
TAG_WHY = {
    "short_break": "price broke below the overnight range and stayed there",
    "long_break": "price broke above the overnight range and stayed there",
    "sweep_short": "price faked a move above the overnight high, then reversed down",
    "sweep_long": "price faked a move below the overnight low, then reversed up",
    "dpb_long": "a sharp dip inside an uptrend (buy the dip)",
    "dpb_short": "a sharp rally inside a downtrend (sell the rally)",
    "trend_long": "a daily close above the breakout level (new trend)",
    "trend_short": "a daily close below the breakout level",
}
REASON_WHY = {
    "session_exit": "the session ended (16:00 London close-out)",
    "trend_exit": "the trend exit was hit",
    "pullback_exit": "price snapped back, so the pullback is done",
    "time_exit": "it reached its maximum holding time",
}


def setup(console=True, file_handler=None):
    """Narration goes to the terminal (as '# ...' lines) and into the log file."""
    narrator.setLevel(logging.INFO)
    narrator.propagate = False
    if console and not any(getattr(h, "_fxbot_console", False) for h in narrator.handlers):
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s  # %(message)s", "%H:%M"))
        h._fxbot_console = True
        narrator.addHandler(h)
    if file_handler is not None and file_handler not in narrator.handlers:
        narrator.addHandler(file_handler)


def say(text, *args):
    narrator.info(text, *args)


def money(x, currency="CAD"):
    return f"{x:+,.2f} {currency}" if x else f"0.00 {currency}"


class NarratingBroker:
    """Wraps a broker and explains each action in plain English. Behaviour is
    unchanged: every call is passed straight through to the real broker."""

    def __init__(self, broker, who, symbol, pip, contract, risk_money, currency="CAD",
                 open_risk_fn=None, risk_cap=None):
        self._b = broker
        self.who, self.symbol, self.pip, self.contract = who, symbol, pip, contract
        self.risk_money, self.currency = risk_money, currency      # e.g. 500 CAD per trade
        self.open_risk_fn, self.risk_cap = open_risk_fn, risk_cap

    # ---- actions that get narrated ----------------------------------------
    def submit(self, order):
        side = "BUY" if order.side == 1 else "SELL"
        name = self.symbol.rstrip(".")
        say("%s wants to %s %s: %s.", self.who, side, name, TAG_WHY.get(order.tag, order.tag))
        if self.open_risk_fn is not None:
            try:
                used = self.open_risk_fn()
                cap = f" (limit {self.risk_cap:,.0f})" if self.risk_cap else ""
                say("Safety checks passed: daily loss OK, no blocking news, %s %s already at risk%s.",
                    f"{used:,.0f}", self.currency, cap)
            except Exception:
                pass
        lots = order.units / self.contract if self.contract else order.units
        target = f"target {order.take_profit:g}" if order.take_profit else "no fixed target"
        say("Trade size: risking ~%s %s -> %.2f lots. Stop %g, %s.",
            f"{self.risk_money:,.0f}", self.currency, lots, order.stop_loss, target)
        ok = self._b.submit(order)
        say("Order sent: %s %.2f lots %s. %s", side, lots, name,
            "Filled." if ok else "NOT sent/filled (see the log file for the reason).")
        return ok

    def update_stop(self, new_stop_price):
        pos = self._b.position()
        self._b.update_stop(new_stop_price)
        if pos is not None and abs(new_stop_price - pos.entry_price) < self.pip / 2:
            say("%s moved the stop to the entry price. This trade can no longer lose.", self.who)
        else:
            say("%s moved the stop to %.5f to lock in more of the move.", self.who, new_stop_price)

    def close_position(self, reason="manual"):
        if self._b.position() is not None:
            say("%s is closing its trade because %s.", self.who, REASON_WHY.get(reason, reason))
        return self._b.close_position(reason)

    # ---- pass-through -----------------------------------------------------
    def equity(self): return self._b.equity()
    def position(self): return self._b.position()
    def current_spread_pips(self): return self._b.current_spread_pips()
    def shutdown(self): return self._b.shutdown()

    @property
    def trades(self):
        return self._b.trades


def closed_trade(who, t, currency="CAD"):
    """Narrate a finished trade (t = fxbot.brokers.base.Trade)."""
    how = str(t.exit_reason)
    if "tp" in how.lower():
        how = "it hit its target"
    elif "sl" in how.lower():
        how = "it hit its stop"
    else:
        how = REASON_WHY.get(how, how)
    # (P/L only: MT5 history doesn't keep the original stop, so R is computed by run_report.py)
    say("%s trade closed: %s, %s.", who, money(t.pnl, currency), how)


def quiet_poll(statuses):
    """One short line for a candle where nothing happened."""
    now = datetime.now().strftime("%H:%M")
    return f"Checked the new candle ({now}). No trade. " + " | ".join(statuses)
