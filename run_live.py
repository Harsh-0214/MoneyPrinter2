"""Live/demo runner.

    python run_live.py                       # demo account, EURUSD (default)
    python run_live.py --pair GBPUSD         # trade another pair from cfg['pairs']
    python run_live.py --dry-run             # log actions without sending orders
    python run_live.py --allow-live          # required to run on a real account

Runs the SAME morning stack and scored routing as the backtest
(cfg['strategies']['morning'] + fxbot.backtest.route_morning), including the
SMT feed from the pair's partner symbol. Run one process per pair; each pair
gets its own magic number (live.magic + index in cfg['pairs']).

Credentials are loaded from .env (see .env.example).
"""
import argparse
import logging
import os
import time
import zoneinfo
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

LONDON = zoneinfo.ZoneInfo("Europe/London")


def _setup_logging(tag):
    Path("logs").mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f"logs/live_{tag}_{today}.log"),
        ],
    )
    return logging.getLogger("fxbot")


log = logging.getLogger("fxbot")


class DryRunBroker:
    """Wraps MT5Broker and intercepts every order-changing call."""

    def __init__(self, real_broker):
        self._b = real_broker

    def equity(self):
        return self._b.equity()

    def position(self):
        return self._b.position()

    def current_spread_pips(self):
        return self._b.current_spread_pips()

    def submit(self, order):
        log.info("DRY RUN: would submit %s %d units SL=%.5f TP=%s tag=%s",
                 "BUY" if order.side == 1 else "SELL",
                 order.units, order.stop_loss,
                 f"{order.take_profit:.5f}" if order.take_profit else "None", order.tag)
        return False

    def close_position(self, reason="manual"):
        log.info("DRY RUN: would close position reason=%s", reason)

    def update_stop(self, new_stop_price):
        log.info("DRY RUN: would move stop to %.5f", new_stop_price)

    def shutdown(self):
        self._b.shutdown()

    @property
    def trades(self):
        return self._b.trades


class CappedEquityBroker:
    """Make the bot size and risk-check as if the account were `cap` dollars.

    Reported equity = cap + (real equity - real equity at start), so 0.5% risk
    means 0.5% of ~cap, and the daily-loss kill switch works on the same base.
    """

    def __init__(self, broker, cap):
        self._b = broker
        self._cap = float(cap)
        self._start = broker.equity()

    def equity(self):
        return self._cap + (self._b.equity() - self._start)

    def position(self): return self._b.position()
    def current_spread_pips(self): return self._b.current_spread_pips()
    def submit(self, order): return self._b.submit(order)
    def close_position(self, reason="manual"): return self._b.close_position(reason)
    def update_stop(self, new_stop_price): return self._b.update_stop(new_stop_price)
    def shutdown(self): return self._b.shutdown()

    @property
    def trades(self):
        return self._b.trades


class _NoOrderBroker:
    """Used while replaying today's bars at startup: state only, no orders."""

    def __init__(self, broker):
        self._b = broker
        self.trades = []

    def equity(self): return self._b.equity()
    def position(self): return self._b.position()
    def current_spread_pips(self): return self._b.current_spread_pips()
    def submit(self, order): return False
    def close_position(self, reason=""): pass
    def update_stop(self, new_stop_price): pass


def _sleep_to_next_bar(timeframe_minutes=5):
    """Sleep until 5 seconds after the next bar boundary."""
    now = datetime.now(timezone.utc).timestamp()
    bar_s = timeframe_minutes * 60
    wait = bar_s - (now % bar_s) + 5
    time.sleep(wait)


def _london_local(ts_utc):
    """Return (numpy datetime64[D], minutes since midnight) in London time.

    Same types the backtest passes to strategies.
    """
    import numpy as np
    local = ts_utc.astimezone(LONDON)
    return np.datetime64(local.date(), "D"), local.hour * 60 + local.minute


_EMA_CACHE = {}


def _add_daily_ema(mt5, symbol, cfg, bars):
    """Add the daily-trend column the strategies filter on, computed exactly like
    the backtest (fxbot.backtest.daily_ema_series) from ~320 days of H1 closes.
    Recomputed once per UTC day per symbol."""
    import pandas as pd
    from fxbot.backtest import daily_ema_series, trend_period
    from fxbot.data import server_ts_to_utc

    period = trend_period(cfg)
    key = (symbol, period, pd.Timestamp.now(tz="UTC").date())
    ema = _EMA_CACHE.get(key)
    if ema is None:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 24 * 320)
        if rates is None or len(rates) == 0:
            log.warning("No H1 history for %s - daily trend filter has no data", symbol)
            return
        h1 = pd.DataFrame(rates)
        h1.index = server_ts_to_utc(h1["time"].values)
        h1 = h1[h1.index.notna()]
        ema = daily_ema_series(h1["close"], period)
        _EMA_CACHE.clear()
        _EMA_CACHE[key] = ema
        uses_trend = any(s.get("ema_filter") or s.get("daily_trend_filter")
                         for s in cfg.get("strategies", {}).get("morning", []))
        if uses_trend:
            log.info("Daily trend: %d-day average of %s = %.5f", period, symbol, ema.iloc[-1])
    bars["daily_ema"] = ema.reindex(bars.index, method="ffill")


def _fetch_completed_bars(mt5, symbol, smt_symbol, cfg, start_utc):
    """M1 bars since start_utc -> completed 5-min bars with spread + SMT columns.

    The still-forming M1 bar and the still-forming 5-min bar are dropped, so a
    strategy never sees a partial candle (the backtest only sees closed bars).
    """
    import pandas as pd
    from fxbot.brokers import compute_spread_pips
    from fxbot.data import resample, server_ts_to_utc

    tf = cfg["data"]["timeframe"]
    tf_delta = pd.Timedelta(tf)
    # Timeframes MT5 serves directly (gold runs on 1h); others are built from M1
    native = {"1h": getattr(mt5, "TIMEFRAME_H1", None), "15min": getattr(mt5, "TIMEFRAME_M15", None)}
    mt_tf = native.get(tf) or mt5.TIMEFRAME_M1

    def _m1(sym):
        # Pad the start: MT5 indexes by server time (UTC+2/+3)
        rates = mt5.copy_rates_range(sym, mt_tf,
                                     (start_utc - timedelta(hours=4)).replace(tzinfo=None),
                                     (datetime.now(timezone.utc) + timedelta(hours=4)).replace(tzinfo=None))
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df.index = server_ts_to_utc(df["time"].values)
        df = df[df.index.notna()]
        cols = ["open", "high", "low", "close"]
        if "spread" in df.columns:
            df["data_spread_pips"] = df["spread"] / 10.0
            cols.append("data_spread_pips")
        return df[cols].iloc[:-1]          # drop the forming M1 bar

    m1 = _m1(symbol)
    if m1 is None or len(m1) == 0:
        return None
    bars = m1.copy() if mt_tf != mt5.TIMEFRAME_M1 else resample(m1, tf)
    now = pd.Timestamp.now(tz="UTC")
    bars = bars[bars.index + tf_delta <= now]          # completed bars only
    bars = bars[bars.index >= pd.Timestamp(start_utc)]
    bars["spread_pips"] = compute_spread_pips(bars, cfg["costs"])

    _add_daily_ema(mt5, symbol, cfg, bars)

    if smt_symbol:
        s1 = _m1(smt_symbol)
        if s1 is not None and len(s1):
            sb = (s1 if mt_tf != mt5.TIMEFRAME_M1 else resample(s1, tf))[["high", "low"]].reindex(bars.index)
            bars["smt_high"] = sb["high"]
            bars["smt_low"] = sb["low"]
    return bars


def _log_status_changes(strategies, local_min, last):
    """Log each strategy's 'what I see' line whenever it changes."""
    now = {}
    for s in strategies:
        if not hasattr(s, "describe"):
            continue
        try:
            st = s.describe(local_min).get("status", "")
        except Exception:
            continue
        now[type(s).__name__] = st
        if st and last.get(type(s).__name__) != st:
            log.info("STATUS %s", st)
    return now


def _log_closed_trade(broker):
    """A position disappeared (stop / target hit at the broker, or our close)."""
    try:
        trades = broker.trades
    except Exception:
        trades = []
    if not trades:
        log.info("CLOSED position (no deal details available)")
        return
    t = trades[-1]
    log.info("CLOSED %s %s %d units: entry %.5f -> exit %.5f  P/L %.2f  reason=%s",
             t.tag, "BUY" if t.side == 1 else "SELL", t.units, t.entry_price,
             t.exit_price, t.pnl, t.exit_reason)


def _overlay_path(mt5, symbol):
    """<MT5 common data>/Files/fxbot_<symbol>.txt, read by the FxbotOverlay indicator."""
    info = mt5.terminal_info()
    if info is None or not getattr(info, "commondata_path", None):
        return None
    d = Path(info.commondata_path) / "Files"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"fxbot_{symbol}.txt")


def _build_morning(cfg):
    from fxbot.backtest import STRATEGY_MAP, instrument_pip
    pip = instrument_pip(cfg)
    if "strategies" in cfg:
        return [STRATEGY_MAP[s["name"]](s, pip) for s in cfg["strategies"]["morning"]]
    s = cfg["strategy"]
    return [STRATEGY_MAP[s.get("name", "london_breakout")](s, pip)]


def _pair_entry(cfg, pair_name):
    pairs = cfg.get("pairs") or [{"symbol": "EURUSD"}]
    names = [p["symbol"] for p in pairs]
    if pair_name not in names:
        raise SystemExit(f"--pair {pair_name} not in config pairs {names}")
    return names.index(pair_name), pairs[names.index(pair_name)], names


def _broker_symbol(cfg, pair):
    return pair.get("broker_symbol") or pair["symbol"] + cfg["live"].get("symbol_suffix", ".")


def _resolve_pair(cfg, pair_name):
    """Return (broker_symbol, smt_broker_symbol, magic) for the chosen pair."""
    idx, pair, names = _pair_entry(cfg, pair_name)
    smt_path = (pair.get("smt") or {}).get("path", "")
    smt_name = next((n for n in names if n != pair_name and n in smt_path), None)
    smt_sym = _broker_symbol(cfg, _pair_entry(cfg, smt_name)[1]) if smt_name else None
    return (_broker_symbol(cfg, pair), smt_sym, int(cfg["live"]["magic"]) + idx)


def run(cfg, pair="EURUSD", dry_run=False, allow_live=False):
    import MetaTrader5 as mt5
    from fxbot.backtest import route_morning
    from fxbot.brokers.mt5_broker import MT5Broker
    from fxbot.data import PIP
    from fxbot.risk import RiskManager

    from fxbot.backtest import instrument_pip, pair_config

    symbol, smt_symbol, magic = _resolve_pair(cfg, pair)
    cfg = pair_config(cfg, _pair_entry(cfg, pair)[1])     # this market's strategies/costs/timeframe
    cfg["live"] = dict(cfg["live"], symbol=symbol, magic=magic)
    pip = instrument_pip(cfg)
    warmup_days = int(cfg.get("warmup_days", 0))
    log.info("Pair %s -> symbol=%s smt=%s magic=%d timeframe=%s strategies=%s",
             pair, symbol, smt_symbol, magic, cfg["data"]["timeframe"],
             [s["name"] for s in cfg["strategies"]["morning"]])

    consecutive_failures = 0
    while True:
        broker = None
        try:
            real_broker = MT5Broker(cfg, log, allow_live=allow_live)
            broker = DryRunBroker(real_broker) if dry_run else real_broker
            cap = cfg["live"].get("equity_cap")
            if cap:
                broker = CappedEquityBroker(broker, cap)
                log.info("Sizing as if equity = %.0f (live.equity_cap)", cap)
            for s in [symbol] + ([smt_symbol] if smt_symbol else []):
                mt5.symbol_select(s, True)

            # Fresh strategy objects every (re)connect, then replay today's
            # closed bars so ranges / sweeps / trades_today are rebuilt.
            morning = _build_morning(cfg)
            r_cfg = dict(cfg["risk"])
            if "min_units" in cfg.get("instrument", {}):
                r_cfg["min_units"] = cfg["instrument"]["min_units"]
            risk = RiskManager(r_cfg, pip)
            now_local = datetime.now(timezone.utc).astimezone(LONDON)
            day_start_utc = now_local.replace(hour=0, minute=0, second=0,
                                              microsecond=0).astimezone(timezone.utc)
            # Strategies that need history (gold trend: 55-day channel) replay
            # `warmup_days` of closed bars first; the London stack replays today only.
            replay_from = day_start_utc - timedelta(days=warmup_days)
            bars = _fetch_completed_bars(mt5, symbol, smt_symbol, cfg, replay_from)
            replay = _NoOrderBroker(broker)
            risk.new_day(broker.equity())
            fired_day, cur_day, last_ts = None, None, None
            if bars is not None:
                for bar in bars.itertuples():
                    day, lmin = _london_local(bar.Index.to_pydatetime())
                    cur_day = day
                    fired_day = route_morning(morning, bar, day, lmin, replay, risk, fired_day, int(cfg.get("slot_max_trades", 1)))
                    last_ts = bar.Index
            # A position already open from today means the morning slot is used
            if broker.position() is not None and cur_day is not None:
                fired_day = cur_day
                for s in morning:
                    s.mark_fired()
            log.info("Startup replay: %d bars, last=%s, slot_used=%s, position=%s",
                     0 if bars is None else len(bars), last_ts,
                     fired_day is not None, broker.position() is not None)
            risk.quote_to_account = real_broker.quote_to_account()
            acct = mt5.account_info()
            log.info("Account currency %s: 1 %s move per unit = %.4f %s (sizing uses this)",
                     acct.currency, symbol[3:6], risk.quote_to_account, acct.currency)
            log.info("Bot started. equity=%.2f dry_run=%s", broker.equity(), dry_run)
            overlay_path = _overlay_path(mt5, symbol)

            def _draw():
                if overlay_path is None:
                    return
                try:
                    from fxbot.overlay import build_lines, write_overlay
                    lmin = _london_local(datetime.now(timezone.utc))[1]
                    write_overlay(overlay_path, build_lines(morning, lmin, broker, symbol))
                except Exception as e:          # drawing must never stop trading
                    log.warning("overlay write failed: %s", e)

            _draw()
            last_status = _log_status_changes(morning, _london_local(datetime.now(timezone.utc))[1], {})
            consecutive_failures = 0

            while True:
                _sleep_to_next_bar()
                since = (last_ts.to_pydatetime() if last_ts is not None else day_start_utc)
                bars = _fetch_completed_bars(mt5, symbol, smt_symbol, cfg,
                                             since - timedelta(minutes=10))
                if bars is None or len(bars) == 0:
                    log.warning("No bars from MT5, retrying next bar")
                    continue
                new = bars[bars.index > last_ts] if last_ts is not None else bars
                had_pos = broker.position() is not None
                live_spread = broker.current_spread_pips()
                fx = getattr(real_broker, "quote_to_account", None)
                if fx is not None:
                    risk.quote_to_account = fx()
                for k, bar in enumerate(new.itertuples()):
                    day, lmin = _london_local(bar.Index.to_pydatetime())
                    if day != cur_day:
                        cur_day = day
                        risk.new_day(broker.equity())
                        log.info("New London day %s equity=%.2f", day, broker.equity())
                    if k == len(new) - 1:
                        # Size the newest bar's order on the actual live spread
                        bar = bar._replace(spread_pips=max(bar.spread_pips, live_spread))
                    fired_day = route_morning(morning, bar, day, lmin, broker, risk, fired_day, int(cfg.get("slot_max_trades", 1)))
                    last_ts = bar.Index
                    log.info("Bar %s spread=%.1fpip position=%s equity=%.2f",
                             bar.Index.astimezone(LONDON).strftime("%H:%M"), bar.spread_pips,
                             "open" if broker.position() is not None else "none",
                             broker.equity())
                if had_pos and broker.position() is None:
                    _log_closed_trade(broker)
                lmin_now = _london_local(datetime.now(timezone.utc))[1]
                last_status = _log_status_changes(morning, lmin_now, last_status)
                _draw()

        except KeyboardInterrupt:
            log.info("Bot stopped cleanly.")
            if broker is not None:
                try:
                    broker.shutdown()
                except Exception:
                    pass
            break

        except Exception as exc:
            consecutive_failures += 1
            log.error("Error (failure %d/5): %s", consecutive_failures, exc, exc_info=True)
            if broker is not None:
                try:
                    broker.shutdown()
                except Exception:
                    pass
            if consecutive_failures >= 5:
                log.error("5 consecutive failures — exiting.")
                break
            log.info("Reconnecting in 60s...")
            time.sleep(60)


def _single_instance_lock(pair):
    """Exclusive lock file per pair; returns the open handle, or None if taken.
    The OS releases it automatically when the process exits (even on a crash)."""
    Path("logs").mkdir(exist_ok=True)
    f = open(f"logs/.run_live_{pair}.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--pair", default="EURUSD")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-live", action="store_true")
    args = ap.parse_args()

    global log
    log = _setup_logging(args.pair)
    lock = _single_instance_lock(args.pair)        # keep the handle open for the process life
    if lock is None:
        log.error("Another run_live.py is already running for %s - exiting so trades "
                  "aren't doubled. Close the other one first.", args.pair)
        raise SystemExit(2)
    cfg = yaml.safe_load(open(args.config))
    if args.allow_live and not cfg["live"].get("allow_live", False):
        raise SystemExit("--allow-live also requires live.allow_live: true in config.yaml")
    run(cfg, pair=args.pair, dry_run=args.dry_run, allow_live=args.allow_live)


if __name__ == "__main__":
    main()
