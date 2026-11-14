"""What the bot reads from MetaTrader, as short plain lines for the terminal.

    MT5: account 22122201 (DEMO, FOREX.comCA-Demo) | CAD | balance 50,808.65 | equity 50,808.65 | ...
    MT5: USDJPY. | 3 digits | 1 lot = 100,000 | lots 0.01-50 step 0.01 | swap long/short 0.0/0.0 ...
    MT5: [Breakout] candle 14:15 London (15min) O 154.210 H 154.380 L 154.190 C 154.355 | bid 154.351 ...
    MT5: open: Breakout BUY 0.52 lots @ 154.102 | stop 153.730 | now 154.351 | P/L +1,021.40 CAD

Every function takes the MetaTrader5 module (or a stand-in in tests) and never raises:
a failed read gives a shorter line, never a stopped bot.
"""
from datetime import timezone
import zoneinfo

LONDON = zoneinfo.ZoneInfo("Europe/London")


def _fmt(x, digits):
    try:
        return f"{float(x):.{int(digits)}f}"
    except Exception:
        return str(x)


def account_line(mt5):
    a = mt5.account_info()
    if a is None:
        return "MT5: account info not available"
    kind = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(getattr(a, "trade_mode", None), "?")
    lvl = getattr(a, "margin_level", 0) or 0
    return (f"MT5: account {a.login} ({kind}, {a.server}) | {a.currency} | leverage 1:{a.leverage} | "
            f"balance {a.balance:,.2f} | equity {a.equity:,.2f} | margin used {a.margin:,.2f} | "
            f"free margin {a.margin_free:,.2f} | margin level "
            + (f"{lvl:,.0f}%" if a.margin else "n/a (nothing open)"))


def symbol_line(mt5, symbol):
    s = mt5.symbol_info(symbol)
    if s is None:
        return f"MT5: {symbol} symbol info not available"
    return (f"MT5: {symbol} | {s.digits} digits | 1 lot = {s.trade_contract_size:,.0f} | "
            f"lots {s.volume_min:g}-{s.volume_max:g} step {s.volume_step:g} | "
            f"swap long/short {s.swap_long:g}/{s.swap_short:g} | min stop distance {s.trade_stops_level} points")


def price_part(mt5, symbol, pip, normal_spread=None):
    """'bid 1.08412 ask 1.08426 spread 1.4p (normal 1.4)' or ''."""
    t, s = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if t is None or s is None or not t.bid:
        return "no live price right now"
    spread = (t.ask - t.bid) / pip
    norm = f" (normal {normal_spread:g})" if normal_spread else ""
    return f"bid {_fmt(t.bid, s.digits)} ask {_fmt(t.ask, s.digits)} spread {spread:.1f}p{norm}"


def candle_line(label, ts, bar, timeframe, digits):
    """The newest CLOSED candle a strategy just used."""
    when = ts.tz_convert(LONDON).strftime("%H:%M") if getattr(ts, "tzinfo", None) else str(ts)
    o, h, l, c = (_fmt(getattr(bar, k), digits) for k in ("open", "high", "low", "close"))
    return f"[{label}] candle {when} London ({timeframe}) O {o} H {h} L {l} C {c}"


def equity_part(mt5):
    a = mt5.account_info()
    if a is None:
        return ""
    lvl = f", margin level {a.margin_level:,.0f}%" if a.margin else ""
    return f"equity {a.equity:,.2f} {a.currency}, free margin {a.margin_free:,.2f}{lvl}"


def position_lines(mt5, symbol, labels):
    """One line per bot position on this market. labels = {magic: strategy label}."""
    ps = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic in labels]
    if not ps:
        return ["MT5: open: none"]
    s = mt5.symbol_info(symbol)
    d = s.digits if s is not None else 5
    cur = (mt5.account_info().currency if mt5.account_info() is not None else "")
    out = []
    for p in ps:
        side = "BUY" if p.type == 0 else "SELL"
        stop = _fmt(p.sl, d) if p.sl else "none"
        tp = f" | target {_fmt(p.tp, d)}" if p.tp else ""
        out.append(f"MT5: open: {labels[p.magic]} {side} {p.volume:g} lots @ {_fmt(p.price_open, d)} | "
                   f"stop {stop}{tp} | now {_fmt(p.price_current, d)} | P/L {p.profit:+,.2f} {cur}"
                   + (f" (swap {p.swap:+,.2f})" if getattr(p, "swap", 0) else ""))
    return out


def startup_lines(mt5, symbol, labels):
    return [account_line(mt5), symbol_line(mt5, symbol)] + position_lines(mt5, symbol, labels)


def poll_lines(mt5, symbol, runners, labels, pip, normal_spread=None):
    """After new candles: each strategy's new candle, then live price + account, then positions."""
    s = mt5.symbol_info(symbol)
    d = s.digits if s is not None else 5
    out = []
    for r in runners:
        lb = getattr(r, "last_bar", None)
        if getattr(r, "new_bars", 0) and lb is not None:
            out.append("MT5: " + candle_line(r.label, lb[0], lb[1], r.cfg["data"]["timeframe"], d))
    out.append(f"MT5: {price_part(mt5, symbol, pip, normal_spread)} | {equity_part(mt5)}")
    return out + position_lines(mt5, symbol, labels)
